"""Enrutador CLI multi-motor, post-procesador Z-Color T0..T3 y extractor de métricas."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import PrinterConfig, get_optimal_chamber_config, resolve_profile_id
from app.core.error_journal import record_error
from app.core.json_patcher import (
    DEFAULT_SLOT_COLORS,
    PatchedProfileSet,
    patch_profiles_for_job,
)
from app.models.schemas import SliceRequest

logger = logging.getLogger("slicerhub.slicer_router")

TIME_RE = re.compile(
    r";\s*(?:estimated printing time(?:\s*\([^)]*\))?|total estimated time)\s*[:=]\s*(.+)",
    re.IGNORECASE,
)
GRAMS_RE = re.compile(
    r";\s*(?:total\s+)?filament used\s*\[g\]\s*=\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
MM_RE = re.compile(
    r";\s*(?:total\s+)?filament used\s*\[mm\]\s*=\s*([0-9]+(?:\.[0-9]+)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SlicingResult:
    """Resultado de una ejecución CLI de laminado."""

    gcode_path: Path
    estimated_time: str
    estimated_time_seconds: int
    filament_grams: float
    filament_meters: float
    support_time_seconds: int = 0
    support_weight_g: float = 0.0
    support_percentage: float = 0.0


def _parse_time_to_seconds(est_time: str) -> int:
    total = 0
    for val, unit in re.findall(r"(\d+)\s*([dhms])", est_time.lower()):
        n = int(val)
        if unit == "d":
            total += n * 86400
        elif unit == "h":
            total += n * 3600
        elif unit == "m":
            total += n * 60
        elif unit == "s":
            total += n
    return total


def parse_gcode_metrics(
    gcode_path: Path,
) -> tuple[str, int, float, float, int, float, float]:
    """Extrae tiempo, gramos, metros y desglose real de soportes desde el `.gcode`."""
    content = gcode_path.read_text(encoding="utf-8", errors="ignore")
    lines = content.splitlines()
    sample = "\n".join(lines[:150] + lines[-150:])

    est_time = "N/D"
    m_time = TIME_RE.search(sample)
    if m_time:
        est_time = m_time.group(1).strip()
    est_seconds = _parse_time_to_seconds(est_time)

    grams = 0.0
    m_grams = GRAMS_RE.findall(sample)
    if m_grams:
        grams = round(float(m_grams[-1]), 2)

    meters = 0.0
    m_mm = MM_RE.findall(sample)
    if m_mm:
        meters = round(float(m_mm[-1]) / 1000.0, 3)

    # Calcular proporción real de extrusión en secciones ;TYPE:*support*
    total_e = 0.0
    support_e = 0.0
    is_support = False
    relative_e = True
    last_abs_e = 0.0
    e_re = re.compile(r"\bE(-?[0-9]+(?:\.[0-9]+)?)\b")

    for ln in lines:
        st = ln.strip()
        if not st:
            continue
        if st.startswith(";TYPE:"):
            is_support = "support" in st[6:].lower()
            continue
        if st.startswith("M82"):
            relative_e = False
            continue
        if st.startswith("M83"):
            relative_e = True
            continue
        if st.startswith("G92") and "E" in st:
            m_e = e_re.search(st)
            if m_e:
                last_abs_e = float(m_e.group(1))
            continue
        if st.startswith(("G0 ", "G1 ", "G2 ", "G3 ")) and "E" in st:
            m_e = e_re.search(st)
            if m_e:
                val = float(m_e.group(1))
                delta = val if relative_e else (val - last_abs_e)
                if not relative_e:
                    last_abs_e = val
                if delta > 0:
                    total_e += delta
                    if is_support:
                        support_e += delta

    sup_ratio = (support_e / total_e) if total_e > 1e-6 else 0.0
    sup_pct = round(sup_ratio * 100.0, 1)
    sup_weight_g = round(grams * sup_ratio, 2)
    sup_time_sec = int(round(est_seconds * sup_ratio))

    return est_time, est_seconds, grams, meters, sup_time_sec, sup_weight_g, sup_pct


def _extruder_for_z(
    z_val: float,
    request: SliceRequest,
) -> int:
    for r in request.z_color_ranges:
        if r.min_z <= z_val <= r.max_z:
            return r.extruder_index
    return request.model_extruder


def apply_multiextruder_and_z_painting(
    gcode_path: Path,
    request: SliceRequest | None,
) -> None:
    """Inyecta metadatos de color `T0..T3` e inserta cambios de cabezal por altura Z y soportes."""
    if request is None or resolve_profile_id(request.printer_id) != "creator5_pro":
        return

    slot_colors = list(DEFAULT_SLOT_COLORS)
    slot_temps = [request.nozzle_temp] * 4
    if request.extruders_config:
        for slot in request.extruders_config:
            slot_colors[slot.extruder_index] = slot.color_hex
            slot_temps[slot.extruder_index] = slot.nozzle_temp

    raw_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    color_header = f"; SLICERHUB_EXTRUDER_COLORS = {','.join(slot_colors)}"

    # Si el G-code ya posee cambios de herramienta nativos generados desde .3mf (ej. T0/T1/T2/T3)
    # y el usuario no definió rangos manuales de altura Z, preservar los cambios nativos intactos.
    has_native_multitool = bool(re.search(r"^(?:T[1-3])\b", raw_text, flags=re.M))
    needs_z_paint = len(request.z_color_ranges) > 0
    if (has_native_multitool and not needs_z_paint) or (not needs_z_paint and not request.supports):
        if "; HEADER_BLOCK_END" in raw_text:
            gcode_path.write_text(
                raw_text.replace("; HEADER_BLOCK_END", f"; HEADER_BLOCK_END\n{color_header}", 1),
                encoding="utf-8",
            )
        else:
            gcode_path.write_text(color_header + "\n" + raw_text, encoding="utf-8")
        return

    lines = raw_text.splitlines()
    out: list[str] = [color_header]

    waiting_z = False
    cur_z = 0.0
    current_feature_support = False
    active_tool = request.model_extruder
    printed_started = False

    def switch_to(target_tool: int) -> None:
        nonlocal active_tool
        if target_tool == active_tool:
            return
        prev_tool = active_tool
        active_tool = target_tool
        out.append(f"; SlicerHub Toolchange Z={cur_z:.2f}: T{prev_tool} -> T{target_tool}")
        out.append(f"T{target_tool}")

    for ln in lines:
        stripped = ln.strip()
        if stripped.startswith(";LAYER_CHANGE"):
            printed_started = True
            waiting_z = True
            out.append(ln)
            continue

        if waiting_z and stripped.startswith(";Z:"):
            waiting_z = False
            try:
                cur_z = float(stripped[3:])
            except ValueError:
                pass
            out.append(ln)
            if needs_z_paint and not current_feature_support:
                switch_to(_extruder_for_z(cur_z, request))
            continue

        if printed_started and stripped.startswith(";TYPE:"):
            tname = stripped[6:].strip().lower()
            is_sup = (
                "support" in tname
                or "skirt" in tname
                or "brim" in tname
                or "raft" in tname
            )
            current_feature_support = is_sup
            out.append(ln)
            target_tool = (
                request.support_extruder
                if (is_sup and request.supports)
                else _extruder_for_z(cur_z, request)
            )
            switch_to(target_tool)
            continue

        # Mantener rastreo si Flash Studio emitió T0..T3 explícito (ej. torre de purga)
        if printed_started and re.fullmatch(r"T[0-3]", stripped):
            active_tool = int(stripped[1])

        out.append(ln)

    gcode_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def inject_timelapse_commands(
    gcode_path: Path,
    request: SliceRequest | None,
) -> None:
    """Inserta `TIMELAPSE_TAKE_FRAME` en cada cambio de capa cuando `enable_timelapse=True` (solo Klipper/Moonraker)."""
    if not (request and request.enable_timelapse):
        return
    if resolve_profile_id(request.printer_id) == "creator5_pro":
        return
    raw_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    out: list[str] = ["; SLICERHUB_TIMELAPSE = 1"]
    for ln in raw_text.splitlines():
        out.append(ln)
        if ln.strip().startswith(";LAYER_CHANGE"):
            out.append("TIMELAPSE_TAKE_FRAME")
    gcode_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def apply_auto_leveling_gcode(
    gcode_path: Path,
    request: SliceRequest | None,
) -> None:
    """Activa o desactiva sondeo de nivelación (`BED_MESH_CALIBRATE`/`BED_LEVEL_*`/`G29`) en Klipper/Marlin."""
    if request is None:
        return
    profile_id = resolve_profile_id(request.printer_id)
    if profile_id == "creator5_pro":
        return

    raw_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    lines = raw_text.splitlines()
    start_zone_lines: list[str] = []
    for ln in lines:
        st = ln.strip()
        if st.startswith(";LAYER_CHANGE"):
            break
        if not st.startswith(";"):
            start_zone_lines.append(st.upper())

    has_mesh_load = any("BED_MESH_PROFILE LOAD=" in u for u in start_zone_lines)
    has_bed_mesh_cal = any("BED_MESH_CALIBRATE" in u for u in start_zone_lines)

    out: list[str] = []
    injected_after_g28 = False
    in_start_zone = True
    leveling_tokens = ("BED_MESH_CALIBRATE", "BED_LEVEL_1", "BED_LEVEL_2", "G29")

    for ln in lines:
        stripped = ln.strip()
        upper = stripped.upper()
        if stripped.startswith(";LAYER_CHANGE"):
            in_start_zone = False

        if not in_start_zone or stripped.startswith(";"):
            out.append(ln)
            continue

        if not request.auto_leveling and any(
            upper.startswith(tok) or f" {tok}" in upper for tok in leveling_tokens
        ):
            out.append(f"; SlicerHub sin nivelación previa: {stripped}")
            if not has_mesh_load and not injected_after_g28 and profile_id != "ender3_s1_pro":
                out.append("BED_MESH_PROFILE LOAD=default")
                injected_after_g28 = True
            continue

        out.append(ln)

        if not injected_after_g28 and upper.startswith("G28"):
            if not request.auto_leveling and not has_mesh_load and profile_id != "ender3_s1_pro":
                out.append("BED_MESH_PROFILE LOAD=default")
                injected_after_g28 = True
            elif request.auto_leveling and not has_bed_mesh_cal and profile_id in (
                "flsun_t1_pro",
                "flsun_v400",
                "flsun_sr",
            ):
                out.append("BED_MESH_CALIBRATE ADAPTIVE=1")
                injected_after_g28 = True

    gcode_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def apply_creator5_pro_chamber_gcode(
    gcode_path: Path,
    request: SliceRequest | None,
) -> None:
    """Inyecta precalentamiento y control de ventilación de cabina (`M106 P2`/`P3`) para Creator 5 Pro."""
    if request is None or resolve_profile_id(request.printer_id) != "creator5_pro":
        return

    active_mats: list[str] = []
    if request.extruders_config:
        if request.part_extruder_map:
            used_indices = {max(0, min(3, int(ext) - 1)) for ext in request.part_extruder_map.values()}
        else:
            used_indices = {request.model_extruder}
        if request.supports:
            used_indices.add(request.support_extruder)
        for zr in request.z_color_ranges:
            used_indices.add(zr.extruder_index)
        by_idx = {s.extruder_index: s.material for s in request.extruders_config}
        active_mats = [by_idx.get(i, request.material) for i in sorted(used_indices)]
    else:
        active_mats = [request.material]

    chamber_cfg = get_optimal_chamber_config(
        active_mats,
        override_temp=request.chamber_temp_target,
    )
    target_temp = int(chamber_cfg["target_temp"])
    max_safe = int(chamber_cfg["max_safe_temp"])
    mode = str(chamber_cfg["mode"])
    p2_fan = int(chamber_cfg["p2_fan"])
    p3_fan = int(chamber_cfg["p3_fan"])

    chamber_lines: list[str] = [
        f"; SLICERHUB_CHAMBER_TARGET = {target_temp}",
        f"; SLICERHUB_CHAMBER_MODE = {mode}",
    ]
    if mode == "preheat_closed":
        bed_soak = max(90, int(request.bed_temp))
        chamber_lines.extend(
            [
                f"; SlicerHub Precalentamiento Cabina ABS/ASA (Obj {target_temp}C)",
                f"M140 S{bed_soak}",
                f"M190 S{bed_soak}",
                f"M106 P2 S{p2_fan} ; Center_Fresh_Air_Input_Fan OFF (camara cerrada)",
                f"M106 P3 S{p3_fan} ; Filter_Unit_Fan 100% recirculacion ABS",
                "G4 P90000 ; Estabilizacion termica del habitaculo (90s)",
            ]
        )
    elif mode == "extraction":
        chamber_lines.extend(
            [
                f"; SlicerHub Extraccion Cabina PLA/TPU (Obj {target_temp}C / Max {max_safe}C)",
                f"M106 P2 S{p2_fan} ; Center_Fresh_Air_Input_Fan extraccion PLA/TPU",
                f"M106 P3 S{p3_fan} ; Filter_Unit_Fan renovacion de aire",
            ]
        )
    else:
        chamber_lines.extend(
            [
                f"; SlicerHub Recirculacion Cabina PETG (Obj {target_temp}C)",
                f"M106 P2 S{p2_fan} ; Center_Fresh_Air_Input_Fan OFF (recirculacion PETG)",
                f"M106 P3 S{p3_fan} ; Filter_Unit_Fan 40% recirculacion interna",
            ]
        )

    raw_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    lines = raw_text.splitlines()
    # Insertar justo después de ';start_gcode end' para que el start_gcode base no sobrescriba P2/P3
    insert_idx = next(
        (i + 1 for i, ln in enumerate(lines) if ln.strip() == ";start_gcode end"),
        None,
    )
    if insert_idx is None:
        insert_idx = next(
            (i + 1 for i, ln in enumerate(lines) if ln.strip() == "; EXECUTABLE_BLOCK_START"),
            0,
        )
    lines[insert_idx:insert_idx] = chamber_lines
    _atomic_write_text(gcode_path, "\n".join(lines) + "\n")


def _atomic_write_text(path: Path, text: str) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def _record_failed_cli_payload(
    patched: PatchedProfileSet,
    cmd: list[str],
    returncode: int,
    detail: str,
) -> None:
    """Registra en log y archivo de diagnóstico el JSON exacto que falló con señal negativa CLI."""
    process_payload: dict[str, object] = {}
    try:
        process_payload = json.loads(patched.process_json.read_text(encoding="utf-8"))
    except Exception:
        process_payload = {}
    relevant_keys = {
        k: process_payload.get(k)
        for k in (
            "enable_support",
            "support_type",
            "support_on_build_plate_only",
            "support_top_z_distance",
            "support_bottom_z_distance",
            "support_object_xy_distance",
            "support_interface_top_layers",
            "support_interface_spacing",
            "brim_type",
            "brim_width",
            "raft_layers",
            "layer_height",
            "enable_prime_tower",
            "prime_tower_width",
            "prime_tower_brim_width",
            "wipe_tower_cone_angle",
            "wipe_tower_rib_width",
            "initial_layer_speed",
            "initial_layer_flow_ratio",
        )
    }
    logger.error(
        "CLI falló con exit=%s | cmd=%s | process_keys=%s | detail=%s",
        returncode,
        " ".join(cmd),
        json.dumps(relevant_keys, ensure_ascii=False),
        detail,
    )
    diag = {
        "returncode": returncode,
        "cmd": cmd,
        "detail": detail,
        "process_keys": relevant_keys,
        "process_json_path": str(patched.process_json),
    }
    try:
        _atomic_write_text(
            patched.job_dir / "failed_cli_payload.json",
            json.dumps(diag, indent=2, ensure_ascii=False) + "\n",
        )
    except Exception:
        pass


def _build_slicer_cli_cmd(
    printer: PrinterConfig,
    model_paths: list[Path],
    patched: PatchedProfileSet,
    out_dir: Path,
    filament_ids: list[int] | None,
    arrange_mode: str = "0",
) -> tuple[list[str], bool]:
    filaments_arg = ";".join(str(p) for p in patched.filament_jsons)
    cmd = [
        str(printer.cli_binary),
        "--debug",
        "2",
        "--arrange",
        arrange_mode,
        "--ensure-on-bed",
        "--load-settings",
        f"{patched.machine_json};{patched.process_json}",
        "--load-filaments",
        filaments_arg,
    ]
    has_3mf = any(p.suffix.lower() == ".3mf" for p in model_paths)
    has_filament_ids = bool(filament_ids and len(filament_ids) == len(model_paths))
    if has_3mf or has_filament_ids:
        cmd.append("--no-check")
    if has_filament_ids:
        cmd.extend(["--load-filament-ids", ",".join(str(i) for i in filament_ids)])

    cmd.extend(["--slice", "0", "--outputdir", str(out_dir)])
    cmd.extend(str(p) for p in model_paths)
    return cmd, has_3mf


def run_slicer_cli(
    printer: PrinterConfig,
    stl_path: Path | list[Path],
    patched: PatchedProfileSet,
    request: SliceRequest | None = None,
    filament_ids: list[int] | None = None,
    timeout_sec: int = 150,
) -> SlicingResult:
    """Ejecuta el binario CLI en modo headless con escritura segura y reintento ante señal negativa."""
    out_dir = patched.job_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    model_paths = stl_path if isinstance(stl_path, list) else [stl_path]
    cmd, has_3mf = _build_slicer_cli_cmd(printer, model_paths, patched, out_dir, filament_ids)

    def _clean_out_dir() -> None:
        for stale in out_dir.glob("*"):
            try:
                if stale.is_file():
                    stale.unlink()
            except OSError:
                pass

    def _run_once(run_cmd: list[str], run_timeout: int) -> tuple[int, str, list[Path]]:
        run_kwargs: dict[str, Any] = {
            "capture_output": True,
            "text": True,
            "timeout": run_timeout,
            "cwd": str(patched.job_dir),
        }
        if sys.platform.startswith("win") and hasattr(subprocess, "CREATE_NO_WINDOW"):
            run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.run(run_cmd, **run_kwargs)
        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        err_lines = [ln for ln in combined.splitlines() if "[error]" in ln]
        detail_msg = "; ".join(err_lines[-5:]) if err_lines else combined[-500:]
        found = sorted(out_dir.glob("*.gcode"))
        return proc.returncode, detail_msg, found

    def _run_with_timeout_retry(run_cmd: list[str]) -> tuple[int, str, list[Path]]:
        try:
            return _run_once(run_cmd, timeout_sec)
        except subprocess.TimeoutExpired:
            retry_timeout = max(200, timeout_sec + 50)
            logger.warning(
                "Timeout (%ss) ejecutando %s; limpiando salida y reintentando con %ss...",
                timeout_sec,
                printer.cli_binary.name,
                retry_timeout,
            )
            _clean_out_dir()
            time.sleep(0.3)
            try:
                return _run_once(run_cmd, retry_timeout)
            except subprocess.TimeoutExpired:
                msg = (
                    f"Tiempo agotado ({timeout_sec}s + reintento {retry_timeout}s) "
                    f"ejecutando {printer.cli_binary.name}."
                )
                record_error(
                    "slicer_cli_timeout",
                    msg,
                    printer_id=printer.printer_id,
                    detail=f"job_dir={patched.job_dir.name} | cmd={' '.join(run_cmd)}",
                )
                raise RuntimeError(msg)

    returncode, detail, gcodes = _run_with_timeout_retry(cmd)

    # Ante señal fatal negativa (<0, p.ej. SIGBUS -10 o SIGSEGV -11), registrar JSON y reintentar 1 vez tras 300ms
    if returncode < 0:
        _record_failed_cli_payload(patched, cmd, returncode, detail)
        time.sleep(0.3)
        _clean_out_dir()
        retry_patched = patched
        if request is not None:
            retry_patched = patch_profiles_for_job(
                request,
                patched.job_dir,
                multimaterial_3mf=(has_3mf and resolve_profile_id(printer.printer_id) == "creator5_pro"),
                safe_clean_base=True,
            )
        retry_cmd, _ = _build_slicer_cli_cmd(
            printer, model_paths, retry_patched, out_dir, filament_ids
        )
        returncode, detail, gcodes = _run_with_timeout_retry(retry_cmd)
        if returncode == 0 and gcodes:
            logger.warning(
                "Recuperado tras señal negativa con reintento limpio en job_dir=%s",
                patched.job_dir.name,
            )

    # Ante error de área no imprimible (exit=154 / error_code = 4, p.ej. tras rotar o con torre de purga),
    # reintentar 1 vez permitiendo --arrange 1 para reacomodar dentro de la cama.
    is_unprintable_area = (
        returncode == 154
        or "unprintable area" in detail.lower()
        or "error_code = 4" in detail
    )
    if (returncode != 0 or not gcodes) and is_unprintable_area:
        logger.warning(
            "Detectado error de área no imprimible (exit=%s); reintentando con --arrange 1 en job_dir=%s",
            returncode,
            patched.job_dir.name,
        )
        for stale in out_dir.glob("*"):
            try:
                if stale.is_file():
                    stale.unlink()
            except OSError:
                pass
        arrange_cmd, _ = _build_slicer_cli_cmd(
            printer, model_paths, patched, out_dir, filament_ids, arrange_mode="1"
        )
        returncode, detail, gcodes = _run_with_timeout_retry(arrange_cmd)

    if returncode != 0 or not gcodes:
        err_msg = f"Error en laminado CLI ({printer.cli_binary.name}, exit={returncode}): {detail}"
        record_error(
            "slicer_cli",
            err_msg,
            printer_id=printer.printer_id,
            detail=f"job_dir={patched.job_dir.name} | cmd={' '.join(cmd)}",
            context={
                "returncode": returncode,
                "supports": bool(request.supports) if request else None,
                "support_type": request.support_type if request else None,
                "rot_x": request.rot_x if request else None,
                "rot_y": request.rot_y if request else None,
                "rot_z": request.rot_z if request else None,
            },
        )
        raise RuntimeError(err_msg)

    gcode_path = gcodes[0]
    apply_multiextruder_and_z_painting(gcode_path, request)
    inject_timelapse_commands(gcode_path, request)
    apply_auto_leveling_gcode(gcode_path, request)
    apply_creator5_pro_chamber_gcode(gcode_path, request)
    if request and request.lithophane_mode:
        raw_gc = gcode_path.read_text(encoding="utf-8", errors="ignore")
        if not raw_gc.startswith("; SLICERHUB_LITHOPHANE_MODE = 1"):
            _atomic_write_text(gcode_path, "; SLICERHUB_LITHOPHANE_MODE = 1\n" + raw_gc)
    est_time, est_sec, grams, meters, sup_sec, sup_g, sup_pct = parse_gcode_metrics(gcode_path)
    return SlicingResult(
        gcode_path=gcode_path,
        estimated_time=est_time,
        estimated_time_seconds=est_sec,
        filament_grams=grams,
        filament_meters=meters,
        support_time_seconds=sup_sec,
        support_weight_g=sup_g,
        support_percentage=sup_pct,
    )
