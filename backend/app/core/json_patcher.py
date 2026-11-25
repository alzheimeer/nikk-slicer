"""Parcheador dinámico de perfiles JSON maestros por trabajo de laminado."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import (
    DEFAULT_SUPPORT_Z_BY_MATERIAL,
    FILAMENTS_DIR,
    MATERIAL_TO_PROFILE,
    PRESET_TO_PROFILE,
    PROCESS_DIR,
    clamp_speed_by_volumetric_flow,
    compute_default_support_xy,
    compute_heterogeneous_speed_cap,
    compute_lithophane_process_overrides,
    compute_optimal_temperatures,
    get_machine_thermal_kinematic_limits,
    get_optimal_chamber_config,
    get_printer_config,
    get_slot_volumetric_limit,
    load_catalog,
    negotiate_multimaterial_bed_temp,
)
from app.models.schemas import ExtruderSlotConfig, SliceRequest

LINE_WIDTH_SCALE_KEYS: dict[str, float] = {
    "line_width": 1.05,
    "outer_wall_line_width": 1.05,
    "inner_wall_line_width": 1.125,
    "initial_layer_line_width": 1.25,
    "internal_solid_infill_line_width": 1.05,
    "sparse_infill_line_width": 1.125,
    "top_surface_line_width": 1.05,
    "support_line_width": 1.0,
}

DEFAULT_SLOT_COLORS: tuple[str, str, str, str] = (
    "#22d3ee",
    "#f97316",
    "#22c55e",
    "#a855f7",
)

# Claves vectoriales que deben existir en los 4 JSONs de Creator 5 Pro para evitar
# `ConfigOptionVector::set_with_restore_2(): invalid size found` al mezclar PLA/PETG/ABS/TPU
CREATOR_UNIFORM_FILAMENT_DEFAULTS: dict[str, list[str]] = {
    "additional_cooling_fan_speed": ["70"],
    "enable_pressure_advance": ["1"],
    "pressure_advance": ["0.045"],
    "z_hop": ["0.2"],
    "z_hop_types": ["Slope Lift"],
    "wipe": ["1"],
    "wipe_distance": ["1.5"],
    "retract_before_wipe": ["70%"],
    "filament_retraction_length": ["1.2"],
    "filament_retraction_speed": ["40"],
    "filament_deretraction_speed": ["35"],
    "retraction_length_when_changing_material": ["1.6"],
    "support_material_interface_fan_speed": ["-1"],
}


@dataclass(frozen=True)
class PatchedProfileSet:
    """Rutas de perfiles clonados y parcheados dentro de `backend/temp/<job_id>/`."""

    job_dir: Path
    machine_json: Path
    filament_json: Path
    filament_jsons: list[Path]
    process_json: Path
    filament_slots: int
    volumetric_guard: dict[str, Any] | None = None


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


VALID_SUPPORT_TYPES: tuple[str, ...] = (
    "normal(auto)",
    "tree(auto)",
    "normal(manual)",
    "tree(manual)",
)
VALID_BRIM_TYPES: tuple[str, ...] = (
    "auto_brim",
    "brim_ears",
    "painted",
    "outer_only",
    "inner_only",
    "outer_and_inner",
    "no_brim",
)


def _save_json(path: Path, data: dict[str, Any]) -> None:
    """Escritura atómica de JSON (write + flush + os.fsync + os.replace)."""
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def _safe_float_str(
    raw: Any,
    default: float,
    min_val: float,
    max_val: float,
    decimals: int = 2,
) -> str:
    try:
        cleaned = str(raw).strip().rstrip("%")
        val = float(cleaned)
    except (TypeError, ValueError):
        val = default
    if not math.isfinite(val):
        val = default
    val = max(min_val, min(max_val, val))
    if decimals == 0:
        return str(int(round(val)))
    return f"{val:.{decimals}f}"


def _fmt(val: float, decimals: int = 2) -> str:
    """Formatea un float finito con `decimals` decimales (o entero si `decimals <= 0`)."""
    if not math.isfinite(val):
        val = 0.0
    if decimals <= 0:
        return str(int(round(val)))
    formatted = f"{val:.{decimals}f}"
    return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted


def _apply_ai_quality_overrides(
    process_data: dict[str, Any],
    machine_data: dict[str, Any],
    filament_jsons: list[Path],
    request: SliceRequest,
) -> None:
    """Inyecta parámetros reales seleccionados en el árbol de Análisis IA (quality_overrides)."""
    raw = {str(x).strip() for x in (getattr(request, "quality_overrides", None) or []) if str(x).strip()}
    if not raw:
        return
    if "full_character_polish" in raw:
        raw |= {"adaptive_layers", "dense_support_interface", "high_contrast_purge"}

    if "adaptive_layers" in raw:
        process_data["adaptive_layer_height"] = "1"
        machine_data["adaptive_layer_height"] = "1"
        if isinstance(machine_data.get("min_layer_height"), list) and machine_data["min_layer_height"]:
            machine_data["min_layer_height"] = ["0.10" for _ in machine_data["min_layer_height"]]
        if isinstance(machine_data.get("max_layer_height"), list) and machine_data["max_layer_height"]:
            machine_data["max_layer_height"] = ["0.24" for _ in machine_data["max_layer_height"]]

    if "dense_support_interface" in raw:
        process_data["support_interface_top_layers"] = "3"
        process_data["support_interface_pattern"] = "rectilinear"
        process_data["support_interface_spacing"] = "0.2"
        process_data["support_top_z_distance"] = "0.16"
        process_data["bridge_speed"] = "25"
        for f_path in filament_jsons:
            try:
                f_data = _load_json(f_path)
                f_data["overhang_fan_speed"] = ["85"]
                f_data["bridge_fan_speed"] = ["85"]
                _save_json(f_path, f_data)
            except Exception:
                pass

    if "high_contrast_purge" in raw:
        process_data["avoid_crossing_perimeters"] = "1"
        process_data["flush_multiplier"] = "1.35"


def _validate_and_normalize_process_data(process_data: dict[str, Any]) -> None:
    """Verifica tipos y rangos válidos del esquema Flash Studio / OrcaSlicer."""
    # Traducir/limpiar clave ajena `support_placement` si existiera en algún JSON legado
    legacy_placement = process_data.pop("support_placement", None)
    if legacy_placement is not None and "support_on_build_plate_only" not in process_data:
        process_data["support_on_build_plate_only"] = (
            "1" if str(legacy_placement).lower() in ("buildplate", "build_plate_only", "1", "true") else "0"
        )

    sup_type = str(process_data.get("support_type", "tree(auto)")).strip()
    if sup_type not in VALID_SUPPORT_TYPES:
        sup_type = "tree(auto)"
    process_data["support_type"] = sup_type

    plate_raw = str(process_data.get("support_on_build_plate_only", "0")).strip().lower()
    process_data["support_on_build_plate_only"] = "1" if plate_raw in ("1", "true", "yes") else "0"

    brim_type = str(process_data.get("brim_type", "no_brim")).strip()
    if brim_type not in VALID_BRIM_TYPES:
        brim_type = "no_brim"
    process_data["brim_type"] = brim_type

    process_data["brim_width"] = _safe_float_str(
        process_data.get("brim_width", "5"), default=5.0, min_val=0.0, max_val=100.0, decimals=0
    )
    process_data["support_top_z_distance"] = _safe_float_str(
        process_data.get("support_top_z_distance", "0.20"), default=0.20, min_val=0.0, max_val=2.0, decimals=2
    )
    process_data["support_bottom_z_distance"] = _safe_float_str(
        process_data.get("support_bottom_z_distance", process_data["support_top_z_distance"]),
        default=0.20,
        min_val=0.0,
        max_val=2.0,
        decimals=2,
    )
    process_data["support_object_xy_distance"] = _safe_float_str(
        process_data.get("support_object_xy_distance", "0.50"), default=0.50, min_val=0.0, max_val=10.0, decimals=2
    )
    process_data["support_interface_top_layers"] = _safe_float_str(
        process_data.get("support_interface_top_layers", "2"), default=2.0, min_val=0.0, max_val=10.0, decimals=0
    )
    process_data["support_interface_spacing"] = _safe_float_str(
        process_data.get("support_interface_spacing", "0.25"), default=0.25, min_val=0.0, max_val=5.0, decimals=2
    )


def _apply_bed_temps(filament_data: dict[str, Any], bed_temp: int) -> None:
    bed_str = [str(bed_temp)]
    for bed_key in (
        "hot_plate_temp",
        "hot_plate_temp_initial_layer",
        "textured_plate_temp",
        "textured_plate_temp_initial_layer",
        "eng_plate_temp",
        "eng_plate_temp_initial_layer",
        "cool_plate_temp",
        "cool_plate_temp_initial_layer",
    ):
        filament_data[bed_key] = bed_str


def _build_creator_slots(request: SliceRequest) -> list[ExtruderSlotConfig]:
    by_idx = {s.extruder_index: s for s in (request.extruders_config or [])}
    init_temp = request.nozzle_temp_initial_layer or request.nozzle_temp
    slots: list[ExtruderSlotConfig] = []
    for idx in range(4):
        if idx in by_idx:
            slots.append(by_idx[idx])
        else:
            slots.append(
                ExtruderSlotConfig(
                    extruder_index=idx,
                    material=request.material,
                    color_hex=DEFAULT_SLOT_COLORS[idx],
                    nozzle_temp=request.nozzle_temp,
                    nozzle_temp_initial_layer=init_temp,
                )
            )
    return slots


def _apply_first_layer_perfection(
    process_data: dict[str, Any],
    filament_jsons: list[Path],
    request: SliceRequest,
    profile_id: str,
    nozzle_d: float,
) -> None:
    """Inyecta parámetros globales de primera capa impecable (cero surcos, cicatrices ni esquinas abultadas)."""
    mat = "pla" if request.lithophane_mode else request.material
    is_petg = mat == "petg"
    is_bowden = profile_id == "flsun_sr"
    is_slow_bed = profile_id in ("ender3_s1_pro", "flsun_sr")

    init_lw = round(nozzle_d * 1.2, 2)  # 0.40 mm -> 0.48 mm
    init_flow = "0.95" if is_petg else "0.98"
    init_speed = "20" if is_slow_bed else ("25" if is_petg else "30")
    init_infill_speed = "35" if is_petg else "45"

    process_data["bottom_surface_pattern"] = "monotonic"
    process_data["initial_layer_line_width"] = f"{init_lw:.2f}"
    process_data["initial_layer_flow_ratio"] = init_flow
    process_data["elefant_foot_compensation"] = "0.15"
    process_data["initial_layer_speed"] = init_speed
    process_data["initial_layer_infill_speed"] = init_infill_speed
    process_data["initial_layer_travel_speed"] = "120"
    process_data["reduce_crossing_wall"] = "1"

    for f_idx, f_path in enumerate(filament_jsons):
        try:
            f_data = _load_json(f_path)
            slot_mat = (
                request.extruders_config[f_idx].material
                if (request.extruders_config and f_idx < len(request.extruders_config))
                else mat
            )
            slot_petg = slot_mat == "petg"
            slot_abs = slot_mat == "abs"

            f_data["z_hop"] = ["0.5" if slot_petg else "0.2"]
            f_data["z_hop_types"] = ["Slope Lift"]
            f_data["wipe"] = ["1"]
            f_data["wipe_distance"] = ["1.5"]
            f_data["retract_before_wipe"] = ["70%"]
            f_data["close_fan_the_first_layers"] = ["3" if (slot_petg or slot_abs) else "1"]
            f_data["enable_pressure_advance"] = ["1"]
            slot_cfg_ref = (
                request.extruders_config[f_idx]
                if (request.extruders_config and f_idx < len(request.extruders_config))
                else None
            )
            if slot_petg:
                pa_val = "0.075" if is_bowden else "0.045"
                if is_bowden:
                    f_data["filament_retraction_length"] = ["4.5"]
                    f_data["filament_retraction_speed"] = ["45"]
                else:
                    eff_ret_len = (
                        f"{slot_cfg_ref.retraction_length:.2f}"
                        if (slot_cfg_ref and slot_cfg_ref.retraction_length is not None)
                        else "0.7"
                    )
                    eff_ret_spd = (
                        f"{slot_cfg_ref.retraction_speed:g}"
                        if (slot_cfg_ref and slot_cfg_ref.retraction_speed is not None)
                        else "30"
                    )
                    f_data["filament_retraction_length"] = [eff_ret_len]
                    f_data["filament_retraction_speed"] = [eff_ret_spd]
                    f_data["filament_deretraction_speed"] = ["28"]
                    f_data["retraction_length_when_changing_material"] = ["1.4"]
            else:
                pa_val = "0.055" if is_bowden else "0.025"
            f_data["pressure_advance"] = [pa_val]
            _save_json(f_path, f_data)
        except Exception:
            pass


def _apply_anti_stringing_and_tower_positioning(
    process_data: dict[str, Any],
    filament_jsons: list[Path],
    request: SliceRequest,
    profile_id: str,
    *,
    is_multicolor: bool,
    model_dimensions_mm: tuple[float, float, float] | None,
) -> None:
    """Optimiza viajes rápidos, moderación térmica en PETG multicolor y posición cercana de torre de purga."""
    if profile_id in ("creator5_pro", "flsun_v400", "flsun_t1_pro"):
        process_data["travel_speed"] = "280"

    if is_multicolor:
        if str(process_data.get("enable_prime_tower", "0")) == "1":
            process_data["ooze_prevention"] = "1"
        process_data["flush_into_infill"] = "1"
        for f_idx, f_path in enumerate(filament_jsons):
            try:
                f_data = _load_json(f_path)
                slot_mat = (
                    request.extruders_config[f_idx].material
                    if (request.extruders_config and f_idx < len(request.extruders_config))
                    else request.material
                )
                if slot_mat == "petg":
                    raw_t = f_data.get("nozzle_temperature")
                    if isinstance(raw_t, list) and raw_t:
                        cur_t = int(float(raw_t[0]))
                        f_data["nozzle_temperature"] = [str(max(225, cur_t - 5))]
                        _save_json(f_path, f_data)
            except Exception:
                pass

    if process_data.get("enable_prime_tower") == "1":
        printer = get_printer_config(request.printer_id)
        dx = float(model_dimensions_mm[0]) if model_dimensions_mm else 80.0
        dy = float(model_dimensions_mm[1]) if model_dimensions_mm else 80.0
        tower_w = float(process_data.get("prime_tower_width", "45") or 45.0)
        if printer.origin == "center":
            max_r = (printer.diameter_mm or 260.0) / 2.0 - tower_w - 8.0
            cand_x = request.offset_x + dx / 2.0 + 20.0
            if abs(cand_x) > max_r:
                cand_x = request.offset_x - dx / 2.0 - 20.0 - tower_w
            cand_x = max(-max_r, min(max_r, cand_x))
            cand_y = max(-max_r * 0.6, min(max_r * 0.6, request.offset_y))
        else:
            bx, by, _ = printer.bed_mm or (256.0, 256.0, 256.0)
            cx, cy = bx / 2.0, by / 2.0
            cand_x = cx + request.offset_x + dx / 2.0 + 20.0
            if cand_x + tower_w > bx - 10.0:
                cand_x = cx + request.offset_x - dx / 2.0 - 20.0 - tower_w
            cand_x = max(12.0, min(bx - tower_w - 12.0, cand_x))
            cand_y = max(12.0, min(by - tower_w - 12.0, cy + request.offset_y))
        process_data["prime_tower_position_x"] = f"{cand_x:.1f}"
        process_data["prime_tower_position_y"] = f"{cand_y:.1f}"


def _apply_prime_tower_anti_detachment(
    process_data: dict[str, Any],
    machine_data: dict[str, Any],
    filament_jsons: list[Path],
    model_dimensions_mm: tuple[float, float, float] | None,
    *,
    is_multimaterial: bool,
) -> None:
    """Anclaje reforzado automático para evitar desprendimiento de la torre de purga en impresiones medianas/altas."""
    tower_active = str(process_data.get("enable_prime_tower", "0")) == "1"
    if not (tower_active or (is_multimaterial and tower_active)):
        return

    max_z_mm = (
        float(model_dimensions_mm[2])
        if (model_dimensions_mm and len(model_dimensions_mm) >= 3)
        else 0.0
    )

    # 1. Brim ancho obligatorio (12.0 mm base; 15.0 mm si altura Z > 80 mm)
    target_brim_w = 15.0 if max_z_mm > 80.0 else 12.0
    try:
        cur_brim_w = float(str(process_data.get("prime_tower_brim_width", "0")).strip() or "0")
    except ValueError:
        cur_brim_w = 0.0
    eff_brim_w = max(cur_brim_w, target_brim_w)
    process_data["prime_tower_brim_width"] = _fmt(eff_brim_w, 1)

    # 2. Huella amplia (>= 45 mm), cono estabilizador (15° si Z >= 60 mm) y costilla estructural (3.0 mm)
    try:
        cur_tower_w = float(str(process_data.get("prime_tower_width", "0")).strip() or "0")
    except ValueError:
        cur_tower_w = 0.0
    process_data["prime_tower_width"] = _fmt(max(cur_tower_w, 45.0), 1)

    if max_z_mm >= 60.0:
        try:
            cur_cone = float(str(process_data.get("wipe_tower_cone_angle", "0")).strip() or "0")
        except ValueError:
            cur_cone = 0.0
        process_data["wipe_tower_cone_angle"] = _fmt(max(cur_cone, 15.0), 0)

    process_data["wipe_tower_rib_width"] = "3.0"
    process_data["prime_tower_rib_width"] = "3.0"
    if "wipe_tower_bridging" not in process_data:
        process_data["wipe_tower_bridging"] = "10"
    process_data["wipe_tower_extra_flow"] = "105%"

    # 3. Primera capa lenta (<= 25 mm/s), flujo completo (100%-105%) y Z-hop >= 0.4 mm anti-golpes
    try:
        cur_init_spd = float(str(process_data.get("initial_layer_speed", "25")).strip() or "25")
    except ValueError:
        cur_init_spd = 25.0
    process_data["initial_layer_speed"] = _fmt(min(cur_init_spd, 25.0), 0)

    try:
        cur_init_flow = float(str(process_data.get("initial_layer_flow_ratio", "1.02")).strip() or "1.02")
    except ValueError:
        cur_init_flow = 1.02
    clamped_flow = max(1.00, min(1.05, cur_init_flow if cur_init_flow >= 1.0 else 1.02))
    process_data["initial_layer_flow_ratio"] = _fmt(clamped_flow, 2)
    try:
        cur_bot_flow = float(str(process_data.get("bottom_solid_infill_flow_ratio", "1.02")).strip() or "1.02")
    except ValueError:
        cur_bot_flow = 1.02
    if cur_bot_flow < 1.00:
        process_data["bottom_solid_infill_flow_ratio"] = _fmt(clamped_flow, 2)

    raw_mach_zhop = machine_data.get("z_hop")
    if isinstance(raw_mach_zhop, list) and raw_mach_zhop:
        new_mach_zhop: list[str] = []
        for zv in raw_mach_zhop:
            try:
                new_mach_zhop.append(_fmt(max(0.4, float(zv)), 2))
            except (TypeError, ValueError):
                new_mach_zhop.append("0.4")
        machine_data["z_hop"] = new_mach_zhop

    for f_path in filament_jsons:
        try:
            f_data = _load_json(f_path)
            raw_zhop = f_data.get("z_hop")
            if isinstance(raw_zhop, list) and raw_zhop:
                cur_zhop = max(float(raw_zhop[0]), 0.4)
                f_data["z_hop"] = [_fmt(cur_zhop, 2) for _ in raw_zhop]
            else:
                f_data["z_hop"] = ["0.4"]
            f_data["z_hop_types"] = ["Slope Lift"]
            _save_json(f_path, f_data)
        except Exception:
            pass


def patch_profiles_for_job(
    request: SliceRequest,
    job_dir: Path,
    multimaterial_3mf: bool = False,
    safe_clean_base: bool = False,
    is_multicolor: bool = False,
    model_dimensions_mm: tuple[float, float, float] | None = None,
) -> PatchedProfileSet:
    """Clona los JSON maestros en `job_dir` e inyecta boquilla, HS, temperaturas, soportes, balsa y T0..T3."""
    job_dir.mkdir(parents=True, exist_ok=True)
    printer = get_printer_config(request.printer_id)
    profile_id = printer.profile_id
    catalog = load_catalog()

    effective_material = "pla" if request.lithophane_mode else request.material
    filament_key = MATERIAL_TO_PROFILE[effective_material]
    process_key = PRESET_TO_PROFILE[request.quality_preset]

    src_machine = printer.machine_profile
    src_filament = FILAMENTS_DIR / f"{filament_key}.json"
    src_process = PROCESS_DIR / f"{process_key}.json"

    dst_machine = job_dir / f"machine_{profile_id}.json"
    dst_process = job_dir / f"process_{process_key}.json"

    # 1. Parchear máquina: diámetro de boquilla, límites físicos y multicabezal Creator 5 Pro
    machine_data = _load_json(src_machine)
    nozzle_d = round(float(request.nozzle_diameter), 2)
    max_lh_for_nozzle = round(nozzle_d * 0.75, 2)
    min_lh_for_nozzle = round(max(0.04, nozzle_d * 0.2), 2)
    slots = printer.extruder_slots

    machine_data["nozzle_diameter"] = [str(nozzle_d)] * slots
    machine_data["printer_variant"] = str(nozzle_d)
    machine_data["max_layer_height"] = [str(max_lh_for_nozzle)] * slots
    machine_data["min_layer_height"] = [str(min_lh_for_nozzle)] * slots

    # Adaptar geometría de cama, firmware y multicolor para impresoras personalizadas del catálogo OrcaSlicer
    if printer.printer_id != printer.profile_id:
        machine_data["printable_height"] = str(int(round(printer.height_mm)))
        if printer.gcode_flavor in ("klipper", "marlin2", "reprap"):
            machine_data["gcode_flavor"] = printer.gcode_flavor
        if printer.bed_shape == "circular" and printer.diameter_mm:
            r = printer.diameter_mm / 2.0
            pts = []
            for i in range(72):
                ang = (2.0 * math.pi * i) / 72.0
                pts.append(f"{r * math.cos(ang):.2f}x{r * math.sin(ang):.2f}")
            machine_data["printable_area"] = pts
        elif printer.bed_mm:
            bx, by, _ = printer.bed_mm
            machine_data["printable_area"] = ["0x0", f"{bx:.1f}x0", f"{bx:.1f}x{by:.1f}", f"0x{by:.1f}"]
        if printer.is_multicolor and slots > 1 and profile_id != "creator5_pro":
            # Solo activar single_extruder_multi_material si la máquina base no es multi-cabezal independiente
            if str(machine_data.get("single_extruder_multi_material", "0")) == "1":
                machine_data["single_extruder_multi_material"] = "1"

    flow_table_key = (
        "high_speed_volumetric_limits_mm3_s"
        if request.high_speed_filament
        else "volumetric_limits_mm3_s"
    )

    filament_jsons: list[Path] = []

    active_slot_indices: set[int] = {request.model_extruder}
    active_slot_flows: list[float] = []
    active_slot_mats: list[str] = []

    if profile_id == "creator5_pro":
        creator_slots = _build_creator_slots(request)
        if multimaterial_3mf:
            if request.part_extruder_map:
                active_slot_indices = {
                    max(0, min(3, int(ext) - 1)) for ext in request.part_extruder_map.values()
                }
            else:
                active_slot_indices = {0, 1, 2, 3}
        else:
            active_slot_indices = {request.model_extruder}
        if request.supports:
            active_slot_indices.add(request.support_extruder)
        for zr in request.z_color_ranges:
            active_slot_indices.add(zr.extruder_index)

        active_mats_all = [creator_slots[i].material for i in sorted(active_slot_indices)]
        distinct_body_mats = {m for m in active_mats_all if m != "soporte"}
        eff_bed_temp = (
            negotiate_multimaterial_bed_temp(active_mats_all)
            if len(distinct_body_mats) > 1
            else request.bed_temp
        )
        chamber_cfg = get_optimal_chamber_config(
            active_mats_all,
            override_temp=request.chamber_temp_target,
        )

        machine_data["extruder_colour"] = [s.color_hex for s in creator_slots]
        machine_data["idle_temperature"] = [
            "195" if (s.material == "petg" and not request.lithophane_mode) else "170"
            for s in creator_slots
        ]
        _save_json(dst_machine, machine_data)

        for idx, slot_cfg in enumerate(creator_slots):
            is_support_mat = slot_cfg.material == "soporte"
            eff_slot_mat = "pla" if (request.lithophane_mode or is_support_mat) else slot_cfg.material
            slot_mat_key = MATERIAL_TO_PROFILE[eff_slot_mat]
            slot_src = FILAMENTS_DIR / f"{slot_mat_key}.json"
            slot_data = _load_json(slot_src)

            slot_temps = compute_optimal_temperatures(
                request.printer_id,
                eff_slot_mat,
                spool_min=slot_cfg.spool_min,
                spool_max=slot_cfg.spool_max,
                high_speed=bool(slot_cfg.high_speed),
                nozzle_diameter=nozzle_d,
            )
            slot_lo = slot_cfg.spool_min if slot_cfg.spool_min is not None else slot_temps["spool_min"]
            slot_hi = slot_cfg.spool_max if slot_cfg.spool_max is not None else slot_temps["spool_max"]
            slot_print_temp = slot_cfg.nozzle_temp or slot_temps["nozzle_temp"]
            slot_init_temp = slot_cfg.nozzle_temp_initial_layer or slot_temps["nozzle_temp_initial_layer"]

            slot_name = f"SlicerHub {slot_cfg.material.upper()} T{idx}"
            slot_data["name"] = slot_name
            slot_data["filament_settings_id"] = [slot_name]
            slot_data["nozzle_temperature"] = [str(slot_print_temp)]
            slot_data["nozzle_temperature_initial_layer"] = [str(slot_init_temp)]
            slot_data["nozzle_temperature_range_low"] = [str(slot_lo)]
            slot_data["nozzle_temperature_range_high"] = [str(slot_hi)]
            slot_data["filament_colour"] = [slot_cfg.color_hex]
            slot_data["filament_type"] = [
                "PLA" if (request.lithophane_mode or is_support_mat) else slot_cfg.material.upper()
            ]
            slot_data["filament_is_support"] = ["1" if is_support_mat else "0"]
            slot_data["idle_temperature"] = ["195" if eff_slot_mat == "petg" else "170"]
            slot_data["activate_chamber_temp_control"] = ["1"]
            slot_data["chamber_temperature"] = [str(chamber_cfg["target_temp"])]
            if request.lithophane_mode:
                slot_data["fan_min_speed"] = ["85"]
                slot_data["fan_max_speed"] = ["100"]
                slot_data["overhang_fan_speed"] = ["100"]
            elif eff_slot_mat == "petg":
                slot_data["fan_min_speed"] = ["30"]
                slot_data["fan_max_speed"] = ["55"]
                slot_data["overhang_fan_speed"] = ["60"]
            elif eff_slot_mat == "abs":
                slot_data["fan_min_speed"] = ["15"]
                slot_data["fan_max_speed"] = ["30"]
                slot_data["overhang_fan_speed"] = ["40"]
            elif eff_slot_mat == "tpu":
                slot_data["fan_min_speed"] = ["40"]
                slot_data["fan_max_speed"] = ["60"]
                slot_data["overhang_fan_speed"] = ["70"]
            else:
                slot_data["fan_min_speed"] = ["70"]
                slot_data["fan_max_speed"] = ["100"]
                slot_data["overhang_fan_speed"] = ["100"]
            _apply_bed_temps(slot_data, eff_bed_temp)

            vol_lim = (
                float(slot_cfg.max_volumetric_speed)
                if slot_cfg.max_volumetric_speed is not None
                else get_slot_volumetric_limit(
                    request.printer_id,
                    eff_slot_mat,
                    high_speed=bool(slot_cfg.high_speed),
                )
            )
            slot_data["filament_max_volumetric_speed"] = [f"{vol_lim:g}"]

            if slot_cfg.flow_ratio is not None:
                slot_data["filament_flow_ratio"] = [f"{slot_cfg.flow_ratio:.2f}"]
            elif request.flow_ratio_override is not None:
                slot_data["filament_flow_ratio"] = [f"{request.flow_ratio_override:.2f}"]

            if slot_cfg.retraction_length is not None:
                slot_data["filament_retraction_length"] = [f"{slot_cfg.retraction_length:.2f}"]
            elif eff_slot_mat == "petg":
                slot_data["filament_retraction_length"] = ["0.7"]
            elif eff_slot_mat == "tpu":
                slot_data["filament_retraction_length"] = ["0.8"]

            if slot_cfg.retraction_speed is not None:
                slot_data["filament_retraction_speed"] = [f"{slot_cfg.retraction_speed:g}"]
            elif eff_slot_mat == "petg":
                slot_data["filament_retraction_speed"] = ["30"]
            elif eff_slot_mat == "tpu":
                slot_data["filament_retraction_speed"] = ["25"]

            if idx in active_slot_indices:
                active_slot_flows.append(vol_lim)
                active_slot_mats.append(eff_slot_mat)

            for u_key, u_val in CREATOR_UNIFORM_FILAMENT_DEFAULTS.items():
                slot_data.setdefault(u_key, list(u_val))

            dst_slot = job_dir / f"filament_slot_{idx}.json"
            _save_json(dst_slot, slot_data)
            filament_jsons.append(dst_slot)
    else:
        _save_json(dst_machine, machine_data)
        dst_filament = job_dir / f"filament_{filament_key}.json"
        filament_data = _load_json(src_filament)
        init_temp = request.nozzle_temp_initial_layer or request.nozzle_temp
        filament_data["nozzle_temperature_initial_layer"] = [str(init_temp)]
        filament_data["nozzle_temperature"] = [str(request.nozzle_temp)]
        filament_data["overhang_fan_speed"] = ["100"]
        if request.lithophane_mode:
            filament_data["fan_min_speed"] = ["85"]
            filament_data["fan_max_speed"] = ["100"]
        elif profile_id == "flsun_v400" and filament_key == "petg_master":
            # En V400 con PETG limitar ventilador de capa a 15-35% para garantizar fusión
            filament_data["fan_min_speed"] = ["15"]
            filament_data["fan_max_speed"] = ["35"]
        _apply_bed_temps(filament_data, request.bed_temp)

        volumetric_limit = (
            catalog.get(flow_table_key, {})
            .get(filament_key, {})
            .get(profile_id, printer.max_volumetric_flow_mm3_s)
        )
        filament_data["filament_max_volumetric_speed"] = [str(volumetric_limit)]
        if request.flow_ratio_override is not None:
            filament_data["filament_flow_ratio"] = [f"{request.flow_ratio_override:.2f}"]
        _save_json(dst_filament, filament_data)
        filament_jsons = [dst_filament] * slots

    # 3. Parchear proceso: anchos por boquilla, soportes avanzados, balsa y asignación T0..T3
    process_data = _load_json(src_process)
    for lw_key, factor in LINE_WIDTH_SCALE_KEYS.items():
        process_data[lw_key] = f"{nozzle_d * factor:.2f}"

    cur_lh = float(process_data.get("layer_height", "0.2"))
    cur_init_lh = float(process_data.get("initial_layer_print_height", "0.2"))
    if cur_lh > max_lh_for_nozzle:
        process_data["layer_height"] = f"{max_lh_for_nozzle:.2f}"
    if cur_init_lh > max_lh_for_nozzle:
        process_data["initial_layer_print_height"] = f"{max_lh_for_nozzle:.2f}"

    if profile_id == "creator5_pro":
        if multimaterial_3mf:
            # 0 = usar asignación individual por parte (--load-filament-ids) en Flash Studio
            process_data["wall_filament"] = "0"
            process_data["sparse_infill_filament"] = "0"
            process_data["solid_infill_filament"] = "0"
        else:
            model_fil = str(request.model_extruder + 1)
            process_data["wall_filament"] = model_fil
            process_data["sparse_infill_filament"] = model_fil
            process_data["solid_infill_filament"] = model_fil

        has_multi_sources = (
            multimaterial_3mf
            or (request.supports and request.support_extruder != request.model_extruder)
            or len(request.z_color_ranges) > 0
        )
        if request.enable_prime_tower is not None:
            use_tower = bool(request.enable_prime_tower)
        elif request.prime_tower_mode == "off":
            use_tower = False
        elif request.prime_tower_mode == "ultra_save":
            use_tower = has_multi_sources
        else:
            # Modo 'auto': desactivada por defecto en 4 cabezales independientes salvo contraste explícito
            use_tower = False

        process_data["enable_prime_tower"] = "1" if use_tower else "0"
        process_data["flush_into_infill"] = "1"
        process_data["flush_into_objects"] = "0"
        if use_tower:
            max_z_est = float(model_dimensions_mm[2]) if (model_dimensions_mm and len(model_dimensions_mm) >= 3) else 0.0
            process_data["prime_tower_width"] = "45"
            process_data["prime_volume"] = "15"
            process_data["prime_tower_brim_width"] = "15" if max_z_est > 80.0 else "12"

        sup_fil = str(request.support_extruder + 1)
        process_data["support_filament"] = sup_fil
        process_data["support_interface_filament"] = sup_fil

        # Limitar velocidades lineales si algún extrusor activo tiene caudal bajo (TPU o boquilla 0.2)
        if active_slot_flows and (
            any(m == "tpu" for m in active_slot_mats)
            or min(active_slot_flows) <= 13.0
            or nozzle_d <= 0.25
        ):
            speed_caps = compute_heterogeneous_speed_cap(
                active_slot_flows, active_slot_mats, nozzle_diameter=nozzle_d
            )
            for key, cap in (
                ("outer_wall_speed", speed_caps["outer_wall_cap"]),
                ("inner_wall_speed", speed_caps["inner_wall_cap"]),
                ("sparse_infill_speed", speed_caps["infill_cap"]),
                ("internal_solid_infill_speed", speed_caps["infill_cap"]),
                ("top_surface_speed", speed_caps["outer_wall_cap"]),
            ):
                cur_val = float(str(process_data.get(key, cap)).rstrip("%") or cap)
                process_data[key] = str(int(min(cur_val, cap)))

    paint_sources = list(getattr(request, "scene_objects", None) or []) or list(getattr(request, "instances", None) or [])
    has_paint_blockers = bool(getattr(request, "support_blockers", None)) or any(
        2 in (getattr(src, "support_paint_map", None) or {}).values()
        for src in paint_sources
    )
    has_paint_enforcers = any(
        1 in (getattr(src, "support_paint_map", None) or {}).values()
        for src in paint_sources
    )
    enforcers_only_sources = [
        src for src in paint_sources
        if getattr(src, "support_paint_mode", "auto") == "enforcers_only"
    ]
    all_enforcers_only = bool(enforcers_only_sources) and len(enforcers_only_sources) == len(paint_sources) and not has_paint_blockers

    if request.supports or has_paint_blockers or has_paint_enforcers:
        z_dist = (
            request.support_z_distance
            if request.support_z_distance is not None
            else DEFAULT_SUPPORT_Z_BY_MATERIAL.get(request.material, 0.20)
        )
        xy_dist = (
            request.support_xy_distance
            if request.support_xy_distance is not None
            else compute_default_support_xy(request.material, nozzle_d)
        )
        process_data["enable_support"] = "1"
        base_sup_type = request.support_type
        if all_enforcers_only:
            base_sup_type = "normal(manual)" if str(base_sup_type).startswith("normal") else "tree(manual)"
        process_data["support_type"] = base_sup_type
        if getattr(request, "support_style", None):
            process_data["support_style"] = str(request.support_style).strip() or "default"
        process_data["support_on_build_plate_only"] = (
            "1" if request.support_on_build_plate_only else "0"
        )
        process_data["support_top_z_distance"] = f"{z_dist:.2f}"
        process_data["support_bottom_z_distance"] = f"{z_dist:.2f}"
        process_data["support_object_xy_distance"] = f"{xy_dist:.2f}"
        process_data["support_interface_top_layers"] = "2"
        process_data["support_interface_spacing"] = "0.25"
    else:
        process_data["enable_support"] = "0"

    if request.adhesion_type == "raft":
        process_data["raft_layers"] = "2"
        process_data["raft_contact_distance"] = "0.18"
        process_data["brim_type"] = "no_brim"
    elif request.adhesion_type == "brim":
        bw = int(round(max(4.0, min(10.0, float(request.brim_width_mm)))))
        process_data["raft_layers"] = "0"
        process_data["brim_type"] = "outer_only"
        process_data["brim_width"] = str(bw)
        process_data["brim_object_gap"] = "0.12"
    else:
        process_data["raft_layers"] = "0"
        process_data["brim_type"] = "no_brim"

    if not safe_clean_base:
        # Optimización física de puentes (bridging) y voladizos para minimizar soportes
        process_data["bridge_speed"] = "25" if profile_id == "ender3_s1_pro" else "35"
        process_data["bridge_flow"] = "0.92"
        process_data["bridge_fan_speed"] = "100"
        process_data["thick_bridges"] = "1"
        process_data["bridge_no_support"] = "1"
        process_data["enable_overhang_speed"] = "1"
        process_data["overhang_1_4_speed"] = "100%"
        process_data["overhang_2_4_speed"] = "75%"
        process_data["overhang_3_4_speed"] = "50%"
        process_data["overhang_4_4_speed"] = "25%"

    if request.lithophane_mode:
        litho_overrides = compute_lithophane_process_overrides(
            profile_id=profile_id,
            high_speed=request.high_speed_filament,
            nozzle_diameter=nozzle_d,
            brim_width_mm=request.brim_width_mm,
        )
        process_data.update(litho_overrides)

    if request.layer_height_override is not None:
        lh_clamped = max(0.08, min(max_lh_for_nozzle, float(request.layer_height_override)))
        process_data["layer_height"] = f"{lh_clamped:.2f}"
    if request.outer_wall_speed_override is not None:
        process_data["outer_wall_speed"] = str(int(request.outer_wall_speed_override))
    if request.infill_density_override is not None:
        process_data["sparse_infill_density"] = f"{int(request.infill_density_override)}%"
        if int(request.infill_density_override) >= 98:
            process_data["sparse_infill_pattern"] = "rectilinear"
            process_data["wall_loops"] = "5"
    if request.ai_strategy_label and "estructural" in request.ai_strategy_label.lower():
        process_data["wall_loops"] = "4"
    if request.fuzzy_skin:
        process_data["fuzzy_skin"] = "outside"
        process_data["fuzzy_skin_first_layer"] = "0"
        process_data["fuzzy_skin_thickness"] = f"{float(request.fuzzy_skin_thickness):.2f}"
        process_data["fuzzy_skin_point_distance"] = f"{float(request.fuzzy_skin_point_distance):.2f}"

    # 4. Aceleraciones, blindaje en capas extremas y seguro matemático de caudal volumétrico
    machine_limits = get_machine_thermal_kinematic_limits(request.printer_id)
    default_accel = int(machine_limits["default_acceleration"])
    outer_accel = int(machine_limits["outer_wall_acceleration"])

    eff_lh = float(process_data.get("layer_height", "0.20") or 0.20)
    if eff_lh <= 0.12:
        # Capas ultra finas (0.08 / 0.12 mm): primera capa segura >= 0.16 mm y menor aceleración anti-ringing
        cur_init = float(process_data.get("initial_layer_print_height", "0.20") or 0.20)
        process_data["initial_layer_print_height"] = f"{max(0.16, min(0.20, cur_init)):.2f}"
        outer_accel = max(800, int(round(outer_accel * 0.65)))
    elif eff_lh >= 0.24 and nozzle_d <= 0.45:
        # Capas gruesas (0.24 / 0.28 mm): ancho 0.46-0.48 mm para mayor solapamiento
        thick_lw = 0.48 if eff_lh >= 0.27 else 0.46
        process_data["line_width"] = f"{thick_lw:.2f}"
        process_data["outer_wall_line_width"] = f"{thick_lw:.2f}"
        process_data["inner_wall_line_width"] = f"{thick_lw + 0.02:.2f}"

    process_data["default_acceleration"] = str(default_accel)
    process_data["outer_wall_acceleration"] = str(outer_accel)

    eff_lw = float(process_data.get("line_width", f"{nozzle_d * 1.05:.2f}") or (nozzle_d * 1.05))
    speed_keys = (
        "outer_wall_speed",
        "inner_wall_speed",
        "sparse_infill_speed",
        "internal_solid_infill_speed",
        "top_surface_speed",
    )
    requested_speeds: dict[str, float] = {}
    for sk in speed_keys:
        raw_sv = str(process_data.get(sk, "120")).strip().rstrip("%")
        try:
            requested_speeds[sk] = float(raw_sv)
        except ValueError:
            requested_speeds[sk] = 120.0

    flow_guard = clamp_speed_by_volumetric_flow(
        request.printer_id,
        "pla" if request.lithophane_mode else request.material,
        eff_lh,
        eff_lw,
        requested_speeds,
        high_speed=bool(request.high_speed_filament),
    )
    for sk, clamped_v in flow_guard["clamped_speeds"].items():
        process_data[sk] = str(clamped_v)

    temp_boost = int(flow_guard.get("temp_boost_c") or 0)
    if (temp_boost > 0 or (eff_lh >= 0.24 and profile_id in ("flsun_v400", "creator5_pro"))) and profile_id != "creator5_pro" and filament_jsons:
        try:
            f_data = _load_json(filament_jsons[0])
            if temp_boost > 0:
                cur_t = int(float(f_data.get("nozzle_temperature", [str(request.nozzle_temp)])[0]))
                cur_init_t = int(float(f_data.get("nozzle_temperature_initial_layer", [str(cur_t)])[0]))
                f_data["nozzle_temperature"] = [str(min(300, cur_t + temp_boost))]
                f_data["nozzle_temperature_initial_layer"] = [str(min(300, cur_init_t + temp_boost))]
            if eff_lh >= 0.24 and profile_id == "flsun_v400":
                if filament_key == "petg_master":
                    f_data["fan_min_speed"] = ["15"]
                    f_data["fan_max_speed"] = ["30"]
                elif filament_key == "pla_master":
                    f_data["fan_min_speed"] = ["65"]
                    f_data["fan_max_speed"] = ["80"]
            _save_json(filament_jsons[0], f_data)
        except Exception:
            pass

    if profile_id != "creator5_pro":
        if request.enable_prime_tower is True:
            process_data["enable_prime_tower"] = "1"
        elif request.enable_prime_tower is False:
            process_data["enable_prime_tower"] = "0"

    _apply_first_layer_perfection(
        process_data,
        filament_jsons,
        request,
        profile_id,
        nozzle_d,
    )
    _apply_anti_stringing_and_tower_positioning(
        process_data,
        filament_jsons,
        request,
        profile_id,
        is_multicolor=bool(is_multicolor or multimaterial_3mf),
        model_dimensions_mm=model_dimensions_mm,
    )
    _apply_prime_tower_anti_detachment(
        process_data,
        machine_data,
        filament_jsons,
        model_dimensions_mm,
        is_multimaterial=bool(
            is_multicolor
            or multimaterial_3mf
            or len(request.z_color_ranges) > 0
            or (request.supports and request.support_extruder != request.model_extruder)
        ),
    )
    _apply_ai_quality_overrides(process_data, machine_data, filament_jsons, request)
    _apply_profile_overrides(process_data, machine_data, filament_jsons, request)
    # Flash Studio / OrcaSlicer solo permite ooze_prevention=1 cuando single_extruder_multi_material=0 Y enable_prime_tower=1
    if not (
        str(machine_data.get("single_extruder_multi_material", "0")) == "0"
        and str(process_data.get("enable_prime_tower", "0")) == "1"
    ):
        process_data["ooze_prevention"] = "0"
    _validate_and_normalize_process_data(process_data)
    _save_json(dst_machine, machine_data)
    _save_json(dst_process, process_data)

    return PatchedProfileSet(
        job_dir=job_dir,
        machine_json=dst_machine,
        filament_json=filament_jsons[0],
        filament_jsons=filament_jsons,
        process_json=dst_process,
        filament_slots=slots,
        volumetric_guard=flow_guard,
    )


def _apply_profile_overrides(
    process_data: dict[str, Any],
    machine_data: dict[str, Any],
    filament_jsons: list[Path],
    request: SliceRequest,
) -> None:
    """Aplica ediciones directas del Inspector Lateral de Perfil (`profile_overrides`)."""
    ov = getattr(request, "profile_overrides", None)
    if not isinstance(ov, dict) or not ov:
        return

    process_key_map = {
        "layer_height": ("layer_height", "float"),
        "initial_layer_height": ("initial_layer_print_height", "float"),
        "line_width": ("line_width", "float"),
        "outer_wall_line_width": ("outer_wall_line_width", "float"),
        "inner_wall_line_width": ("inner_wall_line_width", "float"),
        "top_surface_line_width": ("top_surface_line_width", "float"),
        "infill_line_width": ("internal_solid_infill_line_width", "float"),
        "support_line_width": ("support_line_width", "float"),
        "wall_generator": ("wall_generator", "str"),
        "seam_position": ("seam_position", "str"),
        "ironing_type": ("ironing_type", "str"),
        "top_surface_pattern": ("top_surface_pattern", "str"),
        "wall_loops": ("wall_loops", "int"),
        "top_shell_layers": ("top_shell_layers", "int"),
        "bottom_shell_layers": ("bottom_shell_layers", "int"),
        "sparse_infill_density": ("sparse_infill_density", "pct"),
        "sparse_infill_pattern": ("sparse_infill_pattern", "str"),
        "infill_wall_overlap": ("infill_wall_overlap", "pct"),
        "outer_wall_speed": ("outer_wall_speed", "float"),
        "inner_wall_speed": ("inner_wall_speed", "float"),
        "initial_layer_speed": ("initial_layer_speed", "float"),
        "sparse_infill_speed": ("sparse_infill_speed", "float"),
        "top_surface_speed": ("top_surface_speed", "float"),
        "overhang_speed": ("overhang_2_4_speed", "float"),
        "bridge_speed": ("bridge_speed", "float"),
        "travel_speed": ("travel_speed", "float"),
        "acceleration_print": ("default_acceleration", "float"),
        "enable_support": ("enable_support", "bool"),
        "support_type": ("support_type", "str"),
        "support_style": ("support_style", "str"),
        "support_threshold_angle": ("support_threshold_angle", "float"),
        "support_top_z_distance": ("support_top_z_distance", "float"),
        "support_bottom_z_distance": ("support_bottom_z_distance", "float"),
        "support_object_xy_distance": ("support_object_xy_distance", "float"),
        "support_interface_top_layers": ("support_interface_top_layers", "int"),
        "support_interface_bottom_layers": ("support_interface_bottom_layers", "int"),
        "support_interface_spacing": ("support_interface_spacing", "float"),
        "support_interface_pattern": ("support_interface_pattern", "str"),
        "enable_prime_tower": ("enable_prime_tower", "bool"),
        "prime_tower_width": ("prime_tower_width", "float"),
        "prime_tower_brim_width": ("prime_tower_brim_width", "float"),
        "wipe_tower_cone_angle": ("wipe_tower_cone_angle", "float"),
        "prime_tower_rib_width": ("wipe_tower_rib_width", "float"),
        "wipe_tower_rib_width": ("wipe_tower_rib_width", "float"),
        "support_interface_filament": ("support_interface_filament", "int"),
        "brim_type": ("brim_type", "str"),
        "brim_width": ("brim_width", "float"),
        "skirt_loops": ("skirt_loops", "int"),
    }

    for k, raw_val in ov.items():
        if k == "filaments" or raw_val is None:
            continue
        spec = process_key_map.get(k)
        if not spec:
            continue
        target_key, kind = spec
        try:
            if kind == "bool":
                process_data[target_key] = "1" if bool(raw_val) and str(raw_val).lower() not in ("0", "false") else "0"
            elif kind == "int":
                process_data[target_key] = str(int(round(float(raw_val))))
            elif kind == "float":
                process_data[target_key] = _fmt(float(raw_val), 2)
            elif kind == "pct":
                s = str(raw_val).strip()
                process_data[target_key] = s if s.endswith("%") else f"{_fmt(float(s), 0)}%"
            else:
                process_data[target_key] = str(raw_val)
        except Exception:
            continue

    fil_overrides = ov.get("filaments")
    if isinstance(fil_overrides, list):
        for idx, item in enumerate(fil_overrides):
            if not isinstance(item, dict) or idx >= len(filament_jsons):
                continue
            fpath = filament_jsons[idx]
            try:
                fdata = _load_json(fpath)
            except Exception:
                continue
            fil_map = {
                "nozzle_temp_initial": "nozzle_temperature_initial_layer",
                "nozzle_temp": "nozzle_temperature",
                "bed_temp_initial": "hot_plate_temp_initial_layer",
                "bed_temp": "hot_plate_temp",
                "fan_min_speed": "fan_min_speed",
                "fan_max_speed": "fan_max_speed",
                "overhang_fan_speed": "overhang_fan_speed",
                "retraction_length": "filament_retraction_length",
                "retraction_speed": "filament_retraction_speed",
                "z_hop": "z_hop",
                "flow_ratio": "filament_flow_ratio",
                "max_volumetric_flow": "filament_max_volumetric_speed",
                "density_g_cm3": "filament_density",
            }
            changed = False
            for src_k, dst_k in fil_map.items():
                if src_k in item and item[src_k] is not None:
                    try:
                        val_str = _fmt(float(item[src_k]), 2)
                        if isinstance(fdata.get(dst_k), list):
                            fdata[dst_k] = [val_str]
                        else:
                            fdata[dst_k] = [val_str] if dst_k in ("nozzle_temperature", "nozzle_temperature_initial_layer", "hot_plate_temp", "hot_plate_temp_initial_layer", "fan_min_speed", "fan_max_speed", "overhang_fan_speed", "filament_retraction_length", "filament_retraction_speed", "z_hop", "filament_flow_ratio", "filament_max_volumetric_speed", "filament_density") else val_str
                        changed = True
                    except Exception:
                        continue
            if changed:
                _save_json(fpath, fdata)


def _as_float(val: Any, default: float = 0.0) -> float:
    if isinstance(val, list) and val:
        val = val[0]
    try:
        s = str(val).replace("%", "").strip()
        return round(float(s), 3)
    except Exception:
        return default


def _as_int(val: Any, default: int = 0) -> int:
    return int(round(_as_float(val, float(default))))


def _as_str(val: Any, default: str = "") -> str:
    if isinstance(val, list) and val:
        val = val[0]
    if val is None:
        return default
    return str(val)


def build_sliced_profile_snapshot(
    *,
    patched: PatchedProfileSet,
    request: SliceRequest,
    printer_name: str,
    slicer_engine: str,
    gcode_filename: str = "",
    applied_pauses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Construye la instantánea completa de 7 secciones del perfil efectivo usado en el corte."""
    proc = _load_json(patched.process_json) if patched.process_json.is_file() else {}
    mach = _load_json(patched.machine_json) if patched.machine_json.is_file() else {}

    active_tools: list[str] = []
    filaments_out: list[dict[str, Any]] = []
    slots = list(request.extruders_config or [])

    for idx, fpath in enumerate(patched.filament_jsons):
        fdata = _load_json(fpath) if fpath.is_file() else {}
        slot_cfg = slots[idx] if idx < len(slots) else None
        slot_idx = slot_cfg.extruder_index if slot_cfg else idx
        slot_name = f"T{slot_idx}"
        active_tools.append(slot_name)
        mat = (slot_cfg.material if slot_cfg else request.material).upper()
        color_hex = slot_cfg.color_hex if slot_cfg else "#38BDF8"
        brand_or_name = _as_str(fdata.get("name"), f"{mat} {slot_name}")

        filaments_out.append(
            {
                "slot": slot_name,
                "material": mat,
                "brand_or_name": brand_or_name,
                "color_hex": color_hex,
                "nozzle_temp_initial": _as_float(fdata.get("nozzle_temperature_initial_layer"), 215.0),
                "nozzle_temp": _as_float(fdata.get("nozzle_temperature"), 215.0),
                "bed_temp_initial": _as_float(fdata.get("hot_plate_temp_initial_layer") or fdata.get("textured_plate_temp_initial_layer"), 60.0),
                "bed_temp": _as_float(fdata.get("hot_plate_temp") or fdata.get("textured_plate_temp"), 60.0),
                "fan_min_speed": _as_float(fdata.get("fan_min_speed"), 35.0),
                "fan_max_speed": _as_float(fdata.get("fan_max_speed"), 100.0),
                "overhang_fan_speed": _as_float(fdata.get("overhang_fan_speed"), 100.0),
                "retraction_length": _as_float(fdata.get("retraction_length") or mach.get("retraction_length"), 0.8),
                "retraction_speed": _as_float(fdata.get("retraction_speed") or mach.get("retraction_speed"), 40.0),
                "max_volumetric_flow": _as_float(fdata.get("filament_max_volumetric_speed"), 18.0),
                "density_g_cm3": _as_float(fdata.get("filament_density"), 1.24),
                "cost_per_kg_cop": _as_float(fdata.get("filament_cost"), 85000.0),
            }
        )

    qmax = _as_float(
        (patched.volumetric_guard or {}).get("max_volumetric_speed_mm3_s")
        or (filaments_out[0]["max_volumetric_flow"] if filaments_out else 18.0),
        18.0,
    )

    per_object_support_overrides: list[dict[str, Any]] = []
    per_object_adhesion_overrides: list[dict[str, Any]] = []
    for idx_obj, sc_obj in enumerate(getattr(request, "scene_objects", None) or [], start=1):
        ov = getattr(sc_obj, "overrides", None)
        if ov is None:
            continue
        obj_name = str(getattr(sc_obj, "name", f"Pieza {idx_obj}"))
        if ov.enable_support != "inherit" or ov.support_type != "inherit":
            per_object_support_overrides.append(
                {
                    "name": obj_name,
                    "enable_support": ov.enable_support,
                    "support_type": ov.support_type,
                }
            )
        if ov.brim_type != "inherit":
            per_object_adhesion_overrides.append(
                {
                    "name": obj_name,
                    "brim_type": ov.brim_type,
                    "brim_width": float(ov.brim_width),
                    "raft_layers": int(ov.raft_layers),
                }
            )

    if not per_object_support_overrides and not per_object_adhesion_overrides:
        for idx_inst, inst in enumerate(getattr(request, "instances", None) or [], start=1):
            ov = getattr(inst, "overrides", None)
            if ov is None:
                continue
            inst_name = f"Pieza #{idx_inst}"
            if ov.enable_support != "inherit" or ov.support_type != "inherit":
                per_object_support_overrides.append(
                    {
                        "name": inst_name,
                        "enable_support": ov.enable_support,
                        "support_type": ov.support_type,
                    }
                )
            if ov.brim_type != "inherit":
                per_object_adhesion_overrides.append(
                    {
                        "name": inst_name,
                        "brim_type": ov.brim_type,
                        "brim_width": float(ov.brim_width),
                        "raft_layers": int(ov.raft_layers),
                    }
                )

    return {
        "quality": {
            "layer_height": _as_float(proc.get("layer_height"), 0.2),
            "initial_layer_height": _as_float(proc.get("initial_layer_print_height") or proc.get("initial_layer_height"), 0.2),
            "line_width": _as_float(proc.get("line_width"), 0.42),
            "outer_wall_line_width": _as_float(proc.get("outer_wall_line_width"), 0.42),
            "inner_wall_line_width": _as_float(proc.get("inner_wall_line_width"), 0.45),
            "top_surface_line_width": _as_float(proc.get("top_surface_line_width"), 0.42),
            "infill_line_width": _as_float(proc.get("internal_solid_infill_line_width") or proc.get("sparse_infill_line_width"), 0.45),
            "support_line_width": _as_float(proc.get("support_line_width"), 0.42),
            "wall_generator": _as_str(proc.get("wall_generator"), "arachne"),
            "seam_position": _as_str(proc.get("seam_position"), "aligned"),
            "ironing_type": _as_str(proc.get("ironing_type"), "no ironing"),
            "top_surface_pattern": _as_str(proc.get("top_surface_pattern"), "monotonicline"),
        },
        "strength": {
            "wall_loops": _as_int(proc.get("wall_loops"), 2),
            "top_shell_layers": _as_int(proc.get("top_shell_layers"), 4),
            "bottom_shell_layers": _as_int(proc.get("bottom_shell_layers"), 3),
            "sparse_infill_density": _as_str(proc.get("sparse_infill_density"), "15%"),
            "sparse_infill_pattern": _as_str(proc.get("sparse_infill_pattern"), "gyroid"),
            "infill_wall_overlap": _as_str(proc.get("infill_wall_overlap"), "25%"),
        },
        "speed": {
            "outer_wall_speed": _as_float(proc.get("outer_wall_speed"), 120.0),
            "inner_wall_speed": _as_float(proc.get("inner_wall_speed"), 180.0),
            "initial_layer_speed": _as_float(proc.get("initial_layer_speed"), 45.0),
            "sparse_infill_speed": _as_float(proc.get("sparse_infill_speed"), 200.0),
            "top_surface_speed": _as_float(proc.get("top_surface_speed"), 120.0),
            "overhang_speed": _as_float(proc.get("overhang_2_4_speed") or proc.get("overhang_speed"), 30.0),
            "overhang_1_4_speed": _as_float(proc.get("overhang_1_4_speed"), 60.0),
            "overhang_2_4_speed": _as_float(proc.get("overhang_2_4_speed"), 30.0),
            "overhang_3_4_speed": _as_float(proc.get("overhang_3_4_speed"), 20.0),
            "overhang_4_4_speed": _as_float(proc.get("overhang_4_4_speed"), 15.0),
            "bridge_speed": _as_float(proc.get("bridge_speed"), 35.0),
            "travel_speed": _as_float(proc.get("travel_speed"), 300.0),
            "max_volumetric_speed_qmax": qmax,
            "acceleration_print": _as_float(proc.get("default_acceleration"), 5000.0),
        },
        "support": {
            "enable_support": _as_str(proc.get("enable_support"), "0") == "1",
            "support_type": _as_str(proc.get("support_type"), "tree(auto)"),
            "support_style": _as_str(proc.get("support_style"), "default"),
            "support_threshold_angle": _as_float(proc.get("support_threshold_angle"), 30.0),
            "support_top_z_distance": _as_float(proc.get("support_top_z_distance"), 0.2),
            "support_bottom_z_distance": _as_float(proc.get("support_bottom_z_distance"), 0.2),
            "support_object_xy_distance": _as_float(proc.get("support_object_xy_distance"), 0.5),
            "support_interface_top_layers": _as_int(proc.get("support_interface_top_layers"), 2),
            "support_interface_bottom_layers": _as_int(proc.get("support_interface_bottom_layers"), 2),
            "support_interface_spacing": _as_float(proc.get("support_interface_spacing"), 0.5),
            "support_interface_pattern": _as_str(proc.get("support_interface_pattern"), "rectilinear"),
            "per_object_overrides": per_object_support_overrides,
        },
        "multimaterial": {
            "active_tools": active_tools,
            "tool_mapping": dict(request.part_extruder_map or {}),
            "enable_prime_tower": _as_str(proc.get("enable_prime_tower"), "0") == "1",
            "prime_tower_width": _as_float(proc.get("prime_tower_width"), 45.0),
            "prime_tower_brim_width": _as_float(proc.get("prime_tower_brim_width"), 12.0),
            "wipe_tower_cone_angle": _as_float(proc.get("wipe_tower_cone_angle"), 0.0),
            "prime_tower_rib_width": _as_float(proc.get("wipe_tower_rib_width") or proc.get("prime_tower_rib_width"), 3.0),
            "prime_tower_anti_detachment": _as_str(proc.get("enable_prime_tower"), "0") == "1",
            "flush_volumes": proc.get("flush_volumes_matrix") or proc.get("flush_multiplier") or "1.0",
            "support_interface_filament": _as_int(proc.get("support_interface_filament"), 0),
            "z_color_changes": [z.model_dump() for z in (request.z_color_ranges or [])],
        },
        "others": {
            "brim_type": _as_str(proc.get("brim_type"), "no_brim"),
            "brim_width": _as_float(proc.get("brim_width"), 5.0),
            "skirt_loops": _as_int(proc.get("skirt_loops"), 1),
            "layer_pauses": list(applied_pauses or []),
            "anti_stringing_active": any(f["retraction_length"] > 0 for f in filaments_out),
            "chamber_temp": _as_float(request.chamber_temp_target or mach.get("chamber_temperature"), 0.0),
            "bed_temp": filaments_out[0]["bed_temp"] if filaments_out else float(request.bed_temp),
            "gcode_filename": gcode_filename,
            "printer_name": printer_name,
            "slicer_engine": slicer_engine,
            "sliced_at_timestamp": datetime.now(timezone.utc).isoformat(),
            "per_object_overrides": per_object_adhesion_overrides,
        },
        "filaments": filaments_out,
    }


def inject_profile_snapshot_into_gcode(gcode_path: Path, snapshot: dict[str, Any]) -> None:
    """Inyecta `; NIKK_SLICER_PROFILE_JSON: {...}` al final del .gcode para trazabilidad portátil."""
    if not gcode_path.is_file():
        return
    compact = json.dumps(snapshot, separators=(",", ":"), ensure_ascii=False)
    marker_line = f"; NIKK_SLICER_PROFILE_JSON: {compact}"
    raw_lines = gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    filtered = [ln for ln in raw_lines if not ln.lstrip().startswith("; NIKK_SLICER_PROFILE_JSON:")]
    filtered.append(marker_line)
    tmp_path = gcode_path.with_suffix(".gcode.tmp")
    tmp_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
    os.replace(tmp_path, gcode_path)
