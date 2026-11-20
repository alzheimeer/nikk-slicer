"""Detector multiplataforma (macOS + Windows) de laminadores, rutas de usuario y configuración IA."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def get_os_label() -> str:
    if sys.platform == "darwin":
        return "macOS"
    if sys.platform.startswith("win"):
        return "Windows"
    return "Linux"


def get_user_data_dir() -> Path:
    """Devuelve `~/.nikk_slicer/` en macOS/Linux o `%APPDATA%\\NikkSlicer\\` en Windows."""
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", "").strip()
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
        d = base / "NikkSlicer"
    else:
        d = Path.home() / ".nikk_slicer"
    d.mkdir(parents=True, exist_ok=True)
    return d


SETTINGS_PATH = get_user_data_dir() / "settings.json"


def _load_settings() -> dict[str, Any]:
    if not SETTINGS_PATH.is_file():
        return {}
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_settings(data: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, SETTINGS_PATH)


def _slicer_catalog_specs() -> list[dict[str, Any]]:
    is_win = sys.platform.startswith("win")
    return [
        {
            "id": "orcaslicer",
            "name": "OrcaSlicer",
            "required": True,
            "description": "Motor CLI principal de laminado multi-impresora (Klipper, Marlin, CoreXY).",
            "download_url": (
                "https://github.com/SoftFever/OrcaSlicer/releases/latest"
                if is_win
                else "https://github.com/SoftFever/OrcaSlicer/releases/latest"
            ),
            "mac_candidates": [
                "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer",
                str(Path.home() / "Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"),
            ],
            "mac_profiles": [
                str(Path.home() / "Library/Application Support/OrcaSlicer"),
            ],
            "win_exe_names": ["orca-slicer.exe", "OrcaSlicer.exe"],
            "win_dirs": ["OrcaSlicer"],
            "win_profiles": ["OrcaSlicer"],
        },
        {
            "id": "orca_flashforge",
            "name": "Orca-Flashforge / Flash Studio",
            "required": True,
            "description": "Motor recomendado para FlashForge Creator 5 Pro (4 cabezales T0–T3).",
            "download_url": "https://www.flashforge.com/download-center",
            "mac_candidates": [
                "/Applications/Flash Studio.app/Contents/MacOS/Flash Studio",
                "/Applications/Orca-Flashforge.app/Contents/MacOS/Orca-Flashforge",
                "/Applications/FlashPrint 5.app/Contents/MacOS/FlashPrint",
                "/Applications/FlashPrint.app/Contents/MacOS/FlashPrint",
            ],
            "mac_profiles": [
                str(Path.home() / "Library/Application Support/Orca-Flashforge"),
                str(Path.home() / "Library/Application Support/Flash Studio"),
            ],
            "win_exe_names": ["Orca-Flashforge.exe", "Flash Studio.exe", "FlashPrint.exe"],
            "win_dirs": ["Orca-Flashforge", "FlashForge\\Orca-Flashforge", "FlashForge\\FlashPrint 5"],
            "win_profiles": ["Orca-Flashforge", "Flash Studio"],
        },
        {
            "id": "flsun_slicer",
            "name": "FLSun Slicer",
            "required": False,
            "description": "Motor y perfiles de referencia para impresoras Delta FLSUN (T1 Pro / V400 / SR).",
            "download_url": "https://flsun3d.com/pages/software-download",
            "mac_candidates": [
                "/Applications/FlsunSlicer.app/Contents/MacOS/FlsunSlicer",
                "/Applications/FLSUN Slicer.app/Contents/MacOS/FLSUN Slicer",
            ],
            "mac_profiles": [
                str(Path.home() / "Library/Application Support/FlsunSlicer"),
            ],
            "win_exe_names": ["FlsunSlicer.exe", "FLSUN Slicer.exe"],
            "win_dirs": ["FlsunSlicer", "FLSUN Slicer"],
            "win_profiles": ["FlsunSlicer"],
        },
    ]


def _win_find_executable(exe_names: list[str], subdirs: list[str]) -> str | None:
    if not sys.platform.startswith("win"):
        return None
    roots: list[Path] = []
    for env_key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        val = os.environ.get(env_key, "").strip()
        if val:
            p = Path(val)
            roots.append(p)
            if env_key == "LOCALAPPDATA":
                roots.append(p / "Programs")
    for root in roots:
        for sd in subdirs:
            for exe in exe_names:
                cand = root / sd / exe
                if cand.is_file():
                    return str(cand)
    try:
        import winreg  # type: ignore[import-not-found]

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            for exe in exe_names:
                try:
                    with winreg.OpenKey(
                        hive,
                        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}",
                    ) as key:
                        val, _ = winreg.QueryValueEx(key, "")
                        if val and Path(val).is_file():
                            return str(Path(val))
                except OSError:
                    continue
    except Exception:
        pass
    return None


def _resolve_custom_executable(raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    p = Path(raw_path).expanduser()
    if sys.platform == "darwin" and p.suffix.lower() == ".app" and p.is_dir():
        macos_dir = p / "Contents" / "MacOS"
        if macos_dir.is_dir():
            bins = [f for f in macos_dir.iterdir() if f.is_file() and os.access(f, os.X_OK)]
            if bins:
                return bins[0]
    if p.is_file():
        return p
    return None


def scan_installed_slicers() -> list[dict[str, Any]]:
    """Escanea de forma determinista y rápida los laminadores instalados en el sistema."""
    settings = _load_settings()
    custom_slicers: dict[str, str] = settings.get("slicers") or {}
    results: list[dict[str, Any]] = []
    is_win = sys.platform.startswith("win")

    for spec in _slicer_catalog_specs():
        sid = spec["id"]
        found_exe: str | None = None

        custom_cand = _resolve_custom_executable(custom_slicers.get(sid))
        if custom_cand is not None:
            found_exe = str(custom_cand)
        elif is_win:
            found_exe = _win_find_executable(spec["win_exe_names"], spec["win_dirs"])
        else:
            for mc in spec["mac_candidates"]:
                if Path(mc).is_file():
                    found_exe = mc
                    break

        found_prof: str | None = None
        if is_win:
            appdata = os.environ.get("APPDATA", "").strip()
            if appdata:
                for wp in spec["win_profiles"]:
                    cand_p = Path(appdata) / wp
                    if cand_p.is_dir():
                        found_prof = str(cand_p)
                        break
        else:
            for mp in spec["mac_profiles"]:
                if Path(mp).is_dir():
                    found_prof = mp
                    break

        results.append(
            {
                "id": sid,
                "name": spec["name"],
                "required": bool(spec["required"]),
                "description": spec["description"],
                "detected": bool(found_exe),
                "executable_path": found_exe,
                "profiles_path": found_prof,
                "download_url": spec["download_url"],
            }
        )

    settings["last_scan_at"] = datetime.now(timezone.utc).isoformat()
    _save_settings(settings)
    return results


def get_detected_slicer_executable(slicer_id: str) -> Path | None:
    for item in scan_installed_slicers():
        if item["id"] == slicer_id and item.get("executable_path"):
            p = Path(item["executable_path"])
            if p.is_file():
                return p
    return None


def set_slicer_path(slicer_id: str, raw_path: str) -> dict[str, Any]:
    resolved = _resolve_custom_executable(raw_path)
    if resolved is None:
        raise ValueError(f"El archivo seleccionado no es un ejecutable válido: {raw_path}")
    settings = _load_settings()
    slicers = dict(settings.get("slicers") or {})
    slicers[slicer_id] = str(resolved)
    settings["slicers"] = slicers
    _save_settings(settings)

    if slicer_id == "orca_flashforge":
        os.environ["FLASH_STUDIO_CLI"] = str(resolved)
    elif slicer_id == "orcaslicer":
        os.environ["ORCA_SLICER_CLI"] = str(resolved)

    return {"slicer_id": slicer_id, "executable_path": str(resolved), "detected": True}


def get_active_ai_config() -> dict[str, Any]:
    settings = _load_settings()
    provider = str(settings.get("ai_provider") or os.environ.get("NIKK_AI_PROVIDER") or "deepseek").lower()
    if provider not in ("deepseek", "gemini"):
        provider = "deepseek"
    key = str(
        settings.get("ai_api_key")
        or (os.environ.get("GEMINI_API_KEY") if provider == "gemini" else os.environ.get("DEEPSEEK_API_KEY"))
        or ""
    ).strip()
    if key:
        os.environ["NIKK_AI_PROVIDER"] = provider
        if provider == "gemini":
            os.environ["GEMINI_API_KEY"] = key
        else:
            os.environ["DEEPSEEK_API_KEY"] = key
    masked = f"{key[:4]}...{key[-4:]}" if len(key) > 10 else ("***" if key else "")
    return {
        "provider": provider,
        "has_api_key": bool(key),
        "masked_key": masked,
    }


def save_ai_config(provider: str, api_key: str) -> dict[str, Any]:
    clean_prov = provider.strip().lower()
    if clean_prov not in ("deepseek", "gemini"):
        raise ValueError("Proveedor IA debe ser 'deepseek' o 'gemini'.")
    clean_key = api_key.strip()
    settings = _load_settings()
    settings["ai_provider"] = clean_prov
    if clean_key:
        settings["ai_api_key"] = clean_key
    _save_settings(settings)

    os.environ["NIKK_AI_PROVIDER"] = clean_prov
    if clean_key:
        if clean_prov == "gemini":
            os.environ["GEMINI_API_KEY"] = clean_key
        else:
            os.environ["DEEPSEEK_API_KEY"] = clean_key
    return get_active_ai_config()


def get_system_environment(mcp_tools_count: int = 18) -> dict[str, Any]:
    slicers = scan_installed_slicers()
    has_any_primary = any(s["detected"] and s["required"] for s in slicers)
    missing_required = [s["name"] for s in slicers if s["required"] and not s["detected"]]
    return {
        "os": get_os_label(),
        "platform": sys.platform,
        "user_data_dir": str(get_user_data_dir()),
        "slicers": slicers,
        "has_primary_slicer": has_any_primary,
        "missing_required": missing_required,
        "ai_config": get_active_ai_config(),
        "mcp": {
            "http_url": "http://127.0.0.1:8000/mcp",
            "stdio_command": "python3 -m backend.app.mcp_server",
            "tools_count": mcp_tools_count,
        },
    }
