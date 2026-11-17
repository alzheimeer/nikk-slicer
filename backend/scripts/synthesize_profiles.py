#!/usr/bin/env python3
"""Sintetizador y aplanador de perfiles maestros para SlicerHub (Fase 0).

Resuelve cadenas de herencia JSON (`inherits` / `from`) desde los repositorios
clonados en `repos_referencia/` y los perfiles nativos de los binarios
instalados en macOS, produciendo archivos planos autocontenidos en
`backend/profiles/{machines,filaments,process}/` sin claves ajenas al esquema C++.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOS_DIR = PROJECT_ROOT / "repos_referencia"
PROFILES_OUT = PROJECT_ROOT / "backend" / "profiles"

FLSUN_BUNDLE = REPOS_DIR / "local_bundle_profiles" / "FlsunSlicer" / "FLSun"
FLASH_BUNDLE = REPOS_DIR / "local_bundle_profiles" / "FlashStudio"
ORCA_PROFILES = REPOS_DIR / "OrcaSlicer" / "resources" / "profiles"

MACHINE_NAMES = [
    "SlicerHub FLSUN V400 0.4 nozzle",
    "SlicerHub FLSUN T1 Pro 0.4 nozzle",
    "SlicerHub FLSUN Super Racer 0.4 nozzle",
    "SlicerHub FlashForge Creator 5 Pro 0.4 nozzle",
    "SlicerHub Creality Ender 3 S1 Pro 0.4 nozzle",
]


def load_json(path: Path) -> dict[str, Any]:
    """Carga un archivo JSON desde disco."""
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Guarda un diccionario como JSON formateado."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def build_registry(directories: list[Path]) -> dict[tuple[str, str], dict[str, Any]]:
    """Indexa perfiles JSON por `(type, name)` respetando el orden de prioridad."""
    registry: dict[tuple[str, str], dict[str, Any]] = {}
    for directory in directories:
        if not directory.exists():
            continue
        for json_path in sorted(directory.rglob("*.json")):
            try:
                payload = load_json(json_path)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            name = payload.get("name")
            ptype = payload.get("type")
            if not isinstance(ptype, str):
                parent_folder = json_path.parent.name.lower()
                if parent_folder in {"machine", "filament", "process"}:
                    ptype = parent_folder
                elif json_path.parent.parent.name.lower() in {"machine", "filament", "process"}:
                    ptype = json_path.parent.parent.name.lower()
            if isinstance(name, str) and isinstance(ptype, str):
                registry[(ptype, name)] = payload
    return registry


def resolve_inheritance(
    registry: dict[tuple[str, str], dict[str, Any]],
    ptype: str,
    name: str,
    visited: set[str] | None = None,
) -> dict[str, Any]:
    """Resuelve recursivamente `inherits` fusionando padre -> hijo."""
    if visited is None:
        visited = set()
    if name in visited:
        raise ValueError(f"Ciclo de herencia detectado para ({ptype}, {name})")
    if (ptype, name) not in registry:
        raise KeyError(f"Perfil no encontrado en registro: ({ptype}, {name})")

    visited.add(name)
    node = copy.deepcopy(registry[(ptype, name)])
    parent_name = node.get("inherits")
    if isinstance(parent_name, str) and parent_name.strip():
        merged = resolve_inheritance(registry, ptype, parent_name.strip(), visited)
        merged.update(node)
    else:
        merged = node

    merged.pop("inherits", None)
    merged.pop("z_lift_type", None)
    merged.pop("chamber_temperatures", None)
    merged["instantiation"] = "true"
    merged["from"] = "system"
    return {
        k: v
        for k, v in merged.items()
        if v != "nil" and not (isinstance(v, list) and v == ["nil"])
    }


def circular_bed_polygon(radius: float, segments: int = 72) -> list[str]:
    """Genera un polígono circular centrado en (0, 0) compatible con Klipper/Orca."""
    pts: list[str] = []
    for i in range(segments):
        angle = 2.0 * math.pi * (i + 1) / segments
        x = radius * math.cos(angle)
        y = radius * math.sin(angle)
        pts.append(f"{round(x, 4)}x{round(y, 4)}")
    return pts


def synthesize_machines() -> dict[str, dict[str, Any]]:
    """Sintetiza y optimiza los 5 perfiles maestros de impresoras."""
    flsun_reg = build_registry([FLSUN_BUNDLE / "machine"])
    flash_reg = build_registry([FLASH_BUNDLE / "Flashforge" / "machine"])
    creality_reg = build_registry(
        [
            ORCA_PROFILES / "Creality" / "machine",
            ORCA_PROFILES,
        ]
    )

    machines: dict[str, dict[str, Any]] = {}

    # 1. FLSUN V400 (Delta Klipper, Ø300x410 mm, flujo máx 36-38 mm³/s)
    v400 = resolve_inheritance(flsun_reg, "machine", "FLSun V400 0.4 nozzle")
    v400.update(
        {
            "type": "machine",
            "name": "SlicerHub FLSUN V400 0.4 nozzle",
            "printer_model": "FLSun V400",
            "printer_settings_id": "SlicerHub FLSUN V400 0.4 nozzle",
            "printer_structure": "delta",
            "gcode_flavor": "klipper",
            "nozzle_diameter": ["0.4"],
            "nozzle_type": "brass",
            "printable_area": circular_bed_polygon(150.0, 72),
            "printable_height": "410",
            "bed_exclude_area": ["0x0"],
            "machine_max_speed_x": ["400", "400"],
            "machine_max_speed_y": ["400", "400"],
            "machine_max_speed_z": ["20", "20"],
            "machine_max_speed_e": ["60", "60"],
            "machine_max_acceleration_x": ["9000", "9000"],
            "machine_max_acceleration_y": ["9000", "9000"],
            "machine_max_acceleration_extruding": ["9000", "9000"],
            "machine_max_acceleration_travel": ["9000", "9000"],
            "machine_max_acceleration_retracting": ["5000", "5000"],
            "machine_max_acceleration_e": ["5000", "5000"],
            "machine_max_acceleration_z": ["500", "500"],
            "machine_max_jerk_x": ["9", "9"],
            "machine_max_jerk_y": ["9", "9"],
            "machine_max_jerk_z": ["0.4", "0.4"],
            "machine_max_jerk_e": ["2.5", "2.5"],
            "retraction_length": ["0.8"],
            "retraction_speed": ["45"],
            "deretraction_speed": ["45"],
            "z_hop": ["0.4"],
            "z_hop_types": ["Slope Lift"],
            "travel_slope": ["3"],
            "adaptive_bed_mesh_margin": "0",
            "auxiliary_fan": "0",
            "emit_machine_limits_to_gcode": "1",
            "use_relative_e_distances": "0",
            "before_layer_change_gcode": ";BEFORE_LAYER_CHANGE\n;[layer_z]\n",
            "layer_change_gcode": ";AFTER_LAYER_CHANGE\n;[layer_z]\n",
            "default_filament_profile": ["SlicerHub PLA Master"],
            "default_print_profile": "SlicerHub Estandar 0.20mm",
            "machine_start_gcode": (
                "; SlicerHub START_PRINT FLSUN V400 (Klipper)\n"
                "G21\n"
                "G90\n"
                "M82\n"
                "M104 S150\n"
                "M140 S[bed_temperature_initial_layer_single]\n"
                "G28\n"
                "BED_MESH_PROFILE LOAD=default\n"
                "G1 Z50 F3000\n"
                "G1 X-150 Y0 F3000\n"
                "M190 S[bed_temperature_initial_layer_single]\n"
                "M109 S[nozzle_temperature_initial_layer]\n"
                "G1 Z0.4 F3000\n"
                "G92 E0\n"
                "G3 X0 Y-130 I150 J1 Z0.3 E30 F2000\n"
                "G92 E0\n"
                "G1 E-0.8 F2100\n"
                "G92 E0"
            ),
            "machine_end_gcode": (
                "; SlicerHub END_PRINT FLSUN V400\n"
                "M400\n"
                "G91\n"
                "G1 E-2 F2700\n"
                "G1 Z10 F3000\n"
                "G90\n"
                "G28\n"
                "M104 S0\n"
                "M140 S0\n"
                "M106 S0\n"
                "M84"
            ),
        }
    )
    machines["flsun_v400"] = v400

    # 2. FLSUN T1 Pro (Delta Ultra-Speed Klipper, Ø260x330 mm, flujo seguro 45-50 mm³/s)
    t1p = resolve_inheritance(flsun_reg, "machine", "FLSun T1Pro 0.4 nozzle")
    t1p.update(
        {
            "type": "machine",
            "name": "SlicerHub FLSUN T1 Pro 0.4 nozzle",
            "printer_model": "FLSun T1Pro",
            "printer_settings_id": "SlicerHub FLSUN T1 Pro 0.4 nozzle",
            "printer_structure": "delta",
            "gcode_flavor": "klipper",
            "nozzle_diameter": ["0.4"],
            "nozzle_type": "brass",
            "printable_area": circular_bed_polygon(130.0, 72),
            "printable_height": "330",
            "cylinder_height": "285",
            "bed_exclude_area": ["0x0"],
            "machine_max_speed_x": ["1000", "1000"],
            "machine_max_speed_y": ["1000", "1000"],
            "machine_max_speed_z": ["20", "20"],
            "machine_max_speed_e": ["60", "30"],
            "machine_max_acceleration_x": ["30000", "30000"],
            "machine_max_acceleration_y": ["30000", "30000"],
            "machine_max_acceleration_extruding": ["30000", "30000"],
            "machine_max_acceleration_travel": ["30000", "30000"],
            "machine_max_acceleration_retracting": ["5000", "5000"],
            "machine_max_acceleration_e": ["5000", "5000"],
            "machine_max_acceleration_z": ["500", "500"],
            "retraction_length": ["0.6"],
            "retraction_speed": ["45"],
            "deretraction_speed": ["45"],
            "z_hop": ["0.4"],
            "z_hop_types": ["Slope Lift"],
            "travel_slope": ["3"],
            "adaptive_bed_mesh_margin": "5",
            "fan_speedup_overhangs": "1",
            "auxiliary_fan": "0",
            "emit_machine_limits_to_gcode": "1",
            "use_relative_e_distances": "1",
            "before_layer_change_gcode": ";BEFORE_LAYER_CHANGE\n;[layer_z]\n",
            "layer_change_gcode": ";AFTER_LAYER_CHANGE\n;[layer_z]\nG92 E0\n",
            "default_filament_profile": ["SlicerHub PLA Master"],
            "default_print_profile": "SlicerHub Alta Velocidad 0.20mm",
            "machine_start_gcode": (
                "; SlicerHub START_PRINT FLSUN T1 Pro (Klipper + CPAP + Adaptive Mesh)\n"
                "G21\n"
                "G90\n"
                "M83\n"
                "M140 S[bed_temperature_initial_layer_single]\n"
                "M104 S150\n"
                "G28\n"
                "BED_MESH_CALIBRATE ADAPTIVE=1\n"
                "G1 Z20 F3000\n"
                "M190 S[bed_temperature_initial_layer_single]\n"
                "M109 S[nozzle_temperature_initial_layer]\n"
                "G1 X-120 Y0 Z0.4 F3000\n"
                "G3 X0 Y-120 I120 J0 Z0.3 E25 F2400\n"
                "G92 E0\n"
                "G1 E-0.6 F2400\n"
                "SET_TMC_CURRENT STEPPER=extruder CURRENT=0.8"
            ),
            "machine_end_gcode": (
                "; SlicerHub END_PRINT FLSUN T1 Pro\n"
                "M400\n"
                "G91\n"
                "G1 E-1.5 F2400\n"
                "G1 Z5 F3000\n"
                "G90\n"
                "G28\n"
                "M104 S0\n"
                "M140 S0\n"
                "M106 S0\n"
                "M84"
            ),
        }
    )
    machines["flsun_t1_pro"] = t1p

    # 3. FLSUN Super Racer (SR) (Delta Klipper/Marlin, Ø260x330 mm, Bowden 5.5 mm)
    sr = resolve_inheritance(flsun_reg, "machine", "FLSun Super Racer 0.4 nozzle")
    sr.update(
        {
            "type": "machine",
            "name": "SlicerHub FLSUN Super Racer 0.4 nozzle",
            "printer_model": "FLSun SR",
            "printer_settings_id": "SlicerHub FLSUN Super Racer 0.4 nozzle",
            "printer_structure": "delta",
            "gcode_flavor": "klipper",
            "nozzle_diameter": ["0.4"],
            "nozzle_type": "brass",
            "printable_area": circular_bed_polygon(130.0, 72),
            "printable_height": "330",
            "bed_exclude_area": ["0x0"],
            "machine_max_speed_x": ["200", "200"],
            "machine_max_speed_y": ["200", "200"],
            "machine_max_speed_z": ["20", "12"],
            "machine_max_speed_e": ["45", "25"],
            "machine_max_acceleration_x": ["5000", "2500"],
            "machine_max_acceleration_y": ["5000", "2500"],
            "machine_max_acceleration_extruding": ["5000", "2500"],
            "machine_max_acceleration_travel": ["5000", "3000"],
            "machine_max_acceleration_retracting": ["5000", "5000"],
            "machine_max_acceleration_e": ["5000", "5000"],
            "machine_max_acceleration_z": ["1500", "200"],
            "retraction_length": ["5.5"],
            "retraction_speed": ["40"],
            "deretraction_speed": ["40"],
            "z_hop": ["0.4"],
            "z_hop_types": ["Slope Lift"],
            "travel_slope": ["3"],
            "auxiliary_fan": "0",
            "emit_machine_limits_to_gcode": "1",
            "use_relative_e_distances": "1",
            "before_layer_change_gcode": ";BEFORE_LAYER_CHANGE\n;[layer_z]\n",
            "layer_change_gcode": ";AFTER_LAYER_CHANGE\n;[layer_z]\nG92 E0\n",
            "default_filament_profile": ["SlicerHub PLA Master"],
            "default_print_profile": "SlicerHub Estandar 0.20mm",
            "machine_start_gcode": (
                "; SlicerHub START_PRINT FLSUN Super Racer (Klipper Bowden)\n"
                "G21\n"
                "G90\n"
                "M83\n"
                "G28\n"
                "M140 S[bed_temperature_initial_layer_single]\n"
                "M104 S150\n"
                "M190 S[bed_temperature_initial_layer_single]\n"
                "BED_MESH_PROFILE LOAD=default\n"
                "M109 S[nozzle_temperature_initial_layer]\n"
                "G1 X-125 Y0 Z0.4 F3000\n"
                "G3 X0 Y-125 I125 J0 Z0.3 E35 F2400\n"
                "G92 E0\n"
                "G1 E-5.5 F2400"
            ),
            "machine_end_gcode": (
                "; SlicerHub END_PRINT FLSUN Super Racer\n"
                "M400\n"
                "G91\n"
                "G1 E-6.0 F3000\n"
                "G1 Z10 F3000\n"
                "G90\n"
                "G28\n"
                "M104 S0\n"
                "M140 S0\n"
                "M106 S0\n"
                "M84"
            ),
        }
    )
    machines["flsun_sr"] = sr

    # 4. FlashForge Creator 5 Pro (CoreXY Toolchanger 4 Cabezales, 256x256x256 mm)
    c5p = resolve_inheritance(flash_reg, "machine", "Flashforge Creator 5 Pro 0.4 nozzle")
    c5p.update(
        {
            "type": "machine",
            "name": "SlicerHub FlashForge Creator 5 Pro 0.4 nozzle",
            "printer_model": "Flashforge Creator 5 Pro",
            "printer_settings_id": "SlicerHub FlashForge Creator 5 Pro 0.4 nozzle",
            "printer_structure": "corexy",
            "gcode_flavor": "klipper",
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
            "bed_exclude_area": ["0x0"],
            "single_extruder_multi_material": "0",
            "printer_extruder_id": ["1", "2", "3", "4"],
            "nozzle_diameter": ["0.4", "0.4", "0.4", "0.4"],
            "nozzle_type": [
                "hardened_steel",
                "hardened_steel",
                "hardened_steel",
                "hardened_steel",
            ],
            "extruder_colour": ["#FCE94F", "#4E9A06", "#3465A4", "#CC0000"],
            "extruder_offset": ["0x0", "0x0", "0x0", "0x0"],
            "retraction_length": ["0.8", "0.8", "0.8", "0.8"],
            "retraction_speed": ["35", "35", "35", "35"],
            "deretraction_speed": ["35", "35", "35", "35"],
            "retract_length_toolchange": ["10", "10", "10", "10"],
            "retract_restart_extra_toolchange": ["0", "0", "0", "0"],
            "z_hop": ["0.4", "0.4", "0.4", "0.4"],
            "z_hop_types": ["Auto Lift", "Auto Lift", "Auto Lift", "Auto Lift"],
            "travel_slope": ["3", "3", "3", "3"],
            "wipe": ["1", "1", "1", "1"],
            "wipe_distance": ["2", "2", "2", "2"],
            "machine_max_speed_x": ["600", "600"],
            "machine_max_speed_y": ["600", "600"],
            "machine_max_speed_z": ["20", "20"],
            "machine_max_speed_e": ["35", "35"],
            "machine_max_acceleration_x": ["30000", "20000"],
            "machine_max_acceleration_y": ["30000", "20000"],
            "machine_max_acceleration_extruding": ["20000", "20000"],
            "machine_max_acceleration_travel": ["20000", "20000"],
            "machine_max_acceleration_retracting": ["5000", "5000"],
            "machine_max_acceleration_e": ["5000", "5000"],
            "machine_max_acceleration_z": ["500", "500"],
            "support_chamber_temp_control": "1",
            "auxiliary_fan": "1",
            "purge_in_prime_tower": "1",
            "emit_machine_limits_to_gcode": "1",
            "use_relative_e_distances": "1",
            "before_layer_change_gcode": ";BEFORE_LAYER_CHANGE\n;[layer_z]\n",
            "layer_change_gcode": ";AFTER_LAYER_CHANGE\n;[layer_z]\nG92 E0\n",
            "default_filament_profile": ["SlicerHub PLA Master"],
            "default_print_profile": "SlicerHub Estandar 0.20mm",
            "machine_start_gcode": (
                "; SlicerHub START_PRINT FlashForge Creator 5 Pro (4-Toolchanger)\n"
                "M140 S[bed_temperature_initial_layer_single]\n"
                "M104 T0 S170 ; Standby anti-oozing cabezal T0\n"
                "M104 T1 S170 ; Standby anti-oozing cabezal T1\n"
                "M104 T2 S170 ; Standby anti-oozing cabezal T2\n"
                "M104 T3 S170 ; Standby anti-oozing cabezal T3\n"
                "M106 P101 S0\n"
                "M106 P2 S0\n"
                "M106 S0\n"
                "M106 P3 S0\n"
                "G90\n"
                "M83\n"
                "G28\n"
                "M190 S[bed_temperature_initial_layer_single]\n"
                "G1 Z5 F2400\n"
                "T[initial_extruder]\n"
                "M109 T[initial_extruder] S[nozzle_temperature_initial_layer]\n"
                "G1 X256 Y0 Z0.2 F6000\n"
                "G1 E5 F{filament_max_volumetric_speed[initial_no_support_extruder]/2.4053*60}\n"
                "G1 X216 E10 F{filament_max_volumetric_speed[initial_no_support_extruder]/2.4053*60}\n"
                "G92 E0"
            ),
            "change_filament_gcode": (
                "; Toolchange standby 170C\n"
                "M104 T[previous_extruder] S170\n"
                "T[next_extruder]\n"
                "M109 T[next_extruder] S[nozzle_temperature]"
            ),
            "machine_end_gcode": (
                "; SlicerHub END_PRINT Creator 5 Pro\n"
                "G1 E-1 F2400\n"
                "G1 X200 Y135 E-2 F30000\n"
                "M104 T0 S0\n"
                "M104 T1 S0\n"
                "M104 T2 S0\n"
                "M104 T3 S0\n"
                "M140 S0\n"
                "M107\n"
                "M84"
            ),
        }
    )
    machines["creator5_pro"] = c5p

    # 5. Creality Ender 3 S1 Pro (Cartesiana Marlin 2, 220x220x270 mm, eje Y <= 2000 mm/s²)
    e3s1p = resolve_inheritance(creality_reg, "machine", "Creality Ender-3 S1 Pro 0.4 nozzle")
    e3s1p.pop("z_lift_type", None)
    e3s1p.update(
        {
            "type": "machine",
            "name": "SlicerHub Creality Ender 3 S1 Pro 0.4 nozzle",
            "printer_model": "Creality Ender-3 S1 Pro",
            "printer_settings_id": "SlicerHub Creality Ender 3 S1 Pro 0.4 nozzle",
            "printer_structure": "i3",
            "gcode_flavor": "marlin2",
            "nozzle_diameter": ["0.4"],
            "nozzle_type": "brass",
            "printable_area": ["0x0", "220x0", "220x220", "0x220"],
            "printable_height": "270",
            "bed_exclude_area": ["0x0"],
            "machine_max_speed_x": ["150", "150"],
            "machine_max_speed_y": ["150", "150"],
            "machine_max_speed_z": ["10", "10"],
            "machine_max_speed_e": ["60", "60"],
            "machine_max_acceleration_x": ["3000", "2000"],
            "machine_max_acceleration_y": ["2000", "2000"],
            "machine_max_acceleration_extruding": ["2000", "1500"],
            "machine_max_acceleration_travel": ["2000", "2000"],
            "machine_max_acceleration_retracting": ["1000", "1000"],
            "machine_max_acceleration_e": ["5000", "5000"],
            "machine_max_acceleration_z": ["100", "100"],
            "machine_max_jerk_x": ["8", "8"],
            "machine_max_jerk_y": ["8", "8"],
            "machine_max_jerk_z": ["0.4", "0.4"],
            "machine_max_jerk_e": ["5", "5"],
            "retraction_length": ["1.2"],
            "retraction_speed": ["40"],
            "deretraction_speed": ["40"],
            "z_hop": ["0.2"],
            "z_hop_types": ["Normal Lift"],
            "auxiliary_fan": "0",
            "emit_machine_limits_to_gcode": "1",
            "use_relative_e_distances": "0",
            "before_layer_change_gcode": ";BEFORE_LAYER_CHANGE\n;[layer_z]\n",
            "layer_change_gcode": ";AFTER_LAYER_CHANGE\n;[layer_z]\n",
            "default_filament_profile": ["SlicerHub PLA Master"],
            "default_print_profile": "SlicerHub Estandar 0.20mm",
            "machine_start_gcode": (
                "; SlicerHub START G-CODE Creality Ender 3 S1 Pro (Marlin 2 + Sprite)\n"
                "G21\n"
                "G90\n"
                "M82\n"
                "M107\n"
                "M140 S[bed_temperature_initial_layer_single]\n"
                "M104 S140 ; Precalentamiento anti-ooze CR Touch\n"
                "G28\n"
                "M420 S1 Z10 ; Cargar malla ABL Marlin 2\n"
                "M190 S[bed_temperature_initial_layer_single]\n"
                "M109 S[nozzle_temperature_initial_layer]\n"
                "G92 E0\n"
                "G1 Z2.0 F3000\n"
                "G1 X2.1 Y20 Z0.28 F5000.0\n"
                "G1 X2.1 Y200.0 Z0.28 F1500.0 E15\n"
                "G1 X2.4 Y200.0 Z0.28 F5000.0\n"
                "G1 X2.4 Y20 Z0.28 F1500.0 E30\n"
                "G92 E0\n"
                "G1 Z2.0 F3000"
            ),
            "machine_end_gcode": (
                "; SlicerHub END G-CODE Creality Ender 3 S1 Pro\n"
                "M140 S0\n"
                "M104 S0\n"
                "M106 S0\n"
                "G91\n"
                "G1 E-1.2 F2400\n"
                "G1 Z5 F3000\n"
                "G90\n"
                "G1 X0 Y220 F3000 ; Limite seguro eje Y bed-slinger\n"
                "M84"
            ),
        }
    )
    machines["ender3_s1_pro"] = e3s1p

    return machines


def synthesize_filaments() -> dict[str, dict[str, Any]]:
    """Sintetiza los 4 perfiles maestros de filamento (1.75 mm)."""
    fil_reg = build_registry(
        [
            ORCA_PROFILES / "OrcaFilamentLibrary" / "filament" / "base",
            ORCA_PROFILES / "OrcaFilamentLibrary" / "filament",
            FLASH_BUNDLE / "OrcaFilamentLibrary" / "filament",
        ]
    )

    pla = resolve_inheritance(fil_reg, "filament", "fdm_filament_pla")
    pla.update(
        {
            "type": "filament",
            "name": "SlicerHub PLA Master",
            "filament_settings_id": ["SlicerHub PLA Master"],
            "filament_type": ["PLA"],
            "filament_diameter": ["1.75"],
            "filament_density": ["1.24"],
            "filament_flow_ratio": ["0.98"],
            "nozzle_temperature_initial_layer": ["220"],
            "nozzle_temperature": ["215"],
            "nozzle_temperature_range_low": ["190"],
            "nozzle_temperature_range_high": ["240"],
            "cool_plate_temp": ["50"],
            "cool_plate_temp_initial_layer": ["55"],
            "eng_plate_temp": ["55"],
            "eng_plate_temp_initial_layer": ["60"],
            "hot_plate_temp": ["60"],
            "hot_plate_temp_initial_layer": ["60"],
            "textured_plate_temp": ["55"],
            "textured_plate_temp_initial_layer": ["60"],
            "fan_min_speed": ["100"],
            "fan_max_speed": ["100"],
            "overhang_fan_speed": ["100"],
            "overhang_fan_threshold": ["50%"],
            "close_fan_the_first_x_layers": ["1"],
            "full_fan_speed_layer": ["2"],
            "filament_max_volumetric_speed": ["28"],
            "idle_temperature": ["170"],
            "activate_chamber_temp_control": ["0"],
            "chamber_temperature": ["0"],
            "enable_pressure_advance": ["1"],
            "pressure_advance": ["0.03"],
            "compatible_printers": MACHINE_NAMES,
        }
    )

    petg = resolve_inheritance(fil_reg, "filament", "fdm_filament_pet")
    petg.update(
        {
            "type": "filament",
            "name": "SlicerHub PETG Master",
            "filament_settings_id": ["SlicerHub PETG Master"],
            "filament_type": ["PETG"],
            "filament_diameter": ["1.75"],
            "filament_density": ["1.27"],
            "filament_flow_ratio": ["0.96"],
            "nozzle_temperature_initial_layer": ["250"],
            "nozzle_temperature": ["245"],
            "nozzle_temperature_range_low": ["225"],
            "nozzle_temperature_range_high": ["265"],
            "cool_plate_temp": ["70"],
            "cool_plate_temp_initial_layer": ["75"],
            "eng_plate_temp": ["75"],
            "eng_plate_temp_initial_layer": ["80"],
            "hot_plate_temp": ["75"],
            "hot_plate_temp_initial_layer": ["80"],
            "textured_plate_temp": ["75"],
            "textured_plate_temp_initial_layer": ["80"],
            "fan_min_speed": ["40"],
            "fan_max_speed": ["60"],
            "overhang_fan_speed": ["70"],
            "overhang_fan_threshold": ["40%"],
            "support_material_interface_fan_speed": ["60"],
            "close_fan_the_first_x_layers": ["3"],
            "full_fan_speed_layer": ["4"],
            "filament_max_volumetric_speed": ["18"],
            "idle_temperature": ["170"],
            "activate_chamber_temp_control": ["0"],
            "chamber_temperature": ["0"],
            "enable_pressure_advance": ["1"],
            "pressure_advance": ["0.04"],
            "compatible_printers": MACHINE_NAMES,
        }
    )

    abs_mat = resolve_inheritance(fil_reg, "filament", "fdm_filament_abs")
    abs_mat.update(
        {
            "type": "filament",
            "name": "SlicerHub ABS Master",
            "filament_settings_id": ["SlicerHub ABS Master"],
            "filament_type": ["ABS"],
            "filament_diameter": ["1.75"],
            "filament_density": ["1.04"],
            "filament_flow_ratio": ["0.93"],
            "nozzle_temperature_initial_layer": ["260"],
            "nozzle_temperature": ["255"],
            "nozzle_temperature_range_low": ["240"],
            "nozzle_temperature_range_high": ["285"],
            "cool_plate_temp": ["95"],
            "cool_plate_temp_initial_layer": ["100"],
            "eng_plate_temp": ["100"],
            "eng_plate_temp_initial_layer": ["105"],
            "hot_plate_temp": ["100"],
            "hot_plate_temp_initial_layer": ["105"],
            "textured_plate_temp": ["100"],
            "textured_plate_temp_initial_layer": ["105"],
            "fan_min_speed": ["15"],
            "fan_max_speed": ["30"],
            "overhang_fan_speed": ["50"],
            "overhang_fan_threshold": ["25%"],
            "close_fan_the_first_x_layers": ["4"],
            "full_fan_speed_layer": ["5"],
            "filament_max_volumetric_speed": ["22"],
            "idle_temperature": ["170"],
            "activate_chamber_temp_control": ["1"],
            "chamber_temperature": ["60"],
            "activate_air_filtration": ["1"],
            "during_print_exhaust_fan_speed": ["30"],
            "complete_print_exhaust_fan_speed": ["70"],
            "enable_pressure_advance": ["1"],
            "pressure_advance": ["0.03"],
            "compatible_printers": MACHINE_NAMES,
        }
    )

    tpu = resolve_inheritance(fil_reg, "filament", "fdm_filament_tpu")
    tpu.update(
        {
            "type": "filament",
            "name": "SlicerHub TPU Master",
            "filament_settings_id": ["SlicerHub TPU Master"],
            "filament_type": ["TPU"],
            "filament_diameter": ["1.75"],
            "filament_density": ["1.21"],
            "filament_flow_ratio": ["1.0"],
            "nozzle_temperature_initial_layer": ["225"],
            "nozzle_temperature": ["225"],
            "nozzle_temperature_range_low": ["210"],
            "nozzle_temperature_range_high": ["245"],
            "cool_plate_temp": ["45"],
            "cool_plate_temp_initial_layer": ["50"],
            "eng_plate_temp": ["50"],
            "eng_plate_temp_initial_layer": ["50"],
            "hot_plate_temp": ["50"],
            "hot_plate_temp_initial_layer": ["50"],
            "textured_plate_temp": ["50"],
            "textured_plate_temp_initial_layer": ["50"],
            "fan_min_speed": ["50"],
            "fan_max_speed": ["70"],
            "overhang_fan_speed": ["80"],
            "close_fan_the_first_x_layers": ["2"],
            "full_fan_speed_layer": ["3"],
            "filament_max_volumetric_speed": ["10"],
            "filament_retraction_length": ["0.8"],
            "filament_retraction_speed": ["30"],
            "idle_temperature": ["170"],
            "activate_chamber_temp_control": ["0"],
            "chamber_temperature": ["0"],
            "compatible_printers": MACHINE_NAMES,
        }
    )

    return {
        "pla_master": pla,
        "petg_master": petg,
        "abs_master": abs_mat,
        "tpu_master": tpu,
    }


def synthesize_processes() -> dict[str, dict[str, Any]]:
    """Sintetiza los 3 perfiles maestros de proceso con ingeniería FFF."""
    proc_reg = build_registry([FLSUN_BUNDLE / "process"])
    base_proc = resolve_inheritance(
        proc_reg, "process", "0.20mm Standard @FLSun T1Pro Generic PLA"
    )

    common_fff = {
        "type": "process",
        "compatible_printers": MACHINE_NAMES,
        "compatible_printers_condition": "",
        "layer_height": "0.2",
        "initial_layer_print_height": "0.2",
        "line_width": "0.42",
        "outer_wall_line_width": "0.42",
        "inner_wall_line_width": "0.45",
        "sparse_infill_line_width": "0.45",
        "internal_solid_infill_line_width": "0.42",
        "top_surface_line_width": "0.42",
        "initial_layer_line_width": "0.5",
        "wall_generator": "arachne",
        "wall_transition_angle": "10",
        "wall_transition_filter_deviation": "25%",
        "wall_transition_length": "100%",
        "min_bead_width": "85%",
        "initial_layer_min_bead_width": "85%",
        "min_feature_size": "25%",
        "precise_outer_wall": "1",
        "ensure_vertical_shell_thickness": "ensure_all",
        "seam_position": "aligned",
        "seam_slope_type": "all",
        "seam_slope_conditional": "1",
        "seam_slope_inner_walls": "1",
        "seam_slope_min_length": "20",
        "seam_slope_start_height": "0",
        "seam_slope_steps": "10",
        "scarf_angle_threshold": "155",
        "scarf_joint_flow_ratio": "1",
        "scarf_joint_speed": "80%",
        "scarf_overhang_threshold": "40%",
        "enable_support": "0",
        "support_type": "tree(auto)",
        "support_style": "default",
        "support_top_z_distance": "0.24",
        "support_bottom_z_distance": "0.22",
        "support_object_xy_distance": "0.4",
        "support_interface_top_layers": "3",
        "support_interface_bottom_layers": "2",
        "support_interface_spacing": "0.2",
        "support_threshold_angle": "30",
        "tree_support_branch_angle": "40",
        "sparse_infill_pattern": "gyroid",
        "top_surface_pattern": "monotonicline",
        "bottom_surface_pattern": "monotonicline",
        "ooze_prevention": "1",
        "standby_temperature_delta": "-50",
        "reduce_crossing_wall": "1",
        "reduce_infill_retraction": "1",
        "enable_prime_tower": "0",
        "filename_format": "{input_filename_base}_{filament_type[initial_tool]}_{print_time}.gcode",
    }

    estandar = copy.deepcopy(base_proc)
    estandar.update(common_fff)
    estandar.update(
        {
            "name": "SlicerHub Estandar 0.20mm",
            "print_settings_id": "SlicerHub Estandar 0.20mm",
            "wall_loops": "3",
            "wall_sequence": "inner wall/outer wall",
            "sparse_infill_density": "12%",
            "top_shell_layers": "4",
            "bottom_shell_layers": "3",
            "top_shell_thickness": "0.8",
            "infill_wall_overlap": "15%",
            "initial_layer_speed": "50",
            "initial_layer_infill_speed": "90",
            "outer_wall_speed": "120",
            "inner_wall_speed": "200",
            "sparse_infill_speed": "220",
            "internal_solid_infill_speed": "180",
            "top_surface_speed": "120",
            "gap_infill_speed": "140",
            "travel_speed": "350",
            "default_acceleration": "5000",
            "outer_wall_acceleration": "2500",
            "inner_wall_acceleration": "5000",
            "travel_acceleration": "9000",
            "initial_layer_acceleration": "1500",
            "top_surface_acceleration": "2500",
        }
    )

    mecanico = copy.deepcopy(base_proc)
    mecanico.update(common_fff)
    mecanico.update(
        {
            "name": "SlicerHub Mecanico Resistente 0.20mm",
            "print_settings_id": "SlicerHub Mecanico Resistente 0.20mm",
            "wall_loops": "4",
            "wall_sequence": "inner-outer-inner wall",
            "sparse_infill_density": "25%",
            "top_shell_layers": "5",
            "bottom_shell_layers": "5",
            "top_shell_thickness": "1.0",
            "infill_wall_overlap": "20%",
            "initial_layer_speed": "40",
            "initial_layer_infill_speed": "75",
            "outer_wall_speed": "80",
            "inner_wall_speed": "150",
            "sparse_infill_speed": "160",
            "internal_solid_infill_speed": "140",
            "top_surface_speed": "90",
            "gap_infill_speed": "100",
            "travel_speed": "300",
            "default_acceleration": "3500",
            "outer_wall_acceleration": "2000",
            "inner_wall_acceleration": "3500",
            "travel_acceleration": "6000",
            "initial_layer_acceleration": "1000",
            "top_surface_acceleration": "2000",
        }
    )

    alta_vel = copy.deepcopy(base_proc)
    alta_vel.update(common_fff)
    alta_vel.update(
        {
            "name": "SlicerHub Alta Velocidad 0.20mm",
            "print_settings_id": "SlicerHub Alta Velocidad 0.20mm",
            "wall_loops": "2",
            "wall_sequence": "inner wall/outer wall",
            "sparse_infill_density": "10%",
            "top_shell_layers": "4",
            "bottom_shell_layers": "3",
            "top_shell_thickness": "0.8",
            "infill_wall_overlap": "15%",
            "initial_layer_speed": "60",
            "initial_layer_infill_speed": "120",
            "outer_wall_speed": "200",
            "inner_wall_speed": "350",
            "sparse_infill_speed": "450",
            "internal_solid_infill_speed": "300",
            "top_surface_speed": "200",
            "gap_infill_speed": "220",
            "travel_speed": "500",
            "default_acceleration": "10000",
            "outer_wall_acceleration": "5000",
            "inner_wall_acceleration": "10000",
            "travel_acceleration": "15000",
            "initial_layer_acceleration": "3000",
            "top_surface_acceleration": "5000",
        }
    )

    return {
        "estandar": estandar,
        "mecanico_resistente": mecanico,
        "alta_velocidad": alta_vel,
    }


def build_catalog() -> dict[str, Any]:
    """Genera el catálogo auxiliar con metadatos físicos y rutas CLI para Fase 1."""
    primary_cli = "/Applications/Flash Studio.app/Contents/MacOS/Flash Studio"
    flsun_cli = "/Applications/FlsunSlicer.app/Contents/MacOS/FlsunSlicer"
    return {
        "cli_runtime": {
            "primary_cli_binary": primary_cli,
            "primary_cli_engine": "Orca-Flashforge 2.4.2 (arm64, compatible OrcaSlicer/FLSUN/Marlin2)",
            "secondary_flsun_binary": flsun_cli,
            "secondary_flsun_note": (
                "FlsunSlicer 3.0.0.13 (x86_64 Rosetta) valida JSONs y compatibilidad en CLI, "
                "pero presenta SIGSEGV 0x6f8 en PartPlateList::generate_print_polygon por wxGetApp().plater() == nullptr; "
                "Flash Studio actúa como motor CLI primario unificado en macOS."
            ),
        },
        "machines": {
            "flsun_v400": {
                "cli_engine": "flash_studio_unified",
                "binary_path": primary_cli,
                "reference_flsun_binary": flsun_cli,
                "kinematics": "delta",
                "origin": "center",
                "diameter_mm": 300,
                "height_mm": 410,
                "safe_square_xy_mm": 205,
                "usable_edge_z_mm": 390,
                "max_volumetric_flow_mm3_s": 37.0,
                "recommended_outer_wall_accel": 2500,
                "recommended_travel_accel": 9000,
            },
            "flsun_t1_pro": {
                "cli_engine": "flash_studio_unified",
                "binary_path": primary_cli,
                "reference_flsun_binary": flsun_cli,
                "kinematics": "delta",
                "origin": "center",
                "diameter_mm": 260,
                "height_mm": 330,
                "usable_edge_z_mm": 285,
                "max_volumetric_flow_mm3_s": 48.0,
                "physical_limit_flow_mm3_s": 52.0,
                "cpap_cooling": True,
                "adaptive_bed_mesh": "circular",
            },
            "flsun_sr": {
                "cli_engine": "flash_studio_unified",
                "binary_path": primary_cli,
                "reference_flsun_binary": flsun_cli,
                "kinematics": "delta",
                "origin": "center",
                "diameter_mm": 260,
                "height_mm": 330,
                "extruder_drive": "bowden_bmg_3_1",
                "max_volumetric_flow_mm3_s": 15.0,
            },
            "creator5_pro": {
                "cli_engine": "flash_studio",
                "binary_path": primary_cli,
                "kinematics": "corexy_toolchanger_4x",
                "origin": "bottom_left",
                "bed_mm": [256, 256, 256],
                "max_volumetric_flow_mm3_s": 32.0,
                "idle_standby_temp_c": 170,
                "chamber_max_temp_c": 65,
                "toolchange_retract_mm": 10.0,
            },
            "ender3_s1_pro": {
                "cli_engine": "orcaslicer_compat",
                "binary_path": primary_cli,
                "kinematics": "cartesian_bedslinger",
                "origin": "bottom_left",
                "bed_mm": [220, 220, 270],
                "max_volumetric_flow_mm3_s": 14.0,
                "y_axis_max_accel_mm_s2": 2000,
                "y_axis_physical_endstop_max_mm": 235,
                "serial_baud": 115200,
            },
        },
        "volumetric_limits_mm3_s": {
            "pla_master": {
                "flsun_t1_pro": 48.0,
                "flsun_v400": 37.0,
                "creator5_pro": 32.0,
                "flsun_sr": 15.0,
                "ender3_s1_pro": 14.0,
            },
            "petg_master": {
                "flsun_t1_pro": 20.0,
                "flsun_v400": 20.0,
                "creator5_pro": 18.0,
                "flsun_sr": 12.0,
                "ender3_s1_pro": 10.0,
            },
            "abs_master": {
                "flsun_t1_pro": 32.0,
                "flsun_v400": 24.0,
                "creator5_pro": 24.0,
                "flsun_sr": 12.0,
                "ender3_s1_pro": 11.0,
            },
            "tpu_master": {
                "flsun_t1_pro": 12.0,
                "flsun_v400": 10.0,
                "creator5_pro": 10.0,
                "flsun_sr": 6.0,
                "ender3_s1_pro": 8.0,
            },
        },
        "petg_support_overrides": {
            "support_top_z_distance": "0.24",
            "support_bottom_z_distance": "0.24",
            "support_object_xy_distance": "0.4",
        },
    }


def main() -> None:
    """Genera todos los perfiles aplanados en `backend/profiles/`."""
    machines = synthesize_machines()
    for name, payload in machines.items():
        write_json(PROFILES_OUT / "machines" / f"{name}.json", payload)

    filaments = synthesize_filaments()
    for name, payload in filaments.items():
        write_json(PROFILES_OUT / "filaments" / f"{name}.json", payload)

    processes = synthesize_processes()
    for name, payload in processes.items():
        write_json(PROFILES_OUT / "process" / f"{name}.json", payload)

    write_json(PROFILES_OUT / "slicerhub_catalog.json", build_catalog())
    print(
        f"Sintetizados {len(machines)} máquinas, {len(filaments)} filamentos, "
        f"{len(processes)} procesos y slicerhub_catalog.json en {PROFILES_OUT}"
    )


if __name__ == "__main__":
    main()
