"""Conector asíncrono Moonraker/Klipper para FLSUN V400, T1 Pro y Super Racer."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.config import update_printer_active_ip
from app.models.schemas import (
    PrinterId,
    PrinterLiveStatus,
    PrinterStoredFile,
    PrinterTimelapseFile,
)


def _candidate_ips(cfg: dict[str, Any]) -> list[str]:
    ips: list[str] = []
    primary = str(cfg.get("ip", "")).strip()
    if primary:
        ips.append(primary)
    for raw in cfg.get("fallback_ips") or []:
        s = str(raw).strip()
        if s and s not in ips:
            ips.append(s)
    return ips


def _candidate_ports(cfg: dict[str, Any]) -> list[int]:
    ports: list[int] = []
    raw_port = int(cfg.get("port", 80) or 80)
    for p in (raw_port, 80, 7125, 4408):
        if p not in ports:
            ports.append(p)
    return ports


def _base_url(ip: str, port: int) -> str:
    return f"http://{ip}" if port == 80 else f"http://{ip}:{port}"


def _opt_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        return round(float(val), 1)
    except (TypeError, ValueError):
        return None


def _opt_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _extract_light_state(status: dict[str, Any]) -> bool:
    for key in ("box_light", "output_pin LED_pin", "output_pin caselight"):
        obj = status.get(key)
        if isinstance(obj, dict) and "value" in obj and obj["value"] is not None:
            try:
                return float(obj["value"]) > 0.0
            except (TypeError, ValueError):
                continue
    return False


async def query_moonraker_status(
    printer_id: PrinterId,
    display_name: str,
    cfg: dict[str, Any],
    timeout: float = 2.2,
) -> PrinterLiveStatus:
    """Consulta asíncrona a Moonraker (puerto 80 con fallback 7125/4408 y `fallback_ips`)."""
    primary_ip = str(cfg.get("ip", "")).strip()
    primary_port = int(cfg.get("port", 80) or 80)
    profile_id = cfg.get("profile_id")
    enabled = bool(cfg.get("enabled", True))
    configured_cam = str(cfg.get("camera_url", "")).strip()
    ips = _candidate_ips(cfg)

    if not ips:
        return PrinterLiveStatus(
            printer_id=printer_id,
            profile_id=profile_id,
            display_name=display_name,
            protocol="moonraker",
            ip=primary_ip,
            port=primary_port,
            enabled=enabled,
            online=False,
            state="unconfigured",
            camera_url=configured_cam,
            message="IP de Moonraker sin configurar.",
        )

    ports = _candidate_ports(cfg)
    last_err = "Sin respuesta"
    req_timeout = max(timeout, 2.2)

    async with httpx.AsyncClient(timeout=req_timeout, trust_env=False) as client:
        for cand_ip in ips:
            for cand_port in ports:
                base = _base_url(cand_ip, cand_port)
                url = (
                    f"{base}/printer/objects/query"
                    "?heater_bed&extruder&print_stats&virtual_sdcard"
                    "&gcode_move&fan&display_status&webhooks&box_light"
                    "&output_pin%20LED_pin&output_pin%20caselight"
                    "&temperature_sensor%20mcu_temp&temperature_sensor%20Armv7%20mcu"
                )
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    payload = resp.json()

                    status = payload.get("result", {}).get("status", {})
                    extruder = status.get("extruder", {})
                    heater_bed = status.get("heater_bed", {})
                    print_stats = status.get("print_stats", {})
                    virtual_sd = status.get("virtual_sdcard", {})
                    gcode_move = status.get("gcode_move", {})
                    fan = status.get("fan", {})

                    raw_state = str(print_stats.get("state", "standby")).lower()
                    webhooks = status.get("webhooks") or {}
                    webhooks_state = str(webhooks.get("state", "")).lower()
                    webhooks_msg = str(webhooks.get("state_message") or "").strip()
                    print_msg = str(print_stats.get("message") or "").strip()
                    display_msg = str((status.get("display_status") or {}).get("message") or "").strip()

                    eff_state = raw_state
                    err_code: str | None = None
                    err_msg: str | None = None
                    if raw_state == "error" or webhooks_state in ("error", "shutdown"):
                        eff_state = "error"
                        err_code = "KLIPPER_SHUTDOWN" if webhooks_state == "shutdown" else "KLIPPER_ERROR"
                        err_msg = print_msg or webhooks_msg or "Klipper reportó un error o parada."
                    elif raw_state == "paused":
                        pause_detail = print_msg or (
                            display_msg
                            if any(
                                k in display_msg.lower()
                                for k in ("error", "filament", "runout", "jam", "clog", "pause", "atasco")
                            )
                            else ""
                        )
                        if pause_detail:
                            err_code = "PAUSE_REASON"
                            err_msg = pause_detail
                    progress = float(virtual_sd.get("progress", 0.0) or 0.0) * 100.0
                    total_dur = float(print_stats.get("total_duration", 0.0) or 0.0)
                    print_dur = float(print_stats.get("print_duration", 0.0) or 0.0)
                    eta_sec: int | None = None
                    if raw_state == "printing" and progress > 1.0 and print_dur > 5.0:
                        est_total = print_dur / (progress / 100.0)
                        eta_sec = max(0, int(est_total - print_dur))
                    elif total_dur > 0 and raw_state == "complete":
                        eta_sec = 0

                    info = print_stats.get("info") or {}
                    current_layer = _opt_int(info.get("current_layer"))
                    total_layers = _opt_int(info.get("total_layer"))

                    raw_speed = float(gcode_move.get("speed", 0.0) or 0.0)
                    speed_factor = float(gcode_move.get("speed_factor", 1.0) or 1.0)
                    extrude_factor = float(gcode_move.get("extrude_factor", 1.0) or 1.0)
                    print_speed_mms = (
                        round(raw_speed / 60.0, 1)
                        if raw_state in ("printing", "paused")
                        else 0.0
                    )
                    speed_factor_percent = round(speed_factor * 100.0, 1)
                    flow_factor_percent = round(extrude_factor * 100.0, 1)
                    fan_speed_percent = round(float(fan.get("speed", 0.0) or 0.0) * 100.0, 1)

                    filament_used_mm = round(
                        float(print_stats.get("filament_used", 0.0) or 0.0), 1
                    )
                    filament_used_g = round((filament_used_mm / 1000.0) * 2.98, 2)
                    mcu_temp = _opt_float(
                        (status.get("temperature_sensor mcu_temp") or {}).get("temperature")
                    )
                    host_temp = _opt_float(
                        (status.get("temperature_sensor Armv7 mcu") or {}).get("temperature")
                    )
                    light_on = _extract_light_state(status)

                    # Resolver URL real de cámara MJPEG desde `/server/webcams/list`
                    resolved_cam = configured_cam or f"http://{cand_ip}/webcam/?action=stream"
                    try:
                        cam_resp = await client.get(f"{base}/server/webcams/list", timeout=1.2)
                        if cam_resp.status_code == 200:
                            cams = cam_resp.json().get("result", {}).get("webcams", [])
                            if cams and isinstance(cams[0], dict):
                                raw_stream = str(cams[0].get("stream_url") or "").strip()
                                if raw_stream.startswith("http"):
                                    resolved_cam = raw_stream
                                elif raw_stream.startswith("/"):
                                    resolved_cam = f"http://{cand_ip}{raw_stream}"
                    except (httpx.HTTPError, ValueError):
                        pass

                    if cand_ip != primary_ip or cand_port != primary_port:
                        update_printer_active_ip(
                            printer_id,
                            cand_ip,
                            active_port=cand_port,
                            active_camera_url=resolved_cam,
                        )

                    return PrinterLiveStatus(
                        printer_id=printer_id,
                        profile_id=profile_id,
                        display_name=display_name,
                        protocol="moonraker",
                        ip=cand_ip,
                        port=cand_port,
                        enabled=enabled,
                        online=True,
                        state=eff_state,
                        nozzle_temp=round(float(extruder.get("temperature", 0.0)), 1),
                        nozzle_target=round(float(extruder.get("target", 0.0)), 1),
                        bed_temp=round(float(heater_bed.get("temperature", 0.0)), 1),
                        bed_target=round(float(heater_bed.get("target", 0.0)), 1),
                        progress_percent=round(min(100.0, max(0.0, progress)), 1),
                        current_file=print_stats.get("filename") or None,
                        eta_seconds=eta_sec,
                        camera_url=resolved_cam,
                        message=f"Conectado vía Moonraker ({cand_ip}:{cand_port})",
                        light_on=light_on,
                        current_layer=current_layer,
                        total_layers=total_layers,
                        print_speed_mms=print_speed_mms,
                        speed_factor_percent=speed_factor_percent,
                        flow_factor_percent=flow_factor_percent,
                        fan_speed_percent=fan_speed_percent,
                        elapsed_seconds=int(print_dur),
                        mcu_temp=mcu_temp,
                        host_temp=host_temp,
                        filament_used_mm=filament_used_mm,
                        filament_used_g=filament_used_g,
                        error_code=err_code,
                        error_message=err_msg,
                    )
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    last_err = type(exc).__name__

    return PrinterLiveStatus(
        printer_id=printer_id,
        profile_id=profile_id,
        display_name=display_name,
        protocol="moonraker",
        ip=primary_ip,
        port=primary_port,
        enabled=enabled,
        online=False,
        state="offline",
        camera_url=configured_cam or f"http://{primary_ip}/webcam/?action=stream",
        message=f"Sin respuesta Moonraker en {primary_ip}:{ports} ({last_err})",
    )


async def _resolve_live_base_url(cfg: dict[str, Any]) -> tuple[str, str]:
    ips = _candidate_ips(cfg)
    if not ips:
        raise RuntimeError("Falta configurar la IP de la impresora Moonraker.")
    ports = _candidate_ports(cfg)
    async with httpx.AsyncClient(timeout=2.5, trust_env=False) as client:
        for ip in ips:
            for port in ports:
                base = _base_url(ip, port)
                try:
                    r = await client.get(f"{base}/printer/info")
                    if r.status_code == 200:
                        return ip, base
                except httpx.HTTPError:
                    continue
    return ips[0], _base_url(ips[0], ports[0])


async def upload_and_start_moonraker(
    cfg: dict[str, Any],
    gcode_path: Path,
    filename: str,
    start_immediately: bool = True,
) -> str:
    """Sube `.gcode` a Moonraker (`root=gcodes`) y verifica persistencia real en memoria."""
    ip, base = await _resolve_live_base_url(cfg)
    url = f"{base}/server/files/upload"
    data = {
        "root": "gcodes",
        "print": "true" if start_immediately else "false",
    }
    async with httpx.AsyncClient(timeout=60.0, trust_env=False) as client:
        with gcode_path.open("rb") as fh:
            files = {"file": (filename, fh, "application/octet-stream")}
            resp = await client.post(url, data=data, files=files)
            resp.raise_for_status()
            body = resp.json()

        item = body.get("item", {})
        stored_name = str(item.get("path") or filename)

        persisted = False
        for _ in range(3):
            list_resp = await client.get(f"{base}/server/files/list", params={"root": "gcodes"})
            if list_resp.status_code == 200:
                entries = list_resp.json().get("result", [])
                if any(
                    str(e.get("path", "")) in (stored_name, filename)
                    for e in entries
                    if isinstance(e, dict)
                ):
                    persisted = True
                    break
            await asyncio.sleep(0.3)

    if not persisted:
        raise RuntimeError(
            f"Moonraker ({ip}) respondió 200 al subir '{filename}', pero no se encontró en /server/files/list?root=gcodes."
        )

    if start_immediately:
        return f"Moonraker ({ip}): '{stored_name}' subido, verificado en memoria e impresión iniciada."
    return f"Moonraker ({ip}): '{stored_name}' subido y verificado en memoria (sin iniciar impresión)."


async def list_moonraker_files(cfg: dict[str, Any]) -> list[PrinterStoredFile]:
    """Lista los archivos G-code almacenados en la memoria de Moonraker."""
    _ip, base = await _resolve_live_base_url(cfg)
    async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
        resp = await client.get(f"{base}/server/files/list", params={"root": "gcodes"})
        resp.raise_for_status()
        entries = resp.json().get("result", [])

    files: list[PrinterStoredFile] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        if not path:
            continue
        size_bytes = float(entry.get("size", 0) or 0)
        mod_ts = entry.get("modified")
        est_sec = entry.get("estimated_time")
        files.append(
            PrinterStoredFile(
                filename=path,
                size_mb=round(size_bytes / 1_048_576.0, 2),
                modified_ts=float(mod_ts) if mod_ts is not None else None,
                estimated_time_sec=int(est_sec) if est_sec is not None else None,
            )
        )
    files.sort(key=lambda item: item.modified_ts or 0.0, reverse=True)
    return files


async def get_moonraker_file_thumbnail(
    cfg: dict[str, Any],
    filename: str,
) -> bytes | None:
    """Obtiene la miniatura PNG de un G-code en Moonraker (T1 Pro / V400)."""
    clean_name = filename.strip()
    if not clean_name:
        return None
    _ip, base = await _resolve_live_base_url(cfg)
    async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
        try:
            meta_resp = await client.get(
                f"{base}/server/files/metadata",
                params={"filename": clean_name},
            )
            if meta_resp.status_code == 200:
                thumbs = (meta_resp.json().get("result") or {}).get("thumbnails") or []
                valid_thumbs = [t for t in thumbs if isinstance(t, dict) and t.get("relative_path")]
                if valid_thumbs:
                    best = max(
                        valid_thumbs,
                        key=lambda t: int(t.get("width") or 0) * int(t.get("height") or 0),
                    )
                    rel = str(best["relative_path"]).lstrip("/")
                    img_resp = await client.get(f"{base}/server/files/gcodes/{quote(rel, safe='/')}")
                    if img_resp.status_code == 200 and img_resp.content:
                        return img_resp.content
        except (httpx.HTTPError, ValueError):
            pass

        # Respaldo: leer bloque `; thumbnail begin` de la cabecera del G-code
        try:
            head_resp = await client.get(
                f"{base}/server/files/gcodes/{quote(clean_name, safe='/')}",
                headers={"Range": "bytes=0-131071"},
            )
            if head_resp.status_code in (200, 206):
                m = re.search(
                    r";\s*thumbnail\s+begin\s+\S+\s+\d+\s*\r?\n(.*?);\s*thumbnail\s+end",
                    head_resp.text,
                    re.S | re.I,
                )
                if m:
                    import base64

                    b64 = "".join(ln.lstrip("; ").strip() for ln in m.group(1).splitlines())
                    if b64:
                        return base64.b64decode(b64)
        except (httpx.HTTPError, ValueError):
            pass
    return None


async def print_moonraker_file(
    cfg: dict[str, Any],
    filename: str,
    enable_timelapse: bool = False,
) -> str:
    """Inicia la impresión de un archivo guardado en Moonraker (con soporte timelapse opcional)."""
    ip, base = await _resolve_live_base_url(cfg)
    tl_note = ""
    async with httpx.AsyncClient(timeout=25.0, trust_env=False) as client:
        if enable_timelapse:
            try:
                await client.post(
                    f"{base}/machine/timelapse/settings",
                    json={"enabled": True},
                    timeout=3.0,
                )
            except httpx.HTTPError:
                pass
            try:
                help_resp = await client.get(f"{base}/printer/gcode/help", timeout=4.0)
                has_tl_macro = (
                    help_resp.status_code == 200
                    and "TIMELAPSE_TAKE_FRAME" in (help_resp.json().get("result") or {})
                )
                if has_tl_macro:
                    dl = await client.get(
                        f"{base}/server/files/gcodes/{quote(filename, safe='/')}",
                        timeout=20.0,
                    )
                    if dl.status_code == 200 and "TIMELAPSE_TAKE_FRAME" not in dl.text:
                        injected_lines: list[str] = ["; SLICERHUB_TIMELAPSE = 1"]
                        for ln in dl.text.splitlines():
                            injected_lines.append(ln)
                            if ln.strip().startswith(";LAYER_CHANGE"):
                                injected_lines.append("TIMELAPSE_TAKE_FRAME")
                        patched_bytes = ("\n".join(injected_lines) + "\n").encode("utf-8")
                        up = await client.post(
                            f"{base}/server/files/upload",
                            data={"root": "gcodes", "print": "false"},
                            files={"file": (filename, patched_bytes, "application/octet-stream")},
                            timeout=30.0,
                        )
                        if up.status_code < 400:
                            tl_note = " (TIMELAPSE_TAKE_FRAME activado)"
            except httpx.HTTPError:
                pass

        resp = await client.post(
            f"{base}/printer/print/start",
            params={"filename": filename},
        )
        resp.raise_for_status()
    return f"Moonraker ({ip}): impresión iniciada para '{filename}'{tl_note}."


async def delete_moonraker_file(cfg: dict[str, Any], filename: str) -> str:
    """Elimina un archivo guardado de la memoria `gcodes` en Moonraker."""
    ip, base = await _resolve_live_base_url(cfg)
    encoded = quote(filename, safe="")
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        resp = await client.delete(f"{base}/server/files/gcodes/{encoded}")
        if resp.status_code == 404 and "/" in filename:
            resp = await client.delete(
                f"{base}/server/files/gcodes/{quote(filename, safe='/')}"
            )
        resp.raise_for_status()
    return f"Moonraker ({ip}): archivo '{filename}' eliminado de la memoria."


async def download_moonraker_file(cfg: dict[str, Any], filename: str) -> tuple[bytes, str]:
    """Descarga el contenido binario de un archivo en `gcodes` desde Moonraker."""
    _ip, base = await _resolve_live_base_url(cfg)
    encoded = quote(filename, safe="")
    async with httpx.AsyncClient(timeout=45.0, trust_env=False) as client:
        resp = await client.get(f"{base}/server/files/gcodes/{encoded}")
        if resp.status_code == 404 and "/" in filename:
            resp = await client.get(
                f"{base}/server/files/gcodes/{quote(filename, safe='/')}"
            )
        resp.raise_for_status()
        return resp.content, Path(filename).name


async def set_moonraker_light(
    cfg: dict[str, Any],
    target_on: bool | None = None,
) -> tuple[bool, str]:
    """Consulta y conmuta la luz LED/cabina en Klipper (T1 Pro `box_light`, V400 `LED_pin`)."""
    ip, base = await _resolve_live_base_url(cfg)
    async with httpx.AsyncClient(timeout=6.0, trust_env=False) as client:
        obj_resp = await client.get(f"{base}/printer/objects/list")
        obj_resp.raise_for_status()
        objects = set(obj_resp.json().get("result", {}).get("objects", []))

        q_resp = await client.get(
            f"{base}/printer/objects/query"
            "?box_light&output_pin%20LED_pin&output_pin%20caselight"
        )
        q_resp.raise_for_status()
        status = q_resp.json().get("result", {}).get("status", {})
        cur_on = _extract_light_state(status)
        desired = (not cur_on) if target_on is None else bool(target_on)

        async def _run_script(script: str) -> None:
            r = await client.post(
                f"{base}/printer/gcode/script",
                params={"script": script},
            )
            r.raise_for_status()

        if "box_light" in objects:
            await _run_script("F106 S1" if desired else "F106 S0")
            await asyncio.sleep(0.25)
            chk = await client.get(f"{base}/printer/objects/query?box_light")
            if chk.status_code == 200:
                new_status = chk.json().get("result", {}).get("status", {})
                if _extract_light_state(new_status) != desired:
                    await _run_script("F106")
        elif "output_pin LED_pin" in objects or "gcode_macro led_on" in objects:
            if "gcode_macro led_on" in objects and "gcode_macro led_off" in objects:
                await _run_script("LED_ON" if desired else "LED_OFF")
            if "output_pin LED_pin" in objects:
                await _run_script(f"SET_PIN PIN=LED_pin VALUE={1 if desired else 0}")
        elif "output_pin caselight" in objects:
            await _run_script(f"SET_PIN PIN=caselight VALUE={1 if desired else 0}")
        else:
            raise RuntimeError(
                f"Moonraker ({ip}): no se detectó pin o macro de iluminación LED en Klipper."
            )

        await asyncio.sleep(0.2)
        final_q = await client.get(
            f"{base}/printer/objects/query"
            "?box_light&output_pin%20LED_pin&output_pin%20caselight"
        )
        actual_on = (
            _extract_light_state(final_q.json().get("result", {}).get("status", {}))
            if final_q.status_code == 200
            else desired
        )

    state_txt = "ENCENDIDA" if actual_on else "APAGADA"
    return actual_on, f"Luz LED en Moonraker ({ip}): {state_txt}."


async def list_moonraker_timelapses(
    cfg: dict[str, Any],
) -> tuple[list[PrinterTimelapseFile], str]:
    """Lista videos `.mp4` en el directorio `timelapse` de Moonraker."""
    ip, base = await _resolve_live_base_url(cfg)
    async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
        resp = await client.get(f"{base}/server/files/list", params={"root": "timelapse"})
        if resp.status_code in (400, 404):
            return (
                [],
                f"Moonraker ({ip}): carpeta timelapse no habilitada o sin videos .mp4 aún.",
            )
        resp.raise_for_status()
        entries = resp.json().get("result", [])

    videos: list[PrinterTimelapseFile] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        path = str(entry.get("path") or "").strip()
        if not path.lower().endswith(".mp4"):
            continue
        size_bytes = float(entry.get("size", 0) or 0)
        mod_ts = entry.get("modified")
        videos.append(
            PrinterTimelapseFile(
                filename=path,
                size_mb=round(size_bytes / 1_048_576.0, 2),
                modified_ts=float(mod_ts) if mod_ts is not None else None,
                download_url=f"{base}/server/files/timelapse/{quote(path, safe='/')}",
            )
        )
    videos.sort(key=lambda item: item.modified_ts or 0.0, reverse=True)
    msg = (
        f"{len(videos)} video(s) timelapse encontrados en {ip}."
        if videos
        else f"Sin videos .mp4 en {ip} todavía."
    )
    return videos, msg


async def control_moonraker(cfg: dict[str, Any], action: str) -> str:
    """Ejecuta `pause`, `resume`, `cancel` o control LED en Moonraker."""
    if action in ("light_on", "light_off", "light_toggle"):
        target = True if action == "light_on" else False if action == "light_off" else None
        _on, msg = await set_moonraker_light(cfg, target_on=target)
        return msg

    endpoint_map = {
        "pause": "/printer/print/pause",
        "resume": "/printer/print/resume",
        "cancel": "/printer/print/cancel",
    }
    if action not in endpoint_map:
        raise ValueError(f"Acción no soportada: {action}")

    ip, base = await _resolve_live_base_url(cfg)
    profile_id = str(cfg.get("profile_id") or "")
    url = f"{base}{endpoint_map[action]}"
    async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
        if action == "cancel":
            # En FLSUN Klipper (T1 Pro / V400), END_PRINT detiene de inmediato impresión o sondeo en curso
            if profile_id in ("flsun_t1_pro", "flsun_v400", "flsun_sr"):
                try:
                    await client.post(
                        f"{base}/printer/gcode/script",
                        params={"script": "END_PRINT"},
                    )
                except httpx.HTTPError:
                    pass

            resp = await client.post(url)
            need_macro_fallback = resp.status_code >= 400
            st = "standby"
            if not need_macro_fallback:
                await asyncio.sleep(0.3)
                chk = await client.get(f"{base}/printer/objects/query?print_stats")
                if chk.status_code == 200:
                    st = str(
                        chk.json()
                        .get("result", {})
                        .get("status", {})
                        .get("print_stats", {})
                        .get("state", "standby")
                    ).lower()
                    if st in ("printing", "paused"):
                        need_macro_fallback = True
            if need_macro_fallback:
                script_resp = await client.post(
                    f"{base}/printer/gcode/script",
                    params={"script": "CANCEL_PRINT"},
                )
                script_resp.raise_for_status()
                await asyncio.sleep(0.3)
                chk2 = await client.get(f"{base}/printer/objects/query?print_stats")
                if chk2.status_code == 200:
                    st = str(
                        chk2.json()
                        .get("result", {})
                        .get("status", {})
                        .get("print_stats", {})
                        .get("state", "standby")
                    ).lower()
            return f"Impresión cancelada en Moonraker ({ip}) vía END_PRINT + CANCEL. Estado: {st}."
        else:
            resp = await client.post(url)
            resp.raise_for_status()
    return f"Comando '{action}' enviado a Moonraker ({ip})."
