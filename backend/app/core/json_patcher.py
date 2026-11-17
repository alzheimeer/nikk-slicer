"""Parcheador dinámico de perfiles JSON maestros por trabajo de laminado."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import (
    DEFAULT_SUPPORT_Z_BY_MATERIAL,
    FILAMENTS_DIR,
    MATERIAL_TO_PROFILE,
    PRESET_TO_PROFILE,
    PROCESS_DIR,
    compute_default_support_xy,
    compute_heterogeneous_speed_cap,
    compute_lithophane_process_overrides,
    compute_optimal_temperatures,
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
    "enable_pressure_advance": ["0"],
    "pressure_advance": ["0.03"],
    "filament_retraction_length": ["0.6"],
    "filament_retraction_speed": ["35"],
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


def patch_profiles_for_job(
    request: SliceRequest,
    job_dir: Path,
    multimaterial_3mf: bool = False,
    safe_clean_base: bool = False,
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

        machine_data["extruder_colour"] = [s.color_hex for s in creator_slots]
        machine_data["idle_temperature"] = ["170"] * 4
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
            slot_data["idle_temperature"] = ["170"]
            slot_data["overhang_fan_speed"] = ["100"]
            if request.lithophane_mode:
                slot_data["fan_min_speed"] = ["85"]
                slot_data["fan_max_speed"] = ["100"]
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

            if slot_cfg.retraction_length is not None:
                slot_data["filament_retraction_length"] = [f"{slot_cfg.retraction_length:.2f}"]
            elif eff_slot_mat == "tpu":
                slot_data["filament_retraction_length"] = ["0.8"]

            if slot_cfg.retraction_speed is not None:
                slot_data["filament_retraction_speed"] = [f"{slot_cfg.retraction_speed:g}"]
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
        _apply_bed_temps(filament_data, request.bed_temp)

        volumetric_limit = (
            catalog.get(flow_table_key, {})
            .get(filament_key, {})
            .get(profile_id, printer.max_volumetric_flow_mm3_s)
        )
        filament_data["filament_max_volumetric_speed"] = [str(volumetric_limit)]
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
            process_data["prime_tower_width"] = "20"
            process_data["prime_volume"] = "10"
            process_data["prime_tower_brim_width"] = "3"

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

    if request.supports:
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
        process_data["support_type"] = request.support_type
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

    _validate_and_normalize_process_data(process_data)
    _save_json(dst_process, process_data)

    return PatchedProfileSet(
        job_dir=job_dir,
        machine_json=dst_machine,
        filament_json=filament_jsons[0],
        filament_jsons=filament_jsons,
        process_json=dst_process,
        filament_slots=slots,
    )
