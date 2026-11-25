"""Conector LAN (HTTP :8898 + Socket TCP :8899) para FlashForge Creator 5 Pro."""

from __future__ import annotations

import asyncio
import base64
import json
import re
import socket
from pathlib import Path
from typing import Any

import httpx

from app.config import TEMP_DIR, update_printer_active_ip
from app.models.schemas import PrinterId, PrinterLiveStatus, PrinterStoredFile

TEMP_M105_RE = re.compile(
    r"T0?:([0-9.]+)\s*/\s*([0-9.]+).*?B:([0-9.]+)\s*/\s*([0-9.]+)",
    re.IGNORECASE,
)
PROGRESS_M27_RE = re.compile(r"SD printing byte\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
FF_DELETED_CACHE_PATH = TEMP_DIR / "ff_deleted_files.json"


def _load_deleted_files_map() -> dict[str, list[str]]:
    if not FF_DELETED_CACHE_PATH.exists():
        return {}
    try:
        raw = json.loads(FF_DELETED_CACHE_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _save_deleted_files_map(data: dict[str, list[str]]) -> None:
    FF_DELETED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FF_DELETED_CACHE_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _mark_deleted_file(key: str, filename: str) -> None:
    data = _load_deleted_files_map()
    items = set(data.get(key, []))
    items.add(filename)
    data[key] = sorted(items)
    _save_deleted_files_map(data)


def _unmark_deleted_file(key: str, filename: str) -> None:
    data = _load_deleted_files_map()
    items = [x for x in data.get(key, []) if x != filename]
    if items:
        data[key] = items
    else:
        data.pop(key, None)
    _save_deleted_files_map(data)


def _tcp_command_sync(ip: str, port: int, command: str, timeout: float = 1.5) -> str:
    """Envía un comando `~M...` por socket TCP al puerto FlashForge (8899)."""
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(f"{command}\r\n".encode("ascii"))
        chunks: list[bytes] = []
        while True:
            try:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
                decoded = b"".join(chunks).decode("utf-8", errors="ignore")
                if "ok" in decoded.lower():
                    break
            except socket.timeout:
                break
        return b"".join(chunks).decode("utf-8", errors="ignore")


def _query_tcp_sync(ip: str, port: int, timeout: float = 1.5) -> dict[str, Any]:
    """Consulta M119 (estado), M105 (temperaturas) y M27 (progreso) por socket TCP."""
    with socket.create_connection((ip, port), timeout=timeout) as sock:
        sock.settimeout(timeout)

        def send_cmd(cmd: str) -> str:
            sock.sendall(f"{cmd}\r\n".encode("ascii"))
            buf = b""
            for _ in range(4):
                chunk = sock.recv(2048)
                if not chunk:
                    break
                buf += chunk
                if b"ok" in buf.lower():
                    break
            return buf.decode("utf-8", errors="ignore")

        send_cmd("~M601 S1")
        m119 = send_cmd("~M119")
        m105 = send_cmd("~M105")
        m27 = send_cmd("~M27")

    noz = noz_tgt = bed = bed_tgt = None
    m_t = TEMP_M105_RE.search(m105)
    if m_t:
        noz, noz_tgt, bed, bed_tgt = (float(x) for x in m_t.groups())

    progress = 0.0
    m_p = PROGRESS_M27_RE.search(m27)
    if m_p and int(m_p.group(2)) > 0:
        progress = round((int(m_p.group(1)) / int(m_p.group(2))) * 100.0, 1)

    upper = m119.upper()
    if "BUILDING_FROM_SD" in upper or "PRINTING" in upper:
        state = "printing"
    elif "PAUSED" in upper:
        state = "paused"
    else:
        state = "standby"

    cur_file = None
    m_f = re.search(r"CurrentFile:\s*([^\r\n]+)", m119)
    if m_f:
        cur_file = m_f.group(1).strip() or None

    return {
        "state": state,
        "nozzle_temp": noz,
        "nozzle_target": noz_tgt,
        "bed_temp": bed,
        "bed_target": bed_tgt,
        "progress_percent": progress,
        "current_file": cur_file,
    }


def _discover_flashforge_sn_sync(ip: str, timeout: float = 0.8) -> str | None:
    """Descubre automáticamente el Serial Number (`SN...`) por UDP (48899 / 19000)."""
    for udp_port in (48899, 19000):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(timeout)
                sock.sendto(b"discover", (ip, udp_port))
                data, _ = sock.recvfrom(4096)
            m = re.search(rb"(SN[A-Z0-9]{6,24})", data)
            if m:
                return m.group(1).decode("ascii", errors="ignore")
        except OSError:
            continue
    return None


def _candidate_flashforge_ips(cfg: dict[str, Any]) -> list[str]:
    ips: list[str] = []
    primary = str(cfg.get("ip", "")).strip()
    if primary:
        ips.append(primary)
    for raw in cfg.get("fallback_ips") or []:
        s = str(raw).strip()
        if s and s not in ips:
            ips.append(s)
    return ips


_FLASHFORGE_ERROR_CATALOG: dict[str, str] = {
    "E0163": "Atasco o resistencia de filamento detectada (Clog detected). Revisa boquilla, tubo PTFE o carrete.",
    "E0162": "Fallo de alimentación de filamento o sensor de extrusor. Revisa el carrete y el tubo guía.",
    "E0161": "Fin de filamento detectado (Filament runout).",
    "E0164": "Error en el cargador/estación de filamento (IFS/dock). Verifica el slot activo.",
    "E0011": "Error térmico de boquilla (Heating failed). Verifica termistor y cartucho calentador.",
    "E0017": "Desviación térmica detectada (Thermal runaway).",
}


def _parse_flashforge_error(detail: dict[str, Any]) -> tuple[str | None, str | None]:
    """Extrae `errorCode` del `/detail` de FlashForge y lo traduce a mensaje legible."""
    raw_err = str(detail.get("errorCode") or "").strip()
    if not raw_err or raw_err.lower() in ("0", "ok", "none", "null", "success"):
        return None, None
    err_upper = raw_err.upper()
    base_msg = _FLASHFORGE_ERROR_CATALOG.get(
        err_upper,
        f"Alerta reportada por la impresora ({err_upper}). Revisa la pantalla de la máquina.",
    )
    matl = detail.get("matlStationInfo")
    if isinstance(matl, dict):
        cur_slot = matl.get("currentSlot")
        slots = matl.get("slotInfos")
        slot_desc = ""
        if cur_slot and isinstance(slots, list):
            for s in slots:
                if isinstance(s, dict) and s.get("slotId") == cur_slot:
                    mat_name = str(s.get("materialName") or "").strip()
                    mat_col = str(s.get("materialColor") or "").strip()
                    slot_desc = f" — Slot #{cur_slot}" + (
                        f" ({mat_name} {mat_col})".rstrip() if mat_name or mat_col else ""
                    )
                    break
        elif cur_slot:
            slot_desc = f" — Slot #{cur_slot}"
        if slot_desc:
            base_msg = f"{base_msg}{slot_desc}"
    return err_upper, base_msg


async def _resolve_flashforge_target(
    cfg: dict[str, Any],
    client: httpx.AsyncClient,
) -> tuple[str, str, str, dict[str, Any]]:
    """Resuelve IP activa, serialNumber válido, checkCode y dict `/detail`."""
    ips = _candidate_flashforge_ips(cfg)
    if not ips:
        raise RuntimeError("Falta configurar la IP de FlashForge Creator 5 Pro.")
    access_code = str(cfg.get("access_code", "")).strip()
    serial_number = str(cfg.get("serial_number", "")).strip()

    for cand_ip in ips:
        eff_sn = serial_number
        if not eff_sn:
            eff_sn = await asyncio.to_thread(_discover_flashforge_sn_sync, cand_ip) or ""
        for attempt in range(2):
            try:
                resp = await client.post(
                    f"http://{cand_ip}:8898/detail",
                    json={"serialNumber": eff_sn, "checkCode": access_code},
                )
                if resp.status_code == 200:
                    body = resp.json()
                    msg_txt = str(body.get("message") or "")
                    if "sn is different" in msg_txt.lower():
                        discovered = await asyncio.to_thread(_discover_flashforge_sn_sync, cand_ip)
                        if discovered and discovered != eff_sn:
                            eff_sn = discovered
                            resp = await client.post(
                                f"http://{cand_ip}:8898/detail",
                                json={"serialNumber": eff_sn, "checkCode": access_code},
                            )
                            if resp.status_code == 200:
                                body = resp.json()
                    detail = body.get("detail")
                    if isinstance(detail, dict) and detail:
                        return cand_ip, eff_sn, access_code, detail
                    if attempt == 1:
                        return cand_ip, eff_sn, access_code, detail if isinstance(detail, dict) else {}
            except (httpx.HTTPError, ValueError):
                pass
            if attempt == 0:
                await asyncio.sleep(0.15)

    return ips[0], serial_number, access_code, {}


async def query_flashforge_status(
    printer_id: PrinterId,
    display_name: str,
    cfg: dict[str, Any],
    timeout: float = 2.0,
) -> PrinterLiveStatus:
    """Consulta telemetría completa vía HTTP LAN (:8898) y respaldo TCP (:8899)."""
    primary_ip = str(cfg.get("ip", "")).strip()
    port = int(cfg.get("port", 8899) or 8899)
    profile_id = cfg.get("profile_id")
    enabled = bool(cfg.get("enabled", True))
    access_code = str(cfg.get("access_code", "")).strip()
    serial_number = str(cfg.get("serial_number", "")).strip()
    configured_cam = str(cfg.get("camera_url", "")).strip()
    ips = _candidate_flashforge_ips(cfg)

    if not ips:
        return PrinterLiveStatus(
            printer_id=printer_id,
            profile_id=profile_id,
            display_name=display_name,
            protocol="flashforge_lan",
            ip=primary_ip,
            port=port,
            enabled=enabled,
            online=False,
            state="unconfigured",
            camera_url=configured_cam,
            message="IP / Access Code sin configurar.",
        )

    req_timeout = max(timeout, 2.0)
    last_err = "Timeout"

    async with httpx.AsyncClient(timeout=req_timeout, trust_env=False) as client:
        for cand_ip in ips:
            cand_cam = (
                configured_cam
                if (configured_cam and cand_ip == primary_ip)
                else f"http://{cand_ip}:8080/?action=stream"
            )
            # 1. API HTTP LAN moderna FlashForge (puerto 8898)
            try:
                eff_sn = serial_number
                if not eff_sn:
                    eff_sn = await asyncio.to_thread(_discover_flashforge_sn_sync, cand_ip) or ""
                resp = await client.post(
                    f"http://{cand_ip}:8898/detail",
                    json={"serialNumber": eff_sn, "checkCode": access_code},
                )
                if resp.status_code == 200:
                    body = resp.json()
                    msg_txt = str(body.get("message") or "")
                    if "sn is different" in msg_txt.lower():
                        discovered_sn = await asyncio.to_thread(_discover_flashforge_sn_sync, cand_ip)
                        if discovered_sn and discovered_sn != eff_sn:
                            eff_sn = discovered_sn
                            resp = await client.post(
                                f"http://{cand_ip}:8898/detail",
                                json={"serialNumber": eff_sn, "checkCode": access_code},
                            )
                            if resp.status_code == 200:
                                body = resp.json()
                                msg_txt = str(body.get("message") or "")

                    detail = body.get("detail", {})
                    if isinstance(detail, dict) and detail:
                        raw_status = str(detail.get("status", "ready")).lower()
                        err_code, err_msg = _parse_flashforge_error(detail)
                        state = (
                            "printing"
                            if "print" in raw_status or "build" in raw_status
                            else "paused"
                            if "pause" in raw_status
                            else "error"
                            if "error" in raw_status or "fail" in raw_status
                            else "standby"
                        )
                        cam_stream = str(detail.get("cameraStreamUrl") or cand_cam)
                        if cand_ip != primary_ip or (eff_sn and eff_sn != serial_number):
                            update_printer_active_ip(
                                printer_id,
                                cand_ip,
                                active_camera_url=cam_stream,
                                serial_number=eff_sn or None,
                            )
                        noz_list = detail.get("nozzleTemps")
                        noz_tgt_list = detail.get("nozzleTargetTemps")
                        noz_val = (
                            noz_list[0]
                            if isinstance(noz_list, list) and len(noz_list) > 0
                            else detail.get("nozzleTemp")
                            if detail.get("nozzleTemp") is not None
                            else detail.get("rightTemp")
                            if detail.get("rightTemp") is not None
                            else detail.get("leftTemp")
                        )
                        noz_tgt = (
                            noz_tgt_list[0]
                            if isinstance(noz_tgt_list, list) and len(noz_tgt_list) > 0
                            else detail.get("nozzleTargetTemp")
                            if detail.get("nozzleTargetTemp") is not None
                            else detail.get("rightTargetTemp")
                            if detail.get("rightTargetTemp") is not None
                            else detail.get("leftTargetTemp")
                        )

                        light_on = str(detail.get("lightStatus", "")).strip().lower() == "open"
                        cur_layer = int(detail.get("printLayer", 0) or 0)
                        tgt_layer = int(detail.get("targetPrintLayer", 0) or 0)
                        cur_speed = round(float(detail.get("currentPrintSpeed", 0.0) or 0.0), 1)
                        spd_adj = float(detail.get("printSpeedAdjust", 100.0) or 100.0)
                        if spd_adj <= 0.0:
                            spd_adj = 100.0
                        fan_pct = round(float(detail.get("coolingFanSpeed", 0.0) or 0.0), 1)
                        elapsed_sec = int(detail.get("printDuration", 0) or 0)
                        est_total_sec = float(detail.get("estimatedTime", 0.0) or 0.0)
                        eta_sec = (
                            max(0, int(est_total_sec - elapsed_sec))
                            if (state in ("printing", "paused") and est_total_sec > 0)
                            else None
                        )
                        chamber_t = detail.get("chamberTemp")
                        right_w = float(detail.get("estimatedRightWeight", 0.0) or 0.0)
                        left_w = float(detail.get("estimatedLeftWeight", 0.0) or 0.0)
                        fill_amt = float(detail.get("fillAmount", 0.0) or 0.0)
                        fil_g = round((right_w + left_w) if (right_w + left_w) > 0 else fill_amt, 2)
                        right_len = float(detail.get("estimatedRightLen", 0.0) or 0.0)
                        left_len = float(detail.get("estimatedLeftLen", 0.0) or 0.0)
                        fil_mm = round((right_len + left_len) * 1000.0, 1)

                        return PrinterLiveStatus(
                            printer_id=printer_id,
                            profile_id=profile_id,
                            display_name=display_name,
                            protocol="flashforge_lan",
                            ip=cand_ip,
                            port=8898,
                            enabled=enabled,
                            online=True,
                            state=state,
                            nozzle_temp=noz_val,
                            nozzle_target=noz_tgt,
                            bed_temp=detail.get("platTemp"),
                            bed_target=detail.get("platTargetTemp"),
                            progress_percent=float(detail.get("printProgress", 0.0) or 0.0) * 100.0,
                            current_file=detail.get("printFileName") or None,
                            eta_seconds=eta_sec,
                            camera_url=cam_stream,
                            message=(
                                "Trabajo cancelado en pantalla (toca OK en la impresora para liberar)"
                                if raw_status == "cancel"
                                else "Trabajo completado en pantalla (toca OK en la impresora para liberar)"
                                if raw_status in ("completed", "complete", "finished")
                                else f"Conectado vía FlashForge HTTP LAN ({cand_ip}:8898)"
                            ),
                            light_on=light_on,
                            current_layer=cur_layer if tgt_layer > 0 else None,
                            total_layers=tgt_layer if tgt_layer > 0 else None,
                            print_speed_mms=cur_speed,
                            speed_factor_percent=round(spd_adj, 1),
                            flow_factor_percent=100.0,
                            fan_speed_percent=fan_pct,
                            elapsed_seconds=elapsed_sec,
                            chamber_temp=round(float(chamber_t), 1) if chamber_t is not None else None,
                            filament_used_mm=fil_mm,
                            filament_used_g=fil_g,
                            error_code=err_code,
                            error_message=err_msg,
                        )
                    code = body.get("code")
                    if code == -2 or "lan mode" in msg_txt.lower():
                        if cand_ip != primary_ip or (eff_sn and eff_sn != serial_number):
                            update_printer_active_ip(
                                printer_id,
                                cand_ip,
                                active_camera_url=cand_cam,
                                serial_number=eff_sn or None,
                            )
                        return PrinterLiveStatus(
                            printer_id=printer_id,
                            profile_id=profile_id,
                            display_name=display_name,
                            protocol="flashforge_lan",
                            ip=cand_ip,
                            port=8898,
                            enabled=enabled,
                            online=True,
                            state="lan_mode_required",
                            camera_url=cand_cam,
                            message=(
                                f"Creator 5 Pro detectada en {cand_ip}:8898 "
                                "— Activa 'Modo LAN' en la impresora para telemetría"
                            ),
                        )
                    if "access code" in msg_txt.lower():
                        if cand_ip != primary_ip or (eff_sn and eff_sn != serial_number):
                            update_printer_active_ip(
                                printer_id,
                                cand_ip,
                                active_camera_url=cand_cam,
                                serial_number=eff_sn or None,
                            )
                        return PrinterLiveStatus(
                            printer_id=printer_id,
                            profile_id=profile_id,
                            display_name=display_name,
                            protocol="flashforge_lan",
                            ip=cand_ip,
                            port=8898,
                            enabled=enabled,
                            online=True,
                            state="access_code_mismatch",
                            camera_url=cand_cam,
                            message=(
                                f"Creator 5 Pro ({eff_sn or 'SN'}) en línea en {cand_ip}:8898 — "
                                f"Revisa Access Code '{access_code}' (respuesta: {msg_txt})"
                            ),
                        )
            except (httpx.HTTPError, ValueError) as exc:
                last_err = type(exc).__name__

            # 2. Respaldo socket TCP estándar FlashForge (~M119 / ~M105 / ~M27 en :8899)
            try:
                tcp_info = await asyncio.to_thread(_query_tcp_sync, cand_ip, port, req_timeout)
                if cand_ip != primary_ip:
                    update_printer_active_ip(
                        printer_id, cand_ip, active_camera_url=cand_cam
                    )
                return PrinterLiveStatus(
                    printer_id=printer_id,
                    profile_id=profile_id,
                    display_name=display_name,
                    protocol="flashforge_lan",
                    ip=cand_ip,
                    port=port,
                    enabled=enabled,
                    online=True,
                    state=tcp_info["state"],
                    nozzle_temp=tcp_info["nozzle_temp"],
                    nozzle_target=tcp_info["nozzle_target"],
                    bed_temp=tcp_info["bed_temp"],
                    bed_target=tcp_info["bed_target"],
                    progress_percent=tcp_info["progress_percent"],
                    current_file=tcp_info["current_file"],
                    camera_url=cand_cam,
                    message=f"Conectado vía FlashForge TCP ({cand_ip}:{port})",
                )
            except OSError as exc:
                last_err = type(exc).__name__

    return PrinterLiveStatus(
        printer_id=printer_id,
        profile_id=profile_id,
        display_name=display_name,
        protocol="flashforge_lan",
        ip=primary_ip,
        port=port,
        enabled=enabled,
        online=False,
        state="offline",
        camera_url=configured_cam or f"http://{primary_ip}:8080/?action=stream",
        message=f"Sin conexión LAN FlashForge en {', '.join(ips)} ({last_err})",
    )


def _tcp_upload_sync(
    ip: str,
    port: int,
    gcode_path: Path,
    filename: str,
    start_immediately: bool,
) -> str:
    """Protocolo binario TCP FlashForge (`~M28` / paquetes 4KB / `~M29` / `~M23`)."""
    raw = gcode_path.read_bytes()
    size = len(raw)
    remote_path = f"0:/user/{filename}"

    with socket.create_connection((ip, port), timeout=15.0) as sock:
        sock.settimeout(10.0)
        sock.sendall(b"~M601 S1\r\n")
        sock.recv(1024)
        sock.sendall(f"~M28 {size} {remote_path}\r\n".encode("ascii"))
        resp = sock.recv(1024).decode("utf-8", errors="ignore")
        if "ok" not in resp.lower():
            raise RuntimeError(f"FlashForge rechazó M28: {resp}")

        chunk_size = 4096
        for idx in range(0, size, chunk_size):
            sock.sendall(raw[idx : idx + chunk_size])

        sock.sendall(b"~M29\r\n")
        sock.recv(1024)
        if start_immediately:
            sock.sendall(f"~M23 {remote_path}\r\n".encode("ascii"))
            sock.recv(1024)
    return (
        f"FlashForge TCP ({ip}:{port}): '{filename}' subido ({size} B)"
        + (" e impresión iniciada." if start_immediately else " a memoria interna.")
    )


def _build_material_mappings_from_gcode(
    gcode_path: Path,
    detail: dict[str, Any],
) -> tuple[bool, int, list[dict[str, Any]]]:
    """Extrae herramientas T0..T3 del `.gcode` o `.gcode.3mf` y arma `materialMappings` para Creator 5 Pro."""
    try:
        if gcode_path.suffix.lower() == ".3mf":
            import zipfile

            with zipfile.ZipFile(gcode_path, "r") as zf:
                text = zf.read("Metadata/plate_1.gcode").decode("utf-8", errors="ignore")
        else:
            text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, KeyError, Exception):
        return False, 0, []

    used_tools = sorted({int(m) for m in re.findall(r"^T([0-3])\b", text, flags=re.M)})
    if not used_tools:
        used_tools = [0]

    colors = ["#FFFFFF", "#FFFFFF", "#FFFFFF", "#FFFFFF"]
    m_colors = re.search(r";\s*SLICERHUB_EXTRUDER_COLORS\s*=\s*(.+)", text)
    if m_colors:
        parts = [c.strip() for c in m_colors.group(1).split(",") if c.strip()]
        for idx, col in enumerate(parts[:4]):
            colors[idx] = col

    gcode_mats = ["PLA", "PLA", "PLA", "PLA"]
    m_types = re.search(r";\s*filament_type\s*=\s*(.+)", text)
    if m_types:
        tparts = [p.strip().strip('"') for p in m_types.group(1).split(";") if p.strip()]
        for idx, mt in enumerate(tparts[:4]):
            if mt:
                gcode_mats[idx] = mt

    matl_info = detail.get("matlStationInfo") if isinstance(detail, dict) else None
    slot_infos = (
        matl_info.get("slotInfos", [])
        if isinstance(matl_info, dict) and isinstance(matl_info.get("slotInfos"), list)
        else []
    )
    slots_by_id = {
        int(s.get("slotId", 0)): s
        for s in slot_infos
        if isinstance(s, dict) and s.get("slotId")
    }

    mappings: list[dict[str, Any]] = []
    for t_id in used_tools:
        slot_id = t_id + 1
        slot = slots_by_id.get(slot_id, {})
        mat_name = str(slot.get("materialName") or gcode_mats[t_id] or "PLA").strip() or "PLA"
        slot_color = str(slot.get("materialColor") or colors[t_id] or "#FFFFFF").strip()
        tool_color = colors[t_id] or slot_color
        mappings.append(
            {
                "toolId": t_id,
                "slotId": slot_id,
                "materialName": mat_name,
                "toolMaterialColor": tool_color,
                "slotMaterialColor": slot_color,
            }
        )

    # No apagar la estación IFS si el G-code tiene múltiples herramientas (aunque /detail no traiga slotInfos)
    use_station = len(used_tools) > 1 or used_tools[0] > 0
    if not use_station:
        return False, 0, []
    return True, len(mappings), mappings


async def upload_and_start_flashforge(
    cfg: dict[str, Any],
    gcode_path: Path,
    filename: str,
    start_immediately: bool = True,
    enable_timelapse: bool = False,
    auto_leveling: bool = False,
) -> str:
    """Sube G-code a la memoria de Creator 5 Pro vía `:8898/uploadGcode` (campo `gcodeFile`)."""
    port = int(cfg.get("port", 8899) or 8899)
    upload_timeout = httpx.Timeout(connect=10.0, read=180.0, write=180.0, pool=10.0)
    async with httpx.AsyncClient(timeout=upload_timeout, trust_env=False) as client:
        ip, eff_sn, access_code, detail = await _resolve_flashforge_target(cfg, client)
        use_station, tool_cnt, mappings = _build_material_mappings_from_gcode(
            gcode_path, detail if isinstance(detail, dict) else {}
        )
        mappings_b64 = base64.b64encode(
            json.dumps(mappings, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")
        headers = {
            "serialNumber": eff_sn,
            "checkCode": access_code,
            "fileSize": str(gcode_path.stat().st_size),
            "printNow": "true" if start_immediately else "false",
            "levelingBeforePrint": "true" if auto_leveling else "false",
            "flowCalibration": "true" if auto_leveling else "false",
            "firstLayerInspection": "false",
            "timeLapseVideo": "true" if enable_timelapse else "false",
            "useMatlStation": "true" if use_station else "false",
            "gcodeToolCnt": str(tool_cnt),
            "materialMappings": mappings_b64,
        }
        try:
            with gcode_path.open("rb") as fh:
                files = {"gcodeFile": (filename, fh, "application/octet-stream")}
                resp = await client.post(
                    f"http://{ip}:8898/uploadGcode",
                    headers=headers,
                    files=files,
                )
            if resp.status_code == 200:
                body = resp.json()
                if body.get("code") == 0:
                    _unmark_deleted_file(eff_sn or ip, filename)
                    list_resp = await client.post(
                        f"http://{ip}:8898/gcodeList",
                        json={"serialNumber": eff_sn, "checkCode": access_code},
                    )
                    in_list = (
                        filename in (list_resp.json().get("gcodeList") or [])
                        if list_resp.status_code == 200
                        else False
                    )
                    action_txt = (
                        "e impresión iniciada"
                        if start_immediately
                        else "a memoria sin iniciar impresión"
                    )
                    ver_txt = " [verificado en /gcodeList]" if in_list else ""
                    return f"FlashForge LAN ({ip}:8898): '{filename}' subido {action_txt}{ver_txt}."
                raise RuntimeError(
                    f"FlashForge LAN ({ip}:8898) rechazó la subida: {body.get('message', body)}"
                )
            raise RuntimeError(
                f"FlashForge LAN ({ip}:8898) devolvió HTTP {resp.status_code} al subir '{filename}'."
            )
        except httpx.ConnectError:
            pass
        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Error transfiriendo '{filename}' a FlashForge LAN ({ip}:8898): {exc}"
            ) from exc

    return await asyncio.to_thread(
        _tcp_upload_sync,
        ip,
        port,
        gcode_path,
        filename,
        start_immediately,
    )


async def list_flashforge_files(cfg: dict[str, Any]) -> list[PrinterStoredFile]:
    """Consulta la lista real de archivos internos en Creator 5 Pro (`:8898/gcodeList`)."""
    async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
        ip, eff_sn, access_code, _ = await _resolve_flashforge_target(cfg, client)
        try:
            resp = await client.post(
                f"http://{ip}:8898/gcodeList",
                json={"serialNumber": eff_sn, "checkCode": access_code},
            )
            resp.raise_for_status()
            body = resp.json()
            if body.get("code", -1) == 0:
                details_by_name: dict[str, dict[str, Any]] = {}
                for det in body.get("gcodeListDetail") or []:
                    if isinstance(det, dict) and det.get("gcodeFileName"):
                        details_by_name[str(det["gcodeFileName"])] = det

                names = [str(n) for n in (body.get("gcodeList") or []) if n]
                for d_name in details_by_name:
                    if d_name not in names:
                        names.append(d_name)

                out: list[PrinterStoredFile] = []
                for name in names:
                    det = details_by_name.get(name, {})
                    est_sec = det.get("printingTime")
                    weight_g = det.get("totalFilamentWeight")
                    out.append(
                        PrinterStoredFile(
                            filename=name,
                            size_mb=0.0,
                            estimated_time_sec=int(est_sec) if est_sec is not None else None,
                            filament_grams=(
                                round(float(weight_g), 2) if weight_g is not None else None
                            ),
                        )
                    )
                return out
        except (httpx.HTTPError, ValueError):
            pass

    # Respaldo TCP ~M661
    port = int(cfg.get("port", 8899) or 8899)
    try:
        raw = await asyncio.to_thread(_tcp_command_sync, ip, port, "~M661", 2.5)
        names = [
            ln.strip().removeprefix("/user/").removeprefix("0:/user/")
            for ln in raw.splitlines()
            if ln.strip().lower().endswith((".gcode", ".gx", ".3mf"))
        ]
        return [PrinterStoredFile(filename=n) for n in names]
    except OSError:
        return []


async def print_flashforge_file(
    cfg: dict[str, Any],
    filename: str,
    enable_timelapse: bool = False,
    auto_leveling: bool = False,
) -> str:
    """Inicia la impresión de un archivo guardado en Creator 5 Pro (`:8898/printGcode`)."""
    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        ip, eff_sn, access_code, detail = await _resolve_flashforge_target(cfg, client)
        raw_status = str(detail.get("status", "")).strip().lower() if isinstance(detail, dict) else ""

        use_matl_station = False
        gcode_tool_cnt = 0
        material_mappings: list[dict[str, Any]] = []
        try:
            list_resp = await client.post(
                f"http://{ip}:8898/gcodeList",
                json={"serialNumber": eff_sn, "checkCode": access_code},
            )
            if list_resp.status_code == 200:
                for det in list_resp.json().get("gcodeListDetail") or []:
                    if isinstance(det, dict) and det.get("gcodeFileName") == filename:
                        use_matl_station = bool(det.get("useMatlStation", False))
                        tool_datas = det.get("gcodeToolDatas") or []
                        gcode_tool_cnt = int(det.get("gcodeToolCnt") or len(tool_datas) or 0)
                        for td in tool_datas:
                            if isinstance(td, dict):
                                material_mappings.append(
                                    {
                                        "toolId": int(td.get("toolId", 0)),
                                        "slotId": int(td.get("slotId", 1)),
                                        "materialName": str(td.get("materialName") or "PLA"),
                                        "toolMaterialColor": str(td.get("materialColor") or "#FFFFFF"),
                                        "slotMaterialColor": str(td.get("materialColor") or "#FFFFFF"),
                                    }
                                )
                        break
        except (httpx.HTTPError, ValueError):
            pass

        payload = {
            "serialNumber": eff_sn,
            "checkCode": access_code,
            "fileName": filename,
            "levelingBeforePrint": bool(auto_leveling),
            "flowCalibration": bool(auto_leveling),
            "firstLayerInspection": False,
            "timeLapseVideo": bool(enable_timelapse),
            "useMatlStation": use_matl_station,
            "gcodeToolCnt": gcode_tool_cnt,
            "materialMappings": material_mappings,
        }
        try:
            resp = await client.post(f"http://{ip}:8898/printGcode", json=payload)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("code") == 0:
                    return f"FlashForge LAN ({ip}:8898): impresión iniciada para '{filename}'."
                err_msg = str(body.get("message", body))
                if "busy" in err_msg.lower() and raw_status in ("cancel", "completed", "complete", "finished"):
                    raise RuntimeError(
                        f"Creator 5 Pro sigue en pantalla de '{raw_status}' en su panel táctil. "
                        f"Toca 'OK / Confirmar' en la pantalla de la impresora para liberarla antes de iniciar '{filename}'."
                    )
                raise RuntimeError(
                    f"Creator 5 Pro rechazó iniciar '{filename}': {err_msg}"
                )
        except httpx.HTTPError:
            pass

    port = int(cfg.get("port", 8899) or 8899)
    resp_txt = await asyncio.to_thread(
        _tcp_command_sync, ip, port, f"~M23 0:/user/{filename}", 3.0
    )
    return f"FlashForge TCP ({ip}:{port}): '{filename}' iniciado ({resp_txt.strip()})."


async def delete_flashforge_file(cfg: dict[str, Any], filename: str) -> str:
    """Elimina un archivo en Creator 5 Pro vía `:8898/control` y verifica en `/gcodeList`."""
    async with httpx.AsyncClient(timeout=8.0, trust_env=False) as client:
        ip, eff_sn, access_code, _ = await _resolve_flashforge_target(cfg, client)
        for cmd_name in ("delFile_cmd", "deleteFile_cmd"):
            try:
                await client.post(
                    f"http://{ip}:8898/control",
                    json={
                        "serialNumber": eff_sn,
                        "checkCode": access_code,
                        "payload": {"cmd": cmd_name, "args": {"fileName": filename}},
                    },
                )
            except httpx.HTTPError:
                pass

        try:
            list_resp = await client.post(
                f"http://{ip}:8898/gcodeList",
                json={"serialNumber": eff_sn, "checkCode": access_code},
            )
            if list_resp.status_code == 200:
                current_files = list_resp.json().get("gcodeList") or []
                if filename not in current_files:
                    return f"FlashForge ({ip}:8898): archivo '{filename}' eliminado de la memoria."
                raise RuntimeError(
                    f"El firmware de Creator 5 Pro no permite borrar '{filename}' de forma remota por LAN (bórralo desde la pantalla táctil de la impresora)."
                )
        except httpx.HTTPError:
            pass

    raise RuntimeError(f"No se pudo verificar el borrado de '{filename}' en Creator 5 Pro ({ip}).")


async def set_flashforge_light(
    cfg: dict[str, Any],
    target_on: bool | None = None,
) -> tuple[bool, str]:
    """Enciende/apaga/conmuta la luz LED interna en Creator 5 Pro (`:8898/control`)."""
    async with httpx.AsyncClient(timeout=6.0, trust_env=False) as client:
        ip, eff_sn, access_code, detail = await _resolve_flashforge_target(cfg, client)
        cur_on = str(detail.get("lightStatus", "")).strip().lower() == "open"
        desired = (not cur_on) if target_on is None else bool(target_on)

        payload = {
            "serialNumber": eff_sn,
            "checkCode": access_code,
            "payload": {
                "cmd": "lightControl_cmd",
                "args": {"status": "open" if desired else "close"},
            },
        }
        try:
            resp = await client.post(f"http://{ip}:8898/control", json=payload)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("code") == 0:
                    await asyncio.sleep(0.25)
                    chk = await client.post(
                        f"http://{ip}:8898/detail",
                        json={"serialNumber": eff_sn, "checkCode": access_code},
                    )
                    actual_on = desired
                    if chk.status_code == 200:
                        d2 = chk.json().get("detail") or {}
                        if isinstance(d2, dict) and "lightStatus" in d2:
                            actual_on = str(d2.get("lightStatus", "")).lower() == "open"
                    txt = "ENCENDIDA" if actual_on else "APAGADA"
                    return actual_on, f"Luz LED en Creator 5 Pro ({ip}:8898): {txt}."
                raise RuntimeError(f"Creator 5 Pro luz error: {body.get('message', body)}")
        except httpx.HTTPError:
            pass

    port = int(cfg.get("port", 8899) or 8899)
    cmd = "~M146 r255 g255 b255" if desired else "~M146 r0 g0 b0"
    await asyncio.to_thread(_tcp_command_sync, ip, port, cmd, 3.0)
    txt = "ENCENDIDA" if desired else "APAGADA"
    return desired, f"Luz LED en Creator 5 Pro ({ip}:{port} TCP): {txt}."


async def control_flashforge(cfg: dict[str, Any], action: str) -> str:
    """Envía comando de pausa/reanudar/cancelar/luz por HTTP LAN `:8898/control` o TCP `:8899`."""
    if action in ("light_on", "light_off", "light_toggle"):
        target = True if action == "light_on" else False if action == "light_off" else None
        _on, msg = await set_flashforge_light(cfg, target_on=target)
        return msg

    if action not in ("pause", "resume", "cancel"):
        raise ValueError(f"Acción no soportada: {action}")

    async with httpx.AsyncClient(timeout=6.0, trust_env=False) as client:
        ip, eff_sn, access_code, _ = await _resolve_flashforge_target(cfg, client)
        ff_action = "continue" if action == "resume" else action
        payload = {
            "serialNumber": eff_sn,
            "checkCode": access_code,
            "payload": {
                "cmd": "jobCtl_cmd",
                "args": {"jobID": "", "action": ff_action},
            },
        }
        try:
            resp = await client.post(f"http://{ip}:8898/control", json=payload)
            if resp.status_code == 200:
                body = resp.json()
                return (
                    f"Comando '{action}' enviado a Creator 5 Pro ({ip}:8898): "
                    f"{body.get('message', 'OK')}."
                )
        except httpx.HTTPError:
            pass

    port = int(cfg.get("port", 8899) or 8899)
    tcp_cmd = {"pause": "~M25", "resume": "~M24", "cancel": "~M26"}[action]
    resp_txt = await asyncio.to_thread(_tcp_command_sync, ip, port, tcp_cmd, 3.0)
    return f"Comando '{action}' enviado a FlashForge TCP ({ip}:{port}): {resp_txt.strip()}"
