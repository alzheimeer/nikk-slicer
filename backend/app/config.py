"""Configuración central de rutas macOS y catálogo de impresoras para SlicerHub."""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_DIR.parent
PROFILES_DIR = BACKEND_DIR / "profiles"
MACHINES_DIR = PROFILES_DIR / "machines"
FILAMENTS_DIR = PROFILES_DIR / "filaments"
PROCESS_DIR = PROFILES_DIR / "process"
CATALOG_PATH = PROFILES_DIR / "slicerhub_catalog.json"
PRINTERS_CONFIG_PATH = BACKEND_DIR / "printers_config.json"
BACKEND_ENV_PATH = BACKEND_DIR / ".env"
if getattr(sys, "frozen", False):
    from app.core.platform_detector import get_user_data_dir

    TEMP_DIR = get_user_data_dir() / "temp"
else:
    TEMP_DIR = BACKEND_DIR / "temp"
MESH_CACHE_DIR = TEMP_DIR / "meshes"

FLASH_STUDIO_CLI = Path(
    os.environ.get("FLASH_STUDIO_CLI", "/Applications/Flash Studio.app/Contents/MacOS/Flash Studio")
)
ORCA_SLICER_CLI = Path("/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer")
FLSUN_SLICER_CLI = Path("/Applications/FlsunSlicer.app/Contents/MacOS/FlsunSlicer")

MATERIAL_TO_PROFILE: dict[str, str] = {
    "pla": "pla_master",
    "petg": "petg_master",
    "abs": "abs_master",
    "tpu": "tpu_master",
}

PRESET_TO_PROFILE: dict[str, str] = {
    "estandar": "estandar",
    "mecanico_resistente": "mecanico_resistente",
    "alta_velocidad": "alta_velocidad",
    "rapidez_extrema": "rapidez_extrema",
}

NOZZLE_DIAMETERS: tuple[float, ...] = (0.2, 0.4, 0.6, 0.8)

DEFAULT_SUPPORT_Z_BY_MATERIAL: dict[str, float] = {
    "pla": 0.20,
    "petg": 0.30,
    "abs": 0.24,
    "tpu": 0.28,
}

DEFAULT_SUPPORT_XY_BY_MATERIAL: dict[str, float] = {
    "pla": 0.50,
    "petg": 0.60,
    "abs": 0.55,
    "tpu": 0.60,
}


def compute_default_support_xy(material: str, nozzle_diameter: float = 0.4) -> float:
    """Calcula la separación lateral XY recomendada escalada por diámetro de boquilla."""
    base = float(DEFAULT_SUPPORT_XY_BY_MATERIAL.get(material, 0.50))
    return round(max(0.25, base * (float(nozzle_diameter) / 0.4)), 2)


LITHOPHANE_MACHINE_PROFILES: dict[str, dict[str, Any]] = {
    "flsun_t1_pro": {
        "outer_wall_speed": 65,
        "outer_wall_speed_hs": 75,
        "inner_wall_speed": 95,
        "sparse_infill_speed": 100,
        "top_surface_speed": 60,
        "default_acceleration": 3000,
        "outer_wall_acceleration": 1800,
    },
    "flsun_v400": {
        "outer_wall_speed": 55,
        "outer_wall_speed_hs": 65,
        "inner_wall_speed": 80,
        "sparse_infill_speed": 85,
        "top_surface_speed": 55,
        "default_acceleration": 2000,
        "outer_wall_acceleration": 1200,
    },
    "flsun_sr": {
        "outer_wall_speed": 42,
        "outer_wall_speed_hs": 50,
        "inner_wall_speed": 60,
        "sparse_infill_speed": 65,
        "top_surface_speed": 45,
        "default_acceleration": 1500,
        "outer_wall_acceleration": 900,
    },
    "creator5_pro": {
        "outer_wall_speed": 60,
        "outer_wall_speed_hs": 70,
        "inner_wall_speed": 85,
        "sparse_infill_speed": 90,
        "top_surface_speed": 55,
        "default_acceleration": 2500,
        "outer_wall_acceleration": 1500,
    },
    "ender3_s1_pro": {
        "outer_wall_speed": 32,
        "outer_wall_speed_hs": 38,
        "inner_wall_speed": 45,
        "sparse_infill_speed": 45,
        "top_surface_speed": 32,
        "default_acceleration": 850,
        "outer_wall_acceleration": 500,
        "default_jerk": 7,
    },
}


def compute_lithophane_process_overrides(
    profile_id: str,
    high_speed: bool = False,
    nozzle_diameter: float = 0.4,
    brim_width_mm: float = 8.0,
) -> dict[str, str]:
    """Devuelve el diccionario exacto de claves Orca/Flash Studio para Modo Litofanía."""
    spec = LITHOPHANE_MACHINE_PROFILES.get(
        profile_id, LITHOPHANE_MACHINE_PROFILES["flsun_t1_pro"]
    )
    hs_factor = 1.15 if high_speed else 1.0
    outer_speed = int(
        spec["outer_wall_speed_hs"] if high_speed else spec["outer_wall_speed"]
    )
    inner_speed = int(round(float(spec["inner_wall_speed"]) * hs_factor))
    infill_speed = int(round(float(spec["sparse_infill_speed"]) * hs_factor))
    top_speed = int(round(float(spec["top_surface_speed"]) * hs_factor))
    layer_h = "0.10" if float(nozzle_diameter) <= 0.25 else "0.12"
    brim_w = str(int(round(max(8.0, min(10.0, float(brim_width_mm))))))

    overrides: dict[str, str] = {
        "layer_height": layer_h,
        "initial_layer_print_height": "0.20",
        "sparse_infill_density": "99%",
        "sparse_infill_pattern": "rectilinear",
        "wall_loops": "6",
        "detect_thin_wall": "1",
        "wall_generator": "arachne",
        "seam_position": "back",
        "enable_support": "0",
        "raft_layers": "0",
        "brim_type": "outer_only",
        "brim_width": brim_w,
        "brim_object_gap": "0.12",
        "outer_wall_speed": str(outer_speed),
        "inner_wall_speed": str(inner_speed),
        "sparse_infill_speed": str(infill_speed),
        "top_surface_speed": str(top_speed),
        "default_acceleration": str(spec["default_acceleration"]),
        "outer_wall_acceleration": str(spec["outer_wall_acceleration"]),
    }
    if "default_jerk" in spec:
        overrides["default_jerk"] = str(spec["default_jerk"])
    return overrides


DEFAULT_DEEPSEEK_API_KEY = ""


def load_dotenv() -> None:
    """Carga variables opcionales desde `.env` sin requerir dependencias externas."""
    for env_path in (BACKEND_DIR / ".env", PROJECT_ROOT / ".env"):
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


load_dotenv()
if DEFAULT_DEEPSEEK_API_KEY:
    os.environ.setdefault("DEEPSEEK_API_KEY", DEFAULT_DEEPSEEK_API_KEY)


@dataclass(frozen=True)
class PrinterConfig:
    """Definición de hardware y rutas CLI para un perfil base de impresora de la granja."""

    printer_id: str
    profile_id: str
    display_name: str
    kinematics: str
    origin: str
    cli_binary: Path
    machine_profile: Path
    diameter_mm: float | None
    height_mm: float
    bed_mm: tuple[float, float, float] | None
    usable_edge_z_mm: float | None
    max_volumetric_flow_mm3_s: float
    extruder_slots: int = 1


DISPLAY_NAMES: dict[str, str] = {
    "flsun_v400": "FLSUN V400",
    "flsun_t1_pro": "FLSUN T1 Pro",
    "flsun_sr": "FLSUN Super Racer (SR)",
    "creator5_pro": "FlashForge Creator 5 Pro",
    "ender3_s1_pro": "Creality Ender 3 S1 Pro",
}

PROFILE_PROTOCOL_DEFAULTS: dict[str, tuple[str, int]] = {
    "flsun_v400": ("moonraker", 80),
    "flsun_t1_pro": ("moonraker", 80),
    "flsun_sr": ("marlin_serial", 7125),
    "creator5_pro": ("flashforge_lan", 8899),
    "ender3_s1_pro": ("marlin_serial", 7125),
}


def resolve_cli_binary(printer_id: str, catalog_binary: str | None = None) -> Path:
    """Resuelve el binario CLI disponible en macOS o Windows mediante auto-detección multiplataforma."""
    from app.core.platform_detector import get_detected_slicer_executable

    if printer_id == "ender3_s1_pro":
        orca_det = get_detected_slicer_executable("orcaslicer")
        if orca_det is not None:
            return orca_det
        if ORCA_SLICER_CLI.exists():
            return ORCA_SLICER_CLI
    if catalog_binary:
        candidate = Path(catalog_binary)
        if candidate.exists():
            return candidate
    ff_det = get_detected_slicer_executable("orca_flashforge")
    if ff_det is not None:
        return ff_det
    if FLASH_STUDIO_CLI.exists():
        return FLASH_STUDIO_CLI
    orca_det = get_detected_slicer_executable("orcaslicer")
    if orca_det is not None:
        return orca_det
    if ORCA_SLICER_CLI.exists():
        return ORCA_SLICER_CLI
    flsun_det = get_detected_slicer_executable("flsun_slicer")
    if flsun_det is not None:
        return flsun_det
    raise FileNotFoundError(
        "No se encontró un binario CLI compatible (OrcaSlicer / Orca-Flashforge / FLSun Slicer). "
        "Configúralo desde Entorno del Sistema."
    )


def load_catalog() -> dict[str, Any]:
    """Carga el catálogo de Fase 0 (`backend/profiles/slicerhub_catalog.json`)."""
    with CATALOG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def compute_optimal_temperatures(
    printer_id: str,
    material: str,
    spool_min: int | None = None,
    spool_max: int | None = None,
    high_speed: bool = False,
    nozzle_diameter: float = 0.4,
) -> dict[str, int]:
    """Calcula automáticamente temperaturas óptimas según flujo de impresora, HS y rango de carrete."""
    profile_id = resolve_profile_id(printer_id) if printer_id else "flsun_t1_pro"
    catalog = load_catalog()
    ranges = catalog.get("material_temp_ranges", {}).get(material, {})
    rec_min = int(ranges.get("recommended_min", 190))
    rec_max = int(ranges.get("recommended_max", 225))
    bed_temp = int(ranges.get("default_bed", 60))

    lo = int(spool_min) if spool_min is not None else rec_min
    hi = int(spool_max) if spool_max is not None else rec_max
    if hi <= lo:
        hi = lo + 5
    span = hi - lo

    if profile_id in ("flsun_t1_pro", "flsun_v400") or high_speed:
        ratio_print = 0.80
        ratio_init = 0.97
    elif profile_id in ("ender3_s1_pro", "flsun_sr"):
        ratio_print = 0.55
        ratio_init = 0.75
    else:
        ratio_print = 0.65
        ratio_init = 0.85

    nozzle_delta = 3 if nozzle_diameter >= 0.6 else (-3 if nozzle_diameter <= 0.2 else 0)
    nozzle_temp = max(lo, min(hi, round(lo + span * ratio_print) + nozzle_delta))
    nozzle_temp_initial = max(
        nozzle_temp, min(hi, round(lo + span * ratio_init) + nozzle_delta)
    )
    return {
        "nozzle_temp": int(nozzle_temp),
        "nozzle_temp_initial_layer": int(nozzle_temp_initial),
        "bed_temp": bed_temp,
        "spool_min": lo,
        "spool_max": hi,
    }


def get_slot_volumetric_limit(
    printer_id: str,
    material: str,
    high_speed: bool = False,
) -> float:
    """Devuelve el caudal volumétrico máximo (mm³/s) para un material y boquilla HS opcional."""
    profile_id = resolve_profile_id(printer_id) if printer_id else "creator5_pro"
    catalog = load_catalog()
    eff_mat = "pla" if material == "soporte" else material
    mat_key = MATERIAL_TO_PROFILE.get(eff_mat, "pla_master")
    table_key = (
        "high_speed_volumetric_limits_mm3_s"
        if high_speed
        else "volumetric_limits_mm3_s"
    )
    val = catalog.get(table_key, {}).get(mat_key, {}).get(profile_id)
    if val is not None:
        return float(val)
    return 18.0


def negotiate_multimaterial_bed_temp(materials: list[str]) -> int:
    """Calcula la temperatura de cama negociada para adherencia multi-material en primera capa."""
    body_mats = {m for m in materials if m in ("pla", "petg", "abs", "tpu")}
    if not body_mats:
        return 60
    if len(body_mats) == 1:
        only = next(iter(body_mats))
        return {"pla": 60, "petg": 75, "abs": 100, "tpu": 50}[only]
    if "abs" in body_mats:
        return 90 if ("pla" in body_mats or "tpu" in body_mats) else 95
    if "petg" in body_mats and "pla" in body_mats:
        return 65
    if "petg" in body_mats and "tpu" in body_mats:
        return 65
    if "pla" in body_mats and "tpu" in body_mats:
        return 58
    return 65


def get_optimal_chamber_config(
    active_materials: list[str],
    override_temp: int | None = None,
) -> dict[str, Any]:
    """Calcula la temperatura objetivo y modo de ventilación del habitáculo (Creator 5 Pro)."""
    norm = {str(m).strip().lower() for m in active_materials if str(m).strip().lower() != "soporte"}

    if "pla" in norm or "tpu" in norm:
        target_temp = 30
        max_safe = 35
        mode = "extraction"
        mode_label = "Extracción PLA/TPU" if "tpu" in norm else "Extracción PLA"
        p2_fan = 128
        p3_fan = 153
    elif "abs" in norm or "asa" in norm:
        target_temp = 50
        max_safe = 55
        mode = "preheat_closed"
        mode_label = "Precalentamiento ABS/ASA" if "asa" in norm else "Precalentamiento ABS"
        p2_fan = 0
        p3_fan = 255
    else:
        target_temp = 40
        max_safe = 45
        mode = "recirculation"
        mode_label = "Recirculación PETG"
        p2_fan = 0
        p3_fan = 102

    if override_temp is not None:
        target_temp = max(25, min(55, int(override_temp)))

    return {
        "target_temp": target_temp,
        "max_safe_temp": max_safe,
        "mode": mode,
        "mode_label": mode_label,
        "p2_fan": p2_fan,
        "p3_fan": p3_fan,
    }


def compute_heterogeneous_speed_cap(
    volumetric_limits: list[float],
    materials: list[str],
    nozzle_diameter: float = 0.4,
) -> dict[str, int]:
    """Calcula el techo de velocidades lineales gobernado por el carrete de menor caudal."""
    min_flow = min(volumetric_limits) if volumetric_limits else 18.0
    has_tpu = any(m == "tpu" for m in materials)
    nozzle = max(0.2, float(nozzle_diameter))
    cross_section = (nozzle * 1.1) * (nozzle * 0.5)
    raw_linear = int(round(min_flow / max(0.02, cross_section)))
    if has_tpu:
        raw_linear = min(raw_linear, 80)
    return {
        "min_volumetric_flow": int(round(min_flow)),
        "max_linear_speed": max(25, raw_linear),
        "outer_wall_cap": max(25, min(raw_linear, 55 if has_tpu else raw_linear)),
        "inner_wall_cap": max(30, min(raw_linear, 75 if has_tpu else raw_linear)),
        "infill_cap": max(35, min(raw_linear, 85 if has_tpu else raw_linear)),
    }


MACHINE_THERMAL_KINEMATIC_LIMITS: dict[str, dict[str, Any]] = {
    "flsun_t1_pro": {
        "max_volumetric_speed": {"pla": 26.0, "petg": 17.0, "abs": 20.0, "tpu": 10.0},
        "outer_wall_speed_range": {"pla": (140, 220), "petg": (90, 140), "abs": (110, 160), "tpu": (45, 70)},
        "inner_wall_speed_range": {"pla": (230, 350), "petg": (140, 200), "abs": (160, 230), "tpu": (60, 85)},
        "sparse_infill_speed_range": {"pla": (260, 380), "petg": (160, 220), "abs": (180, 250), "tpu": (65, 95)},
        "default_acceleration": 15000,
        "outer_wall_acceleration": 6000,
        "thick_layer_temp_boost_c": 0,
        "petg_fan_range": None,
    },
    "flsun_v400": {
        "max_volumetric_speed": {"pla": 17.0, "petg": 12.0, "abs": 13.0, "tpu": 8.0},
        "outer_wall_speed_range": {"pla": (85, 100), "petg": (65, 75), "abs": (70, 85), "tpu": (35, 50)},
        "inner_wall_speed_range": {"pla": (120, 140), "petg": (85, 100), "abs": (90, 110), "tpu": (45, 60)},
        "sparse_infill_speed_range": {"pla": (140, 160), "petg": (95, 110), "abs": (105, 125), "tpu": (50, 65)},
        "default_acceleration": 3200,
        "outer_wall_acceleration": 2000,
        "thick_layer_temp_boost_c": 5,
        "petg_fan_range": (15, 35),
    },
    "creator5_pro": {
        "max_volumetric_speed": {"pla": 19.0, "petg": 13.0, "abs": 14.0, "tpu": 8.0},
        "outer_wall_speed_range": {"pla": (90, 110), "petg": (70, 80), "abs": (75, 90), "tpu": (35, 50)},
        "inner_wall_speed_range": {"pla": (130, 150), "petg": (90, 110), "abs": (100, 120), "tpu": (45, 65)},
        "sparse_infill_speed_range": {"pla": (150, 180), "petg": (110, 130), "abs": (120, 145), "tpu": (50, 70)},
        "default_acceleration": 4500,
        "outer_wall_acceleration": 2500,
        "thick_layer_temp_boost_c": 5,
        "petg_fan_range": None,
    },
    "flsun_sr": {
        "max_volumetric_speed": {"pla": 12.0, "petg": 8.5, "abs": 9.5, "tpu": 6.0},
        "outer_wall_speed_range": {"pla": (60, 85), "petg": (50, 65), "abs": (55, 70), "tpu": (30, 45)},
        "inner_wall_speed_range": {"pla": (75, 95), "petg": (60, 75), "abs": (65, 85), "tpu": (35, 55)},
        "sparse_infill_speed_range": {"pla": (85, 110), "petg": (65, 85), "abs": (75, 95), "tpu": (40, 60)},
        "default_acceleration": 2200,
        "outer_wall_acceleration": 1500,
        "thick_layer_temp_boost_c": 5,
        "petg_fan_range": None,
    },
    "ender3_s1_pro": {
        "max_volumetric_speed": {"pla": 11.0, "petg": 8.0, "abs": 9.0, "tpu": 6.5},
        "outer_wall_speed_range": {"pla": (55, 80), "petg": (45, 60), "abs": (50, 65), "tpu": (30, 45)},
        "inner_wall_speed_range": {"pla": (70, 90), "petg": (55, 70), "abs": (60, 75), "tpu": (35, 50)},
        "sparse_infill_speed_range": {"pla": (80, 100), "petg": (60, 80), "abs": (70, 85), "tpu": (40, 55)},
        "default_acceleration": 1500,
        "outer_wall_acceleration": 1000,
        "thick_layer_temp_boost_c": 5,
        "petg_fan_range": None,
    },
}


def get_machine_thermal_kinematic_limits(printer_id: str) -> dict[str, Any]:
    """Devuelve los límites térmicos y cinemáticos auditados para `printer_id`."""
    profile_id = resolve_profile_id(printer_id)
    return MACHINE_THERMAL_KINEMATIC_LIMITS.get(
        profile_id, MACHINE_THERMAL_KINEMATIC_LIMITS["creator5_pro"]
    )


def clamp_speed_by_volumetric_flow(
    printer_id: str,
    material: str,
    layer_height: float,
    line_width: float,
    requested_speeds: dict[str, float],
    high_speed: bool = False,
) -> dict[str, Any]:
    """Recorta velocidades que excedan v_max = Q_max / (h * w) y aplica compensación térmica."""
    profile_id = resolve_profile_id(printer_id)
    limits = get_machine_thermal_kinematic_limits(profile_id)
    mat = str(material).strip().lower()
    if mat not in ("pla", "petg", "abs", "tpu"):
        mat = "pla"

    q_max = float(limits["max_volumetric_speed"].get(mat, 12.0))
    if high_speed:
        q_max = round(q_max * 1.12, 2)

    h = max(0.08, float(layer_height))
    w = max(0.20, float(line_width))
    eff_q = q_max * 0.90 if h >= 0.24 else q_max
    v_max = eff_q / (h * w)

    role_ceilings = {
        "outer_wall_speed": limits["outer_wall_speed_range"].get(mat, (55, 110))[1],
        "top_surface_speed": limits["outer_wall_speed_range"].get(mat, (55, 110))[1],
        "inner_wall_speed": limits["inner_wall_speed_range"].get(mat, (75, 150))[1],
        "sparse_infill_speed": limits["sparse_infill_speed_range"].get(mat, (90, 180))[1],
        "internal_solid_infill_speed": limits["sparse_infill_speed_range"].get(mat, (90, 180))[1],
    }

    clamped: dict[str, int] = {}
    notes: list[str] = []
    was_clamped = False
    for key, req_v in requested_speeds.items():
        val = float(req_v)
        # En capas gruesas (>= 0.24 mm) o cuando excede v_max, aplicar también el techo cinemático auditado
        role_cap = float(role_ceilings.get(key, v_max))
        eff_cap = min(v_max, role_cap) if (h >= 0.24 or profile_id != "flsun_t1_pro") else v_max
        if val > eff_cap:
            new_v = max(25, int(math.floor(eff_cap)))
            if new_v < int(round(val)):
                was_clamped = True
                notes.append(f"{key}: {int(round(val))} -> {new_v} mm/s (Q_max={q_max} mm3/s)")
            clamped[key] = new_v
        else:
            clamped[key] = max(25, int(round(val)))

    temp_boost = 0
    if h >= 0.27 and profile_id != "flsun_t1_pro":
        temp_boost = 8
    elif was_clamped or (profile_id == "flsun_v400" and h >= 0.24):
        temp_boost = int(limits.get("thick_layer_temp_boost_c", 5) or 5)

    return {
        "profile_id": profile_id,
        "material": mat,
        "q_max_mm3_s": q_max,
        "v_max_mms": round(v_max, 1),
        "clamped_speeds": clamped,
        "was_clamped": was_clamped,
        "temp_boost_c": temp_boost,
        "notes": notes,
    }


def build_printer_registry() -> dict[str, PrinterConfig]:
    """Construye el registro de las 5 impresoras desde `slicerhub_catalog.json`."""
    catalog = load_catalog()
    machines_raw = catalog["machines"]
    registry: dict[str, PrinterConfig] = {}

    for pid, meta in machines_raw.items():
        bed_raw = meta.get("bed_mm")
        bed_tuple = (
            (float(bed_raw[0]), float(bed_raw[1]), float(bed_raw[2]))
            if isinstance(bed_raw, list) and len(bed_raw) == 3
            else None
        )
        height = float(meta.get("height_mm") or (bed_tuple[2] if bed_tuple else 250.0))
        registry[pid] = PrinterConfig(
            printer_id=pid,
            profile_id=pid,
            display_name=DISPLAY_NAMES.get(pid, pid),
            kinematics=str(meta["kinematics"]),
            origin=str(meta["origin"]),
            cli_binary=resolve_cli_binary(pid, meta.get("binary_path")),
            machine_profile=MACHINES_DIR / f"{pid}.json",
            diameter_mm=float(meta["diameter_mm"]) if "diameter_mm" in meta else None,
            height_mm=height,
            bed_mm=bed_tuple,
            usable_edge_z_mm=(
                float(meta["usable_edge_z_mm"]) if "usable_edge_z_mm" in meta else None
            ),
            max_volumetric_flow_mm3_s=float(meta["max_volumetric_flow_mm3_s"]),
            extruder_slots=4 if pid == "creator5_pro" else 1,
        )
    return registry


PRINTER_REGISTRY: dict[str, PrinterConfig] = build_printer_registry()
TEMP_DIR.mkdir(parents=True, exist_ok=True)
MESH_CACHE_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_PRINTERS_CONFIG: dict[str, dict[str, Any]] = {
    "flsun_t1_pro_1": {
        "id": "flsun_t1_pro_1",
        "name": "FLSUN T1 Pro #1",
        "profile_id": "flsun_t1_pro",
        "protocol": "moonraker",
        "ip": "192.168.40.39",
        "fallback_ips": ["192.168.40.39"],
        "port": 80,
        "http_port": 8080,
        "access_code": "",
        "serial_number": "",
        "serial_port": "",
        "baudrate": 115200,
        "sd_volume_path": "",
        "camera_url": "http://192.168.40.39/webcam/?action=stream",
        "enabled": True,
    },
    "flsun_t1_pro_2": {
        "id": "flsun_t1_pro_2",
        "name": "FLSUN T1 Pro #2",
        "profile_id": "flsun_t1_pro",
        "protocol": "moonraker",
        "ip": "192.168.40.40",
        "fallback_ips": ["192.168.40.40"],
        "port": 80,
        "http_port": 8080,
        "access_code": "",
        "serial_number": "",
        "serial_port": "",
        "baudrate": 115200,
        "sd_volume_path": "",
        "camera_url": "http://192.168.40.40/webcam/?action=stream",
        "enabled": True,
    },
    "creator5_pro_1": {
        "id": "creator5_pro_1",
        "name": "FlashForge Creator 5 Pro",
        "profile_id": "creator5_pro",
        "protocol": "flashforge_lan",
        "ip": "192.168.40.41",
        "fallback_ips": ["192.168.40.41", "192.168.40.202"],
        "port": 8899,
        "http_port": 8080,
        "access_code": "97lu7sgv",
        "serial_number": "SNMVMF9706239",
        "serial_port": "",
        "baudrate": 115200,
        "sd_volume_path": "",
        "camera_url": "http://192.168.40.41:8080/?action=stream",
        "enabled": True,
    },
    "flsun_v400_1": {
        "id": "flsun_v400_1",
        "name": "FLSUN V400",
        "profile_id": "flsun_v400",
        "protocol": "moonraker",
        "ip": "192.168.40.42",
        "fallback_ips": ["192.168.40.42"],
        "port": 80,
        "http_port": 8080,
        "access_code": "",
        "serial_number": "",
        "serial_port": "",
        "baudrate": 115200,
        "sd_volume_path": "",
        "camera_url": "http://192.168.40.42/webcam/?action=stream",
        "enabled": True,
    },
    "flsun_sr_1": {
        "id": "flsun_sr_1",
        "name": "FLSUN Super Racer",
        "profile_id": "flsun_sr",
        "protocol": "marlin_serial",
        "ip": "",
        "fallback_ips": [],
        "port": 7125,
        "http_port": 8080,
        "access_code": "",
        "serial_number": "",
        "serial_port": "/dev/cu.usbserial-1420",
        "baudrate": 115200,
        "sd_volume_path": "",
        "camera_url": "",
        "enabled": True,
    },
    "ender3_s1_pro_1": {
        "id": "ender3_s1_pro_1",
        "name": "Creality Ender 3 S1 Pro",
        "profile_id": "ender3_s1_pro",
        "protocol": "marlin_serial",
        "ip": "",
        "fallback_ips": [],
        "port": 7125,
        "http_port": 8080,
        "access_code": "",
        "serial_number": "",
        "serial_port": "/dev/cu.usbserial-1410",
        "baudrate": 115200,
        "sd_volume_path": "",
        "camera_url": "",
        "enabled": True,
    },
}


def _infer_profile_id(instance_id: str, cfg: dict[str, Any]) -> str:
    raw_profile = str(cfg.get("profile_id") or "").strip()
    if raw_profile in PRINTER_REGISTRY:
        return raw_profile
    if instance_id in PRINTER_REGISTRY:
        return instance_id
    for base_pid in PRINTER_REGISTRY:
        if instance_id.startswith(f"{base_pid}_"):
            return base_pid
    proto = str(cfg.get("protocol") or "").strip()
    if proto == "flashforge_lan":
        return "creator5_pro"
    if proto == "marlin_serial":
        return "ender3_s1_pro"
    return "flsun_t1_pro"


def _normalize_printer_entry(instance_id: str, cfg: dict[str, Any]) -> dict[str, Any]:
    profile_id = _infer_profile_id(instance_id, cfg)
    default_proto, default_port = PROFILE_PROTOCOL_DEFAULTS.get(
        profile_id, ("moonraker", 7125)
    )
    protocol = str(cfg.get("protocol") or default_proto)
    if protocol not in ("moonraker", "flashforge_lan", "marlin_serial"):
        protocol = default_proto

    name = str(cfg.get("name") or "").strip()
    if not name:
        name = DISPLAY_NAMES.get(profile_id, instance_id)

    ip = str(cfg.get("ip") or "").strip()
    port = int(cfg.get("port") or default_port)
    camera_url = str(cfg.get("camera_url") or "").strip()
    if not camera_url and ip:
        if protocol == "moonraker":
            camera_url = f"http://{ip}/webcam/?action=stream"
        elif protocol == "flashforge_lan":
            camera_url = f"http://{ip}:8080/?action=stream"

    raw_fallbacks = cfg.get("fallback_ips") or []
    fallback_ips = [
        str(x).strip()
        for x in raw_fallbacks
        if isinstance(x, str) and str(x).strip()
    ]

    return {
        "id": instance_id,
        "name": name,
        "profile_id": profile_id,
        "protocol": protocol,
        "ip": ip,
        "fallback_ips": fallback_ips,
        "port": port,
        "http_port": int(cfg.get("http_port") or 8080),
        "access_code": str(cfg.get("access_code") or "").strip(),
        "serial_number": str(cfg.get("serial_number") or "").strip(),
        "serial_port": str(cfg.get("serial_port") or "").strip(),
        "baudrate": int(cfg.get("baudrate") or 115200),
        "sd_volume_path": str(cfg.get("sd_volume_path") or "").strip(),
        "camera_url": camera_url,
        "enabled": bool(cfg.get("enabled", True)),
    }


def load_printers_config() -> dict[str, dict[str, Any]]:
    """Carga todas las instancias de impresoras configuradas desde `printers_config.json`."""
    if PRINTERS_CONFIG_PATH.is_file():
        with PRINTERS_CONFIG_PATH.open("r", encoding="utf-8") as fh:
            stored = json.load(fh)
        if isinstance(stored, dict) and stored:
            # Migrar automáticamente formato antiguo (5 claves sin `profile_id` ni `flsun_t1_pro_1`)
            is_legacy = all(k in PRINTER_REGISTRY and not isinstance(v.get("profile_id"), str) for k, v in stored.items() if isinstance(v, dict))
            if not is_legacy:
                normalized: dict[str, dict[str, Any]] = {}
                for pid, cfg in stored.items():
                    if isinstance(cfg, dict):
                        normalized[str(pid)] = _normalize_printer_entry(str(pid), cfg)
                if normalized:
                    return normalized

    return {
        pid: dict(defaults) for pid, defaults in DEFAULT_PRINTERS_CONFIG.items()
    }


def save_printers_config(data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Persiste la granja multi-impresora (creación, edición o eliminación) en JSON."""
    normalized: dict[str, dict[str, Any]] = {}
    for pid, entry in data.items():
        clean_id = str(pid).strip()
        if not clean_id or not isinstance(entry, dict):
            continue
        normalized[clean_id] = _normalize_printer_entry(clean_id, entry)

    if not normalized:
        normalized = {
            pid: dict(defaults) for pid, defaults in DEFAULT_PRINTERS_CONFIG.items()
        }

    with PRINTERS_CONFIG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(normalized, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    return normalized


def update_printer_active_ip(
    printer_id: str,
    active_ip: str,
    active_port: int | None = None,
    active_camera_url: str | None = None,
    serial_number: str | None = None,
) -> None:
    """Actualiza y persiste IP/puerto/cámara/SN activos cuando responde una máquina o respaldo."""
    configs = load_printers_config()
    entry = configs.get(printer_id)
    if not entry:
        return
    changed = False
    if active_ip and entry.get("ip") != active_ip:
        old_ip = str(entry.get("ip") or "").strip()
        entry["ip"] = active_ip
        fallbacks = list(entry.get("fallback_ips") or [])
        if old_ip and old_ip not in fallbacks:
            fallbacks.insert(0, old_ip)
        if active_ip not in fallbacks:
            fallbacks.append(active_ip)
        entry["fallback_ips"] = fallbacks
        changed = True
    if active_port is not None and entry.get("port") != active_port:
        entry["port"] = active_port
        changed = True
    if active_camera_url is not None and entry.get("camera_url") != active_camera_url:
        entry["camera_url"] = active_camera_url
        changed = True
    if serial_number and entry.get("serial_number") != serial_number:
        entry["serial_number"] = serial_number
        changed = True
    if changed:
        save_printers_config(configs)


def resolve_profile_id(printer_id: str) -> str:
    """Resuelve el perfil técnico base (`flsun_t1_pro`, `creator5_pro`, etc.) de una instancia."""
    if printer_id in PRINTER_REGISTRY:
        return printer_id
    configs = load_printers_config()
    if printer_id in configs:
        profile = str(configs[printer_id].get("profile_id", ""))
        if profile in PRINTER_REGISTRY:
            return profile
    inferred = _infer_profile_id(printer_id, {})
    if inferred in PRINTER_REGISTRY and any(printer_id.startswith(f"{k}_") for k in PRINTER_REGISTRY):
        return inferred
    raise ValueError(f"Impresora o perfil desconocido: {printer_id}")


def get_printer_config(printer_id: str) -> PrinterConfig:
    """Obtiene el `PrinterConfig` técnico del perfil asociado a `printer_id`."""
    profile_id = resolve_profile_id(printer_id)
    return PRINTER_REGISTRY[profile_id]


def get_printer_instance(printer_id: str) -> tuple[str, dict[str, Any]]:
    """Retorna `(instance_id, cfg)` desde `printers_config.json` (soporta IDs heredados de perfil)."""
    configs = load_printers_config()
    if printer_id in configs:
        return printer_id, configs[printer_id]
    for inst_id, cfg in configs.items():
        if cfg.get("profile_id") == printer_id:
            return inst_id, cfg
    if printer_id in PRINTER_REGISTRY:
        return printer_id, _normalize_printer_entry(printer_id, {"profile_id": printer_id})
    raise ValueError(f"Instancia de impresora no encontrada: {printer_id}")


def detect_macos_serial_and_volumes() -> tuple[list[str], list[str]]:
    """Autodetecta puertos USB `/dev/cu.*` y volúmenes SD en `/Volumes/` en macOS."""
    dev_dir = Path("/dev")
    serial_ports: list[str] = []
    if dev_dir.is_dir():
        patterns = ("cu.usbserial*", "cu.usbmodem*", "cu.wchusbserial*")
        seen: set[str] = set()
        for pat in patterns:
            for item in sorted(dev_dir.glob(pat)):
                p_str = str(item)
                if p_str not in seen:
                    seen.add(p_str)
                    serial_ports.append(p_str)

    volumes_dir = Path("/Volumes")
    sd_volumes: list[str] = []
    if volumes_dir.is_dir():
        for entry in sorted(volumes_dir.iterdir()):
            if entry.name == "Macintosh HD" or entry.name.startswith("."):
                continue
            if entry.is_dir() and os.access(entry, os.W_OK):
                sd_volumes.append(str(entry))

    return serial_ports, sd_volumes


def _mask_secret(secret: str) -> str:
    clean = secret.strip()
    if not clean:
        return ""
    if len(clean) <= 8:
        return "*" * len(clean)
    return f"{clean[:4]}...{clean[-4:]}"


def get_masked_ai_keys() -> dict[str, Any]:
    """Retorna si hay API keys activas y su versión enmascarada sin exponer el secreto."""
    gemini = os.environ.get("GEMINI_API_KEY", "").strip()
    deepseek = os.environ.get("DEEPSEEK_API_KEY", DEFAULT_DEEPSEEK_API_KEY).strip()
    return {
        "has_gemini_key": bool(gemini),
        "has_deepseek_key": bool(deepseek),
        "gemini_key_masked": _mask_secret(gemini),
        "deepseek_key_masked": _mask_secret(deepseek),
    }


def save_ai_keys_to_env(
    gemini_api_key: str | None = None,
    deepseek_api_key: str | None = None,
) -> dict[str, Any]:
    """Guarda claves Gemini / DeepSeek en `backend/.env` y actualiza `os.environ`."""
    existing: dict[str, str] = {}
    if BACKEND_ENV_PATH.is_file():
        for raw in BACKEND_ENV_PATH.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            existing[k.strip()] = v.strip().strip('"').strip("'")

    if gemini_api_key is not None and gemini_api_key.strip():
        clean_g = gemini_api_key.strip()
        existing["GEMINI_API_KEY"] = clean_g
        os.environ["GEMINI_API_KEY"] = clean_g

    if deepseek_api_key is not None and deepseek_api_key.strip():
        clean_d = deepseek_api_key.strip()
        existing["DEEPSEEK_API_KEY"] = clean_d
        os.environ["DEEPSEEK_API_KEY"] = clean_d

    lines = ["# Claves de Copiloto IA para SlicerHub"]
    for k, v in existing.items():
        lines.append(f"{k}={v}")
    BACKEND_ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return get_masked_ai_keys()
