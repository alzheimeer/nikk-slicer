"""Registro persistente de impresoras activas del usuario (user_printers.json)."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from app.core.orca_catalog import get_orca_catalog_entry
from app.core.platform_detector import get_user_data_dir

USER_PRINTERS_PATH = get_user_data_dir() / "user_printers.json"


def _infer_base_profile_id(
    kinematics: str,
    is_high_speed: bool,
    is_multicolor: bool,
) -> str:
    if kinematics == "delta":
        return "flsun_t1_pro" if is_high_speed else "flsun_sr"
    if kinematics == "corexy" or is_multicolor:
        return "creator5_pro"
    return "ender3_s1_pro"


def _enrich_builtin_entry(inst_id: str, cfg: dict[str, Any], base_registry: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(cfg.get("profile_id") or "flsun_t1_pro")
    base = base_registry.get(profile_id)
    is_delta = bool(base and base.kinematics == "delta")
    is_creator = profile_id == "creator5_pro"
    bed_mm = list(base.bed_mm) if (base and base.bed_mm) else None
    diam = float(base.diameter_mm) if (base and base.diameter_mm) else None
    height = float(base.height_mm) if base else 250.0
    q_max = float(base.max_volumetric_flow_mm3_s) if base else 18.0
    flavor = "klipper" if profile_id in ("flsun_t1_pro", "flsun_v400", "creator5_pro") else "marlin2"
    vendor = (
        "FLSun"
        if profile_id.startswith("flsun_")
        else ("Flashforge" if is_creator else "Creality")
    )
    return {
        **cfg,
        "vendor": str(cfg.get("vendor") or vendor),
        "model_name": str(cfg.get("model_name") or (base.display_name if base else cfg.get("name", inst_id))),
        "bed_shape": str(cfg.get("bed_shape") or ("circular" if is_delta else "rectangular")),
        "bed_width_mm": float(cfg.get("bed_width_mm") or (diam if is_delta and diam else (bed_mm[0] if bed_mm else 220.0))),
        "bed_depth_mm": float(cfg.get("bed_depth_mm") or (diam if is_delta and diam else (bed_mm[1] if bed_mm else 220.0))),
        "bed_diameter_mm": cfg.get("bed_diameter_mm") if cfg.get("bed_diameter_mm") is not None else diam,
        "max_height_mm": float(cfg.get("max_height_mm") or height),
        "kinematics": str(cfg.get("kinematics") or (base.kinematics if base else "cartesian")),
        "gcode_flavor": str(cfg.get("gcode_flavor") or flavor),
        "estimated_q_max": float(cfg.get("estimated_q_max") or q_max),
        "is_multicolor": bool(cfg.get("is_multicolor", is_creator)),
        "tool_count": int(cfg.get("tool_count") or (4 if is_creator else 1)),
        "has_heated_chamber": bool(cfg.get("has_heated_chamber", is_creator)),
        "is_high_speed": bool(cfg.get("is_high_speed", profile_id in ("flsun_t1_pro", "flsun_v400", "creator5_pro"))),
        "nozzle_diameter": float(cfg.get("nozzle_diameter") or 0.4),
        "connection_mode": str(cfg.get("connection_mode") or ("lan" if cfg.get("ip") else "usb_sd")),
        "is_custom": bool(cfg.get("is_custom", False)),
    }


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def ensure_user_printers_initialized(
    legacy_configs: dict[str, dict[str, Any]],
    base_registry: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Asegura que `user_printers.json` exista precargando las impresoras actuales."""
    if USER_PRINTERS_PATH.is_file():
        try:
            raw = json.loads(USER_PRINTERS_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and raw:
                return {
                    str(pid): _enrich_builtin_entry(str(pid), cfg, base_registry)
                    for pid, cfg in raw.items()
                    if isinstance(cfg, dict)
                }
        except Exception:
            pass

    seeded = {
        str(pid): _enrich_builtin_entry(str(pid), cfg, base_registry)
        for pid, cfg in legacy_configs.items()
        if isinstance(cfg, dict)
    }
    _atomic_write_json(USER_PRINTERS_PATH, seeded)
    return seeded


def load_user_printers_raw() -> dict[str, dict[str, Any]]:
    if not USER_PRINTERS_PATH.is_file():
        return {}
    try:
        raw = json.loads(USER_PRINTERS_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def save_user_printers_raw(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    _atomic_write_json(USER_PRINTERS_PATH, data)
    return data


def add_user_printer_from_catalog(
    catalog_id: str,
    display_name: str | None = None,
    nozzle_diameter: float = 0.4,
    connection_mode: str = "lan",
    ip: str = "",
    port: int | None = None,
    protocol: str | None = None,
    is_multicolor: bool | None = None,
    tool_count: int | None = None,
) -> dict[str, Any]:
    """Registra una impresora del catálogo OrcaSlicer en `user_printers.json`."""
    from app.config import load_printers_config

    entry = get_orca_catalog_entry(catalog_id)
    if entry is None:
        raise ValueError(f"Modelo de catálogo no encontrado: {catalog_id}")

    existing = load_printers_config()
    caps = entry.get("capabilities") or {}
    eff_mc = bool(caps.get("is_multicolor", False)) if is_multicolor is None else bool(is_multicolor)
    eff_tools = int(tool_count if tool_count is not None else (caps.get("tool_count", 4) if eff_mc else 1))
    eff_tools = max(1, min(16, eff_tools if eff_mc else 1))
    kin = str(entry.get("kinematics") or "cartesian")
    is_hs = bool(caps.get("is_high_speed", False))
    flavor = str(entry.get("gcode_flavor") or "marlin2")

    base_profile_id = _infer_base_profile_id(kin, is_hs, eff_mc)
    clean_ip = ip.strip() if connection_mode == "lan" else ""

    if protocol and protocol in ("moonraker", "flashforge_lan", "marlin_serial"):
        eff_proto = protocol
    elif connection_mode != "lan" or not clean_ip:
        eff_proto = "marlin_serial"
    elif "flashforge" in str(entry.get("vendor") or "").lower():
        eff_proto = "flashforge_lan"
    else:
        eff_proto = "moonraker"

    eff_port = int(port or (8899 if eff_proto == "flashforge_lan" else 7125))
    base_slug = re.sub(r"[^a-z0-9]+", "_", catalog_id.lower()).strip("_") or "custom_printer"
    idx = 1
    new_id = f"{base_slug}_{idx}"
    while new_id in existing:
        idx += 1
        new_id = f"{base_slug}_{idx}"

    name = (display_name or "").strip() or str(entry.get("model_name") or new_id)
    cam_url = ""
    if clean_ip:
        cam_url = (
            f"http://{clean_ip}:8080/?action=stream"
            if eff_proto == "flashforge_lan"
            else f"http://{clean_ip}/webcam/?action=stream"
        )

    record: dict[str, Any] = {
        "id": new_id,
        "name": name,
        "profile_id": base_profile_id,
        "catalog_id": catalog_id,
        "vendor": str(entry.get("vendor") or "Custom"),
        "model_name": str(entry.get("model_name") or name),
        "protocol": eff_proto,
        "connection_mode": "lan" if clean_ip else "usb_sd",
        "ip": clean_ip,
        "fallback_ips": [clean_ip] if clean_ip else [],
        "port": eff_port,
        "http_port": 8080,
        "access_code": "",
        "serial_number": "",
        "serial_port": "",
        "baudrate": 115200,
        "sd_volume_path": "",
        "camera_url": cam_url,
        "enabled": True,
        "is_custom": True,
        "bed_shape": str(entry.get("bed_shape") or "rectangular"),
        "bed_width_mm": float(entry.get("bed_width_mm") or 220.0),
        "bed_depth_mm": float(entry.get("bed_depth_mm") or 220.0),
        "bed_diameter_mm": entry.get("bed_diameter_mm"),
        "max_height_mm": float(entry.get("max_height_mm") or 250.0),
        "kinematics": kin,
        "gcode_flavor": flavor,
        "max_speed_mm_s": int(entry.get("max_speed_mm_s") or 200),
        "max_accel_mm_s2": int(entry.get("max_accel_mm_s2") or 3000),
        "estimated_q_max": float(entry.get("estimated_q_max") or 18.0),
        "is_multicolor": eff_mc,
        "tool_count": eff_tools,
        "has_heated_chamber": bool(caps.get("has_heated_chamber", False)),
        "is_high_speed": is_hs,
        "nozzle_diameter": float(nozzle_diameter or 0.4),
        "profile_sub_path": str(entry.get("profile_sub_path") or ""),
    }
    existing[new_id] = record
    save_user_printers_raw(existing)
    return record


def update_user_printer(printer_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    from app.config import load_printers_config

    existing = load_printers_config()
    if printer_id not in existing:
        raise ValueError(f"Impresora no encontrada: {printer_id}")
    entry = dict(existing[printer_id])

    for key in (
        "name",
        "ip",
        "port",
        "protocol",
        "connection_mode",
        "nozzle_diameter",
        "is_multicolor",
        "tool_count",
        "has_heated_chamber",
        "enabled",
        "serial_port",
        "sd_volume_path",
        "camera_url",
    ):
        if key in patch and patch[key] is not None:
            entry[key] = patch[key]

    if not entry.get("is_multicolor", False):
        entry["tool_count"] = 1
    else:
        entry["tool_count"] = max(2, min(16, int(entry.get("tool_count") or 4)))

    if entry.get("connection_mode") == "usb_sd":
        entry["ip"] = ""
        entry["protocol"] = "marlin_serial"

    existing[printer_id] = entry
    save_user_printers_raw(existing)
    return entry


def delete_user_printer(printer_id: str) -> dict[str, Any]:
    from app.config import load_printers_config

    existing = load_printers_config()
    if printer_id not in existing:
        raise ValueError(f"Impresora no encontrada: {printer_id}")
    if len(existing) <= 1:
        raise ValueError("Debe permanecer al menos una impresora activa en el registro.")
    removed = existing.pop(printer_id)
    save_user_printers_raw(existing)
    return removed
