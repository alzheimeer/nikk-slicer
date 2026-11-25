"""Grabador local de Timelapse en segundo plano por impresora (`printer_id`) vía cámara MJPEG `:8080`."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import struct
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from app.config import TEMP_DIR
from app.models.schemas import PrinterLiveStatus

logger = logging.getLogger("slicerhub.local_timelapse")

TIMELAPSE_DIR = TEMP_DIR / "timelapses"
ACTIVE_TIMELAPSES_PATH = TIMELAPSE_DIR / "active_sessions.json"
COMPLETED_TIMELAPSES_PATH = TIMELAPSE_DIR / "completed_timelapses.json"
ARMED_PRINTERS_PATH = TIMELAPSE_DIR / "armed_printers.json"

ACTIVE_STATES = {"printing", "heating", "busy", "paused"}
MAX_FRAMES_PER_SESSION = 3000
MIN_CAPTURE_INTERVAL_SEC = 3.0
FALLBACK_CAPTURE_INTERVAL_SEC = 25.0


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _slugify(name: str | None) -> str:
    stem = Path(name or "print").stem
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_")
    return cleaned[:48] or "print_job"


async def grab_single_jpeg_from_camera(camera_url: str, timeout: float = 4.0) -> bytes | None:
    """Captura exactamente 1 frame JPEG desde un stream MJPEG (`?action=stream`) o snapshot y cierra al instante."""
    if not camera_url:
        return None
    buf = bytearray()
    try:
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            async with client.stream("GET", camera_url) as resp:
                if resp.status_code != 200:
                    return None
                ctype = str(resp.headers.get("content-type", "")).lower()
                if "image/jpeg" in ctype or "image/jpg" in ctype:
                    data = await resp.aread()
                    return data if data.startswith(b"\xff\xd8") else None

                async for chunk in resp.aiter_bytes(8192):
                    buf.extend(chunk)
                    start = buf.find(b"\xff\xd8")
                    if start >= 0:
                        end = buf.find(b"\xff\xd9", start + 2)
                        if end >= 0:
                            return bytes(buf[start : end + 2])
                    if len(buf) > 2 * 1024 * 1024:
                        break
    except (httpx.HTTPError, OSError, asyncio.TimeoutError):
        return None
    return None


def write_mjpeg_avi(frame_paths: list[Path], out_avi_path: Path, fps: int = 15) -> Path:
    """Empaqueta JPEGs crudos en un contenedor `.avi` MJPEG estándar (0 re-codificación, 0 dependencias)."""
    frames = [p.read_bytes() for p in frame_paths if p.is_file()]
    if not frames:
        raise ValueError("No hay frames JPEG para generar AVI.")

    with Image.open(frame_paths[0]) as im0:
        width, height = im0.size

    usec_per_frame = int(1_000_000 / max(1, fps))

    # Construir chunks '00dc' dentro de LIST 'movi'
    movi_chunks = bytearray()
    idx1_entries = bytearray()
    offset = 4  # relativo al inicio de 'movi' (después del FourCC 'movi')
    max_frame_size = 0

    for jpg in frames:
        size = len(jpg)
        max_frame_size = max(max_frame_size, size)
        pad = b"\x00" if (size % 2 == 1) else b""
        movi_chunks.extend(b"00dc" + struct.pack("<I", size) + jpg + pad)
        idx1_entries.extend(struct.pack("<4sIII", b"00dc", 0x10, offset, size))
        offset += 8 + size + len(pad)

    avih = struct.pack(
        "<14I",
        usec_per_frame,
        max_frame_size * fps,
        0,
        0x10,  # AVIF_HASINDEX
        len(frames),
        0,
        1,
        max_frame_size,
        width,
        height,
        0,
        0,
        0,
        0,
    )
    avih_chunk = b"avih" + struct.pack("<I", len(avih)) + avih

    strh = struct.pack(
        "<4s4sIHHIIIIIIIIhhhh",
        b"vids",
        b"MJPG",
        0,
        0,
        0,
        0,
        1,
        fps,
        0,
        len(frames),
        max_frame_size,
        0xFFFFFFFF,
        0,
        0,
        0,
        width,
        height,
    )
    strh_chunk = b"strh" + struct.pack("<I", len(strh)) + strh

    strf = struct.pack(
        "<IiiHH4sIiiII",
        40,
        width,
        height,
        1,
        24,
        b"MJPG",
        width * height * 3,
        0,
        0,
        0,
        0,
    )
    strf_chunk = b"strf" + struct.pack("<I", len(strf)) + strf

    strl_body = b"strl" + strh_chunk + strf_chunk
    strl_list = b"LIST" + struct.pack("<I", len(strl_body)) + strl_body

    hdrl_body = b"hdrl" + avih_chunk + strl_list
    hdrl_list = b"LIST" + struct.pack("<I", len(hdrl_body)) + hdrl_body

    movi_body = b"movi" + bytes(movi_chunks)
    movi_list = b"LIST" + struct.pack("<I", len(movi_body)) + movi_body

    idx1_chunk = b"idx1" + struct.pack("<I", len(idx1_entries)) + bytes(idx1_entries)

    riff_body = b"AVI " + hdrl_list + movi_list + idx1_chunk
    riff = b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body

    out_avi_path.parent.mkdir(parents=True, exist_ok=True)
    out_avi_path.write_bytes(riff)
    return out_avi_path


def build_animated_webp(frame_paths: list[Path], out_webp_path: Path, fps: int = 15) -> Path:
    """Ensambla frames JPEG en un WebP animado reproducible directo en el navegador / app."""
    imgs: list[Image.Image] = []
    try:
        for p in frame_paths:
            if not p.is_file():
                continue
            im = Image.open(p).convert("RGB")
            if im.width > 960:
                new_h = max(1, int(im.height * (960 / im.width)))
                im = im.resize((960, new_h), Image.Resampling.BILINEAR)
            imgs.append(im)
        if not imgs:
            raise ValueError("No hay frames válidos para WebP.")
        duration_ms = max(40, int(1000 / max(1, fps)))
        out_webp_path.parent.mkdir(parents=True, exist_ok=True)
        imgs[0].save(
            out_webp_path,
            format="WEBP",
            save_all=True,
            append_images=imgs[1:],
            duration=duration_ms,
            loop=0,
            quality=80,
            method=4,
        )
        return out_webp_path
    finally:
        for im in imgs:
            im.close()


class LocalTimelapseRecorder:
    """Gestor de grabación de timelapses en segundo plano indexado por `printer_id`."""

    def __init__(self) -> None:
        self._loaded = False
        self._active_by_printer: dict[str, dict[str, Any]] = {}
        self._completed: list[dict[str, Any]] = []
        self._armed_printers: set[str] = set()
        self._capture_locks: dict[str, asyncio.Lock] = {}
        self._finalizing_ids: set[str] = set()

    def load_persisted_state(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        TIMELAPSE_DIR.mkdir(parents=True, exist_ok=True)
        if ACTIVE_TIMELAPSES_PATH.is_file():
            try:
                raw = json.loads(ACTIVE_TIMELAPSES_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._active_by_printer = raw
            except Exception as exc:
                logger.warning("No se pudo cargar active_sessions.json de timelapses: %s", exc)
        if COMPLETED_TIMELAPSES_PATH.is_file():
            try:
                raw = json.loads(COMPLETED_TIMELAPSES_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    self._completed = raw
            except Exception as exc:
                logger.warning("No se pudo cargar completed_timelapses.json: %s", exc)
        if ARMED_PRINTERS_PATH.is_file():
            try:
                raw = json.loads(ARMED_PRINTERS_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    self._armed_printers = {str(x) for x in raw}
            except Exception as exc:
                logger.warning("No se pudo cargar armed_printers.json: %s", exc)

    def _save_active(self) -> None:
        _atomic_write_json(ACTIVE_TIMELAPSES_PATH, self._active_by_printer)

    def _save_completed(self) -> None:
        _atomic_write_json(COMPLETED_TIMELAPSES_PATH, self._completed)

    def _save_armed(self) -> None:
        _atomic_write_json(ARMED_PRINTERS_PATH, sorted(self._armed_printers))

    def arm_printer(self, printer_id: str, armed: bool = True) -> list[str]:
        self.load_persisted_state()
        if armed:
            self._armed_printers.add(printer_id)
        else:
            self._armed_printers.discard(printer_id)
        self._save_armed()
        return sorted(self._armed_printers)

    def is_printer_armed(self, printer_id: str) -> bool:
        self.load_persisted_state()
        return printer_id in self._armed_printers

    def get_armed_printers(self) -> list[str]:
        self.load_persisted_state()
        return sorted(self._armed_printers)

    def _start_session(self, status: PrinterLiveStatus, camera_url: str, now_ts: float) -> dict[str, Any]:
        pid = status.printer_id
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        slug = _slugify(status.current_file)
        sid = f"tl_{pid}_{stamp}_{slug}"
        frames_dir = TIMELAPSE_DIR / sid / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        sess = {
            "session_id": sid,
            "printer_id": pid,
            "printer_name": status.display_name,
            "filename": status.current_file or "impresion_activa",
            "camera_url": camera_url,
            "started_at": now_ts,
            "started_iso": datetime.now(timezone.utc).isoformat(),
            "last_capture_ts": 0.0,
            "last_layer": -1,
            "frame_count": 0,
            "status": "recording",
        }
        self._active_by_printer[pid] = sess
        self._save_active()
        logger.info("Timelapse local iniciado: %s (%s)", sid, camera_url)
        return sess

    async def _capture_frame(self, printer_id: str, session_id: str, camera_url: str, layer_num: int | None) -> None:
        lock = self._capture_locks.setdefault(printer_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            sess = self._active_by_printer.get(printer_id)
            if not sess or sess.get("session_id") != session_id:
                return
            if int(sess.get("frame_count", 0)) >= MAX_FRAMES_PER_SESSION:
                return
            jpg = await grab_single_jpeg_from_camera(camera_url, timeout=4.0)
            if not jpg:
                return
            # Revalidar que la sesión siga activa tras I/O
            sess = self._active_by_printer.get(printer_id)
            if not sess or sess.get("session_id") != session_id:
                return
            idx = int(sess.get("frame_count", 0)) + 1
            frame_path = TIMELAPSE_DIR / session_id / "frames" / f"frame_{idx:05d}.jpg"
            frame_path.parent.mkdir(parents=True, exist_ok=True)
            frame_path.write_bytes(jpg)
            sess["frame_count"] = idx
            sess["last_capture_ts"] = time.time()
            if layer_num is not None:
                sess["last_layer"] = int(layer_num)
            self._save_active()

    async def _finalize_session(self, printer_id: str, final_status: str) -> None:
        sess = self._active_by_printer.get(printer_id)
        if not sess:
            return
        sid = str(sess.get("session_id", ""))
        if not sid or sid in self._finalizing_ids:
            return
        self._finalizing_ids.add(sid)
        try:
            self._active_by_printer.pop(printer_id, None)
            self._save_active()

            sess_dir = TIMELAPSE_DIR / sid
            frames_dir = sess_dir / "frames"
            frame_paths = sorted(frames_dir.glob("frame_*.jpg")) if frames_dir.is_dir() else []
            if not frame_paths:
                return

            thumb_path = sess_dir / "thumb.jpg"
            mid_frame = frame_paths[len(frame_paths) // 2]
            shutil.copy2(mid_frame, thumb_path)

            avi_path = sess_dir / "timelapse.avi"
            webp_path = sess_dir / "timelapse.webp"
            await asyncio.to_thread(write_mjpeg_avi, frame_paths, avi_path, 15)
            await asyncio.to_thread(build_animated_webp, frame_paths, webp_path, 15)

            mp4_path: Path | None = None
            ffmpeg_bin = shutil.which("ffmpeg")
            if ffmpeg_bin:
                candidate_mp4 = sess_dir / "timelapse.mp4"
                proc = await asyncio.create_subprocess_exec(
                    ffmpeg_bin,
                    "-y",
                    "-framerate",
                    "15",
                    "-i",
                    str(frames_dir / "frame_%05d.jpg"),
                    "-c:v",
                    "libx264",
                    "-pix_fmt",
                    "yuv420p",
                    str(candidate_mp4),
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                rc = await proc.wait()
                if rc == 0 and candidate_mp4.is_file():
                    mp4_path = candidate_mp4

            entry = {
                "session_id": sid,
                "printer_id": printer_id,
                "printer_name": sess.get("printer_name") or printer_id,
                "filename": sess.get("filename") or "impresion",
                "status": final_status,
                "started_iso": sess.get("started_iso"),
                "completed_iso": datetime.now(timezone.utc).isoformat(),
                "frame_count": len(frame_paths),
                "has_webp": webp_path.is_file(),
                "has_avi": avi_path.is_file(),
                "has_mp4": bool(mp4_path and mp4_path.is_file()),
                "has_thumb": thumb_path.is_file(),
                "size_bytes": avi_path.stat().st_size if avi_path.is_file() else 0,
            }
            self._completed.insert(0, entry)
            self._completed = self._completed[:100]
            self._save_completed()
            logger.info("Timelapse ensamblado (%s, %d frames): %s", final_status, len(frame_paths), sid)
        except Exception as exc:
            logger.warning("Error ensamblando timelapse %s: %s", sid, exc)
        finally:
            self._finalizing_ids.discard(sid)

    def ingest_status(self, status: PrinterLiveStatus, camera_url: str | None = None) -> None:
        """Procesa el estado de una impresora sin bloquear el bucle principal."""
        self.load_persisted_state()
        if not status.online:
            return

        pid = status.printer_id
        cam = (camera_url or status.camera_url or "").strip()
        state_lower = (status.state or "").strip().lower()
        is_active = state_lower in ACTIVE_STATES
        now_ts = time.time()
        existing = self._active_by_printer.get(pid)

        if is_active:
            if existing is None:
                if not self.is_printer_armed(pid) or not cam:
                    return
                existing = self._start_session(status, cam, now_ts)

            cur_file = (status.current_file or "").strip()
            prev_file = str(existing.get("filename") or "")
            if cur_file and prev_file and cur_file != prev_file and not prev_file.startswith("impresion_activa"):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._finalize_session(pid, "completed"))
                except RuntimeError:
                    pass
                if self.is_printer_armed(pid) and cam:
                    existing = self._start_session(status, cam, now_ts)
                else:
                    return

            if cur_file and prev_file.startswith("impresion_activa"):
                existing["filename"] = cur_file
                self._save_active()

            if state_lower == "paused":
                return

            eff_cam = cam or str(existing.get("camera_url") or "")
            if not eff_cam:
                return

            elapsed = now_ts - float(existing.get("last_capture_ts") or 0.0)
            if elapsed < MIN_CAPTURE_INTERVAL_SEC:
                return

            cur_layer = status.current_layer
            last_layer = int(existing.get("last_layer", -1))
            should_capture = False
            if cur_layer is not None and cur_layer > last_layer:
                should_capture = True
            elif cur_layer is None and elapsed >= FALLBACK_CAPTURE_INTERVAL_SEC:
                should_capture = True
            elif int(existing.get("frame_count", 0)) == 0:
                should_capture = True

            if should_capture:
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(
                        self._capture_frame(pid, str(existing["session_id"]), eff_cam, cur_layer)
                    )
                except RuntimeError:
                    pass
            return

        # Estado no activo
        if existing is not None:
            final_status = "cancelled" if state_lower == "cancelled" else "completed"
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._finalize_session(pid, final_status))
            except RuntimeError:
                pass

    def list_timelapses(self, printer_id: str | None = None) -> dict[str, Any]:
        self.load_persisted_state()
        active = [
            v
            for v in self._active_by_printer.values()
            if not printer_id or v.get("printer_id") == printer_id
        ]
        completed = [
            v
            for v in self._completed
            if not printer_id or v.get("printer_id") == printer_id
        ]
        return {
            "armed_printers": sorted(self._armed_printers),
            "active": active,
            "completed": completed,
        }

    def get_media_path(self, session_id: str, fmt: str = "webp") -> Path | None:
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "", session_id)
        if not safe_id:
            return None
        sess_dir = TIMELAPSE_DIR / safe_id
        if not sess_dir.is_dir():
            return None
        mapping = {
            "webp": sess_dir / "timelapse.webp",
            "avi": sess_dir / "timelapse.avi",
            "mp4": sess_dir / "timelapse.mp4",
            "thumb": sess_dir / "thumb.jpg",
        }
        p = mapping.get(fmt.lower())
        return p if (p is not None and p.is_file()) else None

    def delete_timelapse(self, session_id: str) -> bool:
        self.load_persisted_state()
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "", session_id)
        before = len(self._completed)
        self._completed = [x for x in self._completed if x.get("session_id") != safe_id]
        if len(self._completed) != before:
            self._save_completed()
        sess_dir = TIMELAPSE_DIR / safe_id
        if sess_dir.is_dir():
            shutil.rmtree(sess_dir, ignore_errors=True)
            return True
        return len(self._completed) != before


local_timelapse_recorder = LocalTimelapseRecorder()
