"""Grabador continuo de telemetría por impresión (0% → 100%) y compendios IA post-impresión."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.config import TEMP_DIR, resolve_profile_id
from app.core.ai_copilot import generate_post_print_compendium
from app.models.schemas import (
    MachineMaterialLearningRun,
    MachineMaterialLearningsResponse,
    PostPrintCompendium,
    PrinterLiveStatus,
    PrinterTelemetrySessionResponse,
    TelemetryPhaseStats,
    TelemetrySample,
    TelemetrySessionState,
    TelemetrySessionSummary,
)

logger = logging.getLogger("slicerhub.telemetry_recorder")

TELEMETRY_SESSIONS_DIR = TEMP_DIR / "telemetry_sessions"
COMPLETED_INDEX_PATH = TELEMETRY_SESSIONS_DIR / "completed_compendiums.json"

ACTIVE_STATES = {"printing", "heating", "busy", "paused"}
PROGRESS_MILESTONES: tuple[float, ...] = (1.0, 5.0, 15.0, 30.0, 50.0, 75.0, 90.0, 100.0)
SAMPLE_INTERVAL_SEC = 20.0
MAX_SAMPLES_PER_SESSION = 5000


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _slugify_filename(filename: str | None) -> str:
    stem = Path(filename or "trabajo").stem
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return (cleaned[:48] or "print_job")


def _min_avg_max(values: list[float]) -> tuple[float | None, float | None, float | None]:
    if not values:
        return None, None, None
    return round(min(values), 2), round(sum(values) / len(values), 2), round(max(values), 2)


def _compute_phase_stats(samples: list[dict[str, Any]]) -> TelemetryPhaseStats:
    if not samples:
        return TelemetryPhaseStats(samples_count=0)
    active_noz = [
        float(s["nozzle_temp"])
        for s in samples
        if s.get("nozzle_temp") is not None
        and float(s["nozzle_temp"]) >= 150.0
        and (s.get("nozzle_target") is None or float(s["nozzle_target"]) >= 150.0)
    ]
    noz = active_noz or [float(s["nozzle_temp"]) for s in samples if s.get("nozzle_temp") is not None]
    active_bed = [
        float(s["bed_temp"])
        for s in samples
        if s.get("bed_temp") is not None
        and float(s["bed_temp"]) >= 35.0
        and (s.get("bed_target") is None or float(s["bed_target"]) >= 35.0)
    ]
    bed = active_bed or [float(s["bed_temp"]) for s in samples if s.get("bed_temp") is not None]
    mcu = [float(s["mcu_temp"]) for s in samples if s.get("mcu_temp") is not None]
    host = [float(s["host_temp"]) for s in samples if s.get("host_temp") is not None]
    spd = [float(s["speed_mms"]) for s in samples if s.get("speed_mms") is not None and float(s["speed_mms"]) > 0]
    fan = [float(s["fan_pct"]) for s in samples if s.get("fan_pct") is not None]

    noz_min, noz_avg, noz_max = _min_avg_max(noz)
    bed_min, bed_avg, bed_max = _min_avg_max(bed)
    mcu_min, mcu_avg, mcu_max = _min_avg_max(mcu)
    host_min, host_avg, host_max = _min_avg_max(host)
    spd_min, spd_avg, spd_max = _min_avg_max(spd)
    fan_avg = round(sum(fan) / len(fan), 1) if fan else None

    return TelemetryPhaseStats(
        samples_count=len(samples),
        nozzle_min=noz_min,
        nozzle_avg=noz_avg,
        nozzle_max=noz_max,
        bed_min=bed_min,
        bed_avg=bed_avg,
        bed_max=bed_max,
        mcu_min=mcu_min,
        mcu_avg=mcu_avg,
        mcu_max=mcu_max,
        host_min=host_min,
        host_avg=host_avg,
        host_max=host_max,
        speed_min=spd_min,
        speed_avg=spd_avg,
        speed_max=spd_max,
        fan_avg=fan_avg,
    )


def compute_session_summary(session: dict[str, Any]) -> TelemetrySessionSummary:
    """Calcula estadísticas consolidadas por fases y anomalías sobre las muestras."""
    samples: list[dict[str, Any]] = list(session.get("samples") or [])
    if not samples:
        return TelemetrySessionSummary()

    p_init = [s for s in samples if float(s.get("progress_pct", 0.0)) < 5.0]
    p_mid = [s for s in samples if 5.0 <= float(s.get("progress_pct", 0.0)) < 85.0]
    p_fin = [s for s in samples if float(s.get("progress_pct", 0.0)) >= 85.0]

    anomalies: list[str] = []
    noz_drops = [
        s
        for s in samples
        if s.get("nozzle_target")
        and float(s["nozzle_target"]) >= 160
        and s.get("nozzle_temp") is not None
        and float(s["nozzle_temp"]) >= 150.0
        and 2.0 <= float(s.get("progress_pct", 0.0)) < 99.5
        and str(s.get("printer_state") or "").lower() not in ("completed", "idle", "standby", "cancelled")
        and abs(float(s["nozzle_temp"]) - float(s["nozzle_target"])) >= 6.0
    ]
    if noz_drops:
        anomalies.append(
            f"Desviación térmica de boquilla >=6°C detectada en {len(noz_drops)} muestra(s)."
        )

    bed_drops = [
        s
        for s in samples
        if s.get("bed_target")
        and float(s["bed_target"]) >= 40
        and s.get("bed_temp") is not None
        and float(s.get("progress_pct", 0.0)) >= 1.0
        and abs(float(s["bed_temp"]) - float(s["bed_target"])) >= 5.0
    ]
    if bed_drops:
        anomalies.append(
            f"Oscilación de cama >=5°C detectada en {len(bed_drops)} muestra(s)."
        )

    mcu_hot = [s for s in samples if s.get("mcu_temp") is not None and float(s["mcu_temp"]) >= 65.0]
    if mcu_hot:
        peak_mcu = max(float(s["mcu_temp"]) for s in mcu_hot)
        anomalies.append(f"Temperatura elevada de MCU (pico {peak_mcu:.1f}°C).")

    host_hot = [s for s in samples if s.get("host_temp") is not None and float(s["host_temp"]) >= 72.0]
    if host_hot:
        peak_host = max(float(s["host_temp"]) for s in host_hot)
        anomalies.append(f"Temperatura elevada de Host SBC (pico {peak_host:.1f}°C).")

    first_ts = float(samples[0]["timestamp"])
    last_ts = float(samples[-1]["timestamp"])
    dur_recorded = max(0, int(round(last_ts - first_ts)))
    real_elapsed = samples[-1].get("elapsed_seconds")
    est_total = session.get("estimated_total_seconds")
    fil_g = max((float(s.get("filament_used_g") or 0.0) for s in samples), default=0.0)

    return TelemetrySessionSummary(
        samples_count=len(samples),
        duration_recorded_seconds=dur_recorded,
        real_elapsed_seconds=int(real_elapsed) if real_elapsed is not None else None,
        estimated_total_seconds=int(est_total) if est_total is not None else None,
        filament_used_g=round(fil_g, 2),
        overall=_compute_phase_stats(samples),
        phase_initial_0_5=_compute_phase_stats(p_init),
        phase_middle_5_85=_compute_phase_stats(p_mid),
        phase_final_85_100=_compute_phase_stats(p_fin),
        anomalies=anomalies,
    )


class PrintTelemetryRecorder:
    """Gestor persistente de sesiones de telemetría 0–100% y compendios IA."""

    def __init__(self) -> None:
        self._active_by_printer: dict[str, dict[str, Any]] = {}
        self._session_paths: dict[str, Path] = {}
        self._completed_compendiums: list[dict[str, Any]] = []
        self._last_ingest_ts: dict[str, float] = {}
        self._finalizing_ids: set[str] = set()
        self._loaded = False

    def load_persisted_state(self) -> None:
        if self._loaded:
            return
        TELEMETRY_SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        if COMPLETED_INDEX_PATH.is_file():
            try:
                raw = json.loads(COMPLETED_INDEX_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    self._completed_compendiums = raw[:60]
            except Exception:
                self._completed_compendiums = []

        # Recuperar sesiones activas que quedaron grabando tras reinicio
        for p in sorted(TELEMETRY_SESSIONS_DIR.glob("*.json")):
            if p.name == COMPLETED_INDEX_PATH.name:
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("status") == "recording":
                    pid = str(data.get("printer_id") or "")
                    if pid:
                        self._active_by_printer[pid] = data
                        self._session_paths[pid] = p
            except Exception:
                continue
        self._loaded = True

    def _save_active_session(self, printer_id: str) -> None:
        session = self._active_by_printer.get(printer_id)
        path = self._session_paths.get(printer_id)
        if session and path:
            _atomic_write_json(path, session)

    def _append_completed_compendium(self, comp: PostPrintCompendium) -> None:
        comp_dict = comp.model_dump()
        self._completed_compendiums = [
            c
            for c in self._completed_compendiums
            if c.get("session_id") != comp.session_id
        ]
        self._completed_compendiums.insert(0, comp_dict)
        self._completed_compendiums = self._completed_compendiums[:60]
        _atomic_write_json(COMPLETED_INDEX_PATH, self._completed_compendiums)

    def _build_sample(self, status: PrinterLiveStatus, now_ts: float) -> dict[str, Any]:
        sample = TelemetrySample(
            timestamp=round(now_ts, 3),
            iso_time=datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
            progress_pct=round(float(status.progress_percent or 0.0), 2),
            layer_current=status.current_layer,
            layer_total=status.total_layers,
            nozzle_temp=status.nozzle_temp,
            nozzle_target=status.nozzle_target,
            bed_temp=status.bed_temp,
            bed_target=status.bed_target,
            mcu_temp=status.mcu_temp,
            host_temp=status.host_temp,
            chamber_temp=status.chamber_temp,
            speed_mms=status.print_speed_mms,
            speed_factor=float(status.speed_factor_percent or 100.0),
            flow_factor=float(status.flow_factor_percent or 100.0),
            fan_pct=float(status.fan_speed_percent or 0.0),
            filament_used_g=float(status.filament_used_g or 0.0),
            elapsed_seconds=status.elapsed_seconds,
        )
        return sample.model_dump()

    def _should_record_sample(
        self,
        session: dict[str, Any],
        status: PrinterLiveStatus,
        now_ts: float,
    ) -> bool:
        samples: list[dict[str, Any]] = session.get("samples") or []
        if not samples:
            return True
        if len(samples) >= MAX_SAMPLES_PER_SESSION:
            return False
        last_ts = float(samples[-1]["timestamp"])
        if now_ts - last_ts >= SAMPLE_INTERVAL_SEC:
            return True
        prev_pct = float(samples[-1].get("progress_pct", 0.0))
        cur_pct = float(status.progress_percent or 0.0)
        for m in PROGRESS_MILESTONES:
            if prev_pct < m <= cur_pct:
                return True
        return False

    def _start_new_session(self, status: PrinterLiveStatus, now_ts: float) -> dict[str, Any]:
        pid = status.printer_id
        fname = status.current_file or "impresion_activa.gcode"
        slug = _slugify_filename(fname)
        ts_str = datetime.fromtimestamp(now_ts, tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        session_id = f"{pid}_{slug}_{ts_str}"
        path = TELEMETRY_SESSIONS_DIR / f"{session_id}.json"

        est_total = None
        if status.elapsed_seconds is not None and status.eta_seconds is not None:
            est_total = int(status.elapsed_seconds + status.eta_seconds)

        session: dict[str, Any] = {
            "session_id": session_id,
            "printer_id": pid,
            "display_name": status.display_name,
            "filename": fname,
            "status": "recording",
            "started_at": datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat(),
            "ended_at": None,
            "last_progress_pct": round(float(status.progress_percent or 0.0), 2),
            "estimated_total_seconds": est_total,
            "samples": [self._build_sample(status, now_ts)],
            "compendium": None,
        }
        self._active_by_printer[pid] = session
        self._session_paths[pid] = path
        _atomic_write_json(path, session)
        return session

    async def _finalize_session(
        self,
        printer_id: str,
        final_status: str,
        now_ts: float,
    ) -> None:
        session = self._active_by_printer.pop(printer_id, None)
        path = self._session_paths.pop(printer_id, None)
        if not session or not path:
            return
        sid = str(session.get("session_id") or "")
        if sid in self._finalizing_ids:
            return
        self._finalizing_ids.add(sid)
        try:
            session["status"] = final_status
            session["ended_at"] = datetime.fromtimestamp(now_ts, tz=timezone.utc).isoformat()
            summary = compute_session_summary(session)
            session["live_stats"] = summary.model_dump()
            _atomic_write_json(path, session)

            # Generar compendio final con DeepSeek API en hilo separado
            if summary.samples_count >= 1:
                comp = await asyncio.to_thread(
                    generate_post_print_compendium, session, False
                )
                session["compendium"] = comp.model_dump()
                _atomic_write_json(path, session)
                self._append_completed_compendium(comp)
                logger.info(
                    "Compendio post-impresión generado para %s (%s, %s).",
                    printer_id,
                    session.get("filename"),
                    comp.provider,
                )
        except Exception as exc:
            logger.warning("Error finalizando sesión de telemetría %s: %s", sid, exc)
        finally:
            self._finalizing_ids.discard(sid)

    def ingest_status(self, status: PrinterLiveStatus) -> None:
        """Procesa un snapshot en vivo: inicia/reanuda grabación, guarda muestras o cierra al terminar."""
        self.load_persisted_state()
        if not status.online:
            return

        pid = status.printer_id
        now_ts = time.time()
        self._last_ingest_ts[pid] = now_ts
        state_lower = (status.state or "").strip().lower()
        is_active = state_lower in ACTIVE_STATES

        existing = self._active_by_printer.get(pid)

        if is_active:
            cur_file = status.current_file or ""
            if existing is None:
                self._start_new_session(status, now_ts)
                return

            prev_file = str(existing.get("filename") or "")
            # Si cambió de archivo a un nuevo trabajo distinto, cerrar el anterior y abrir nuevo
            if (
                cur_file
                and prev_file
                and cur_file != prev_file
                and not prev_file.startswith("impresion_activa")
            ):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._finalize_session(pid, "completed", now_ts))
                except RuntimeError:
                    pass
                self._start_new_session(status, now_ts)
                return

            if cur_file and (not prev_file or prev_file == "impresion_activa.gcode"):
                existing["filename"] = cur_file

            if status.elapsed_seconds is not None and status.eta_seconds is not None:
                existing["estimated_total_seconds"] = int(
                    status.elapsed_seconds + status.eta_seconds
                )
            existing["last_progress_pct"] = round(
                max(float(existing.get("last_progress_pct", 0.0)), float(status.progress_percent or 0.0)),
                2,
            )

            if self._should_record_sample(existing, status, now_ts):
                existing.setdefault("samples", []).append(self._build_sample(status, now_ts))
                self._save_active_session(pid)
            return

        # Estado no activo (`complete`, `standby`, `ready`, `idle`, `cancelled`, `error`)
        if existing is not None:
            last_pct = float(existing.get("last_progress_pct", 0.0))
            cur_pct = float(status.progress_percent or 0.0)
            peak_pct = max(last_pct, cur_pct)
            if state_lower == "cancelled":
                final_status = "cancelled"
            elif state_lower == "complete" or peak_pct >= 95.0:
                final_status = "completed"
            elif peak_pct >= 1.0:
                final_status = "completed"
            else:
                final_status = "cancelled"

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._finalize_session(pid, final_status, now_ts))
            except RuntimeError:
                pass

    def get_printer_session(self, printer_id: str) -> PrinterTelemetrySessionResponse:
        self.load_persisted_state()
        active_raw = self._active_by_printer.get(printer_id)
        active_state: TelemetrySessionState | None = None
        if active_raw:
            summary = compute_session_summary(active_raw)
            comp_raw = active_raw.get("compendium")
            active_state = TelemetrySessionState(
                session_id=str(active_raw["session_id"]),
                printer_id=printer_id,
                display_name=str(active_raw.get("display_name") or printer_id),
                filename=str(active_raw.get("filename") or ""),
                status="recording",
                started_at=str(active_raw.get("started_at") or ""),
                ended_at=active_raw.get("ended_at"),
                samples_count=summary.samples_count,
                duration_recorded_seconds=summary.duration_recorded_seconds,
                last_progress_pct=float(active_raw.get("last_progress_pct", 0.0)),
                live_stats=summary,
                compendium=PostPrintCompendium.model_validate(comp_raw) if comp_raw else None,
            )

        printer_history: list[PostPrintCompendium] = []
        for item in self._completed_compendiums:
            if item.get("printer_id") == printer_id:
                try:
                    printer_history.append(PostPrintCompendium.model_validate(item))
                except Exception:
                    continue

        last_comp = printer_history[0] if printer_history else None
        return PrinterTelemetrySessionResponse(
            printer_id=printer_id,
            active_session=active_state,
            last_compendium=last_comp,
            history=printer_history[:15],
        )

    async def generate_compendium_now(
        self,
        printer_id: str,
        current_status: PrinterLiveStatus | None = None,
    ) -> PostPrintCompendium:
        """Genera o regenera el compendio acumulado hasta el instante actual."""
        self.load_persisted_state()
        if current_status is not None:
            self.ingest_status(current_status)

        active_raw = self._active_by_printer.get(printer_id)
        if active_raw is not None:
            summary = compute_session_summary(active_raw)
            active_raw["live_stats"] = summary.model_dump()
            comp = await asyncio.to_thread(
                generate_post_print_compendium, active_raw, True
            )
            active_raw["compendium"] = comp.model_dump()
            self._save_active_session(printer_id)
            return comp

        # Si no hay sesión activa, buscar última sesión en disco o en historial completado
        for item in self._completed_compendiums:
            if item.get("printer_id") == printer_id:
                session_file = TELEMETRY_SESSIONS_DIR / f"{item.get('session_id')}.json"
                if session_file.is_file():
                    sess_data = json.loads(session_file.read_text(encoding="utf-8"))
                    sess_data["live_stats"] = compute_session_summary(sess_data).model_dump()
                    comp = await asyncio.to_thread(
                        generate_post_print_compendium, sess_data, False
                    )
                    sess_data["compendium"] = comp.model_dump()
                    _atomic_write_json(session_file, sess_data)
                    self._append_completed_compendium(comp)
                    return comp
                return PostPrintCompendium.model_validate(item)

        raise ValueError(
            f"No hay sesión de telemetría grabada ni compendio previo para {printer_id}."
        )

    def should_poll_printer(self, printer_id: str, max_age_sec: float = 9.0) -> bool:
        last_ts = self._last_ingest_ts.get(printer_id, 0.0)
        return (time.time() - last_ts) >= max_age_sec


telemetry_recorder = PrintTelemetryRecorder()


async def telemetry_recorder_worker(
    poll_all_fn: Callable[[], Awaitable[list[PrinterLiveStatus]]],
    interval_sec: float = 10.0,
) -> None:
    """Bucle en segundo plano que mantiene la grabación continua aunque el UI esté cerrado."""
    telemetry_recorder.load_persisted_state()
    while True:
        try:
            statuses = await poll_all_fn()
            for st in statuses:
                telemetry_recorder.ingest_status(st)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Error en telemetry_recorder_worker: %s", exc)
        await asyncio.sleep(interval_sec)


def get_machine_material_learnings(
    printer_id: str,
    material: str,
    limit: int = 3,
) -> MachineMaterialLearningsResponse:
    """Lee `completed_compendiums.json` y extrae aprendizajes reales por máquina/alias y material."""
    telemetry_recorder.load_persisted_state()
    target_profile = resolve_profile_id(printer_id) if printer_id else ""
    target_mat = (material or "PLA").strip().upper()
    if target_mat == "SOPORTE":
        target_mat = "PLA"

    raw_items: list[dict[str, Any]] = []
    if COMPLETED_INDEX_PATH.is_file():
        try:
            loaded = json.loads(COMPLETED_INDEX_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, list):
                raw_items = [x for x in loaded if isinstance(x, dict)]
        except Exception:
            raw_items = []
    if not raw_items:
        raw_items = list(telemetry_recorder._completed_compendiums)

    exact_matches: list[dict[str, Any]] = []
    alias_matches: list[dict[str, Any]] = []

    for item in raw_items:
        if item.get("is_partial"):
            continue
        item_mat = str(item.get("detected_material") or "").strip().upper()
        if item_mat != target_mat:
            continue
        item_pid = str(item.get("printer_id") or "")
        if item_pid == printer_id:
            exact_matches.append(item)
        elif target_profile and resolve_profile_id(item_pid) == target_profile:
            alias_matches.append(item)

    all_matched = exact_matches + alias_matches
    total_count = len(all_matched)
    top_runs = all_matched[: max(1, limit)]

    noz_vals: list[float] = []
    bed_vals: list[float] = []
    spd_vals: list[float] = []
    mcu_vals: list[float] = []
    seen_imps: set[str] = set()
    accumulated_improvements: list[str] = []
    recent_runs: list[MachineMaterialLearningRun] = []

    for r in top_runs:
        overall = (r.get("stats") or {}).get("overall") or {}
        noz_avg = overall.get("nozzle_avg")
        noz_min = overall.get("nozzle_min")
        bed_avg = overall.get("bed_avg")
        spd_avg = overall.get("speed_avg")
        mcu_max = overall.get("mcu_max")
        if noz_avg is not None and float(noz_avg) >= 180.0 and (noz_min is None or float(noz_min) >= 150.0):
            noz_vals.append(float(noz_avg))
        if bed_avg is not None and float(bed_avg) >= 40.0:
            bed_vals.append(float(bed_avg))
        if spd_avg is not None:
            spd_vals.append(float(spd_avg))
        if mcu_max is not None:
            mcu_vals.append(float(mcu_max))

        imps = [str(x).strip() for x in (r.get("improvements") or []) if str(x).strip()]
        for imp in imps:
            # Filtrar falsos positivos de enfriamiento en sesiones legadas (boquilla < 150°C)
            if "osciló entre " in imp and noz_min is not None and float(noz_min) < 150.0:
                continue
            cat_key = imp.split("(")[0].split(":")[0].strip().lower()
            if imp not in seen_imps and cat_key not in seen_imps:
                seen_imps.add(imp)
                seen_imps.add(cat_key)
                accumulated_improvements.append(imp)

        recent_runs.append(
            MachineMaterialLearningRun(
                compendium_id=str(r.get("compendium_id") or ""),
                printer_id=str(r.get("printer_id") or ""),
                filename=str(r.get("filename") or ""),
                rating=str(r.get("rating") or "BUENA_CON_MEJORAS"),
                nozzle_avg=float(noz_avg) if noz_avg is not None else None,
                bed_avg=float(bed_avg) if bed_avg is not None else None,
                speed_avg=float(spd_avg) if spd_avg is not None else None,
                generated_at=str(r.get("generated_at") or ""),
                improvements=imps[:4],
            )
        )

    return MachineMaterialLearningsResponse(
        printer_id=printer_id,
        profile_id=target_profile or printer_id,
        material=target_mat,
        runs_count=total_count,
        avg_nozzle_temp=round(sum(noz_vals) / len(noz_vals), 1) if noz_vals else None,
        avg_bed_temp=round(sum(bed_vals) / len(bed_vals), 1) if bed_vals else None,
        avg_speed_mms=round(sum(spd_vals) / len(spd_vals), 1) if spd_vals else None,
        avg_mcu_max=round(sum(mcu_vals) / len(mcu_vals), 1) if mcu_vals else None,
        accumulated_improvements=accumulated_improvements[:6],
        recent_runs=recent_runs,
    )
