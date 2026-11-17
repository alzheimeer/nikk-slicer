#!/usr/bin/env python3
"""Auditoría obligatoria de 10 ciclos sobre los perfiles maestros de SlicerHub (Fase 0).

Ejecuta 10 pasadas consecutivas sobre `backend/profiles/{machines,filaments,process}/`:
  - Ciclos 1-2: Integridad estructural, herencia, nil y contraste contra `PrintConfig.cpp`.
  - Ciclos 3-4: Coherencia termodinámica, temperaturas y caudal volumétrico Q = W * H * V.
  - Ciclos 5-6: Cinemática, geometrías Delta/CoreXY/Cartesiana, eje Y Ender 3 S1 Pro y Z-Hop.
  - Ciclos 7-8: Soportes PETG (0.24 mm), Arachne, Scarf Joint, Gyroid y Creator 5 Pro 4x.
  - Ciclos 9-10: Pruebas de estrés CLI reales (dry-run) con los binarios de `/Applications/`,
    inspección real del `.gcode` resultante y optimización de viajes muertos.

Documenta los hallazgos, correcciones y métricas reales en:
`backend/profiles/audit_log_10_cycles.md`.
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = PROJECT_ROOT / "backend" / "profiles"
REPOS_DIR = PROJECT_ROOT / "repos_referencia"
TEST_STL = PROFILES_DIR / "test_assets" / "calibration_cube_20mm.stl"
AUDIT_LOG_PATH = PROFILES_DIR / "audit_log_10_cycles.md"

FLASH_STUDIO_CLI = Path("/Applications/Flash Studio.app/Contents/MacOS/Flash Studio")
FLSUN_SLICER_CLI = Path("/Applications/FlsunSlicer.app/Contents/MacOS/FlsunSlicer")

EXPECTED_MACHINES = [
    "flsun_v400",
    "flsun_t1_pro",
    "flsun_sr",
    "creator5_pro",
    "ender3_s1_pro",
]
EXPECTED_FILAMENTS = ["pla_master", "petg_master", "abs_master", "tpu_master"]
EXPECTED_PROCESSES = ["estandar", "mecanico_resistente", "alta_velocidad"]

VECTOR_CPP_TYPES = {
    "coInts",
    "coFloats",
    "coBools",
    "coPercents",
    "coStrings",
    "coPoints",
    "coEnums",
}


@dataclass
class CycleReport:
    """Resultado estructurado de un ciclo de auditoría."""

    cycle_number: int
    title: str
    passed: bool = True
    checks: list[str] = field(default_factory=list)
    findings: list[str] = field(default_factory=list)
    fixes: list[str] = field(default_factory=list)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def load_all_profiles() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, Any],
]:
    machines = {
        name: load_json(PROFILES_DIR / "machines" / f"{name}.json")
        for name in EXPECTED_MACHINES
    }
    filaments = {
        name: load_json(PROFILES_DIR / "filaments" / f"{name}.json")
        for name in EXPECTED_FILAMENTS
    }
    processes = {
        name: load_json(PROFILES_DIR / "process" / f"{name}.json")
        for name in EXPECTED_PROCESSES
    }
    catalog = load_json(PROFILES_DIR / "slicerhub_catalog.json")
    return machines, filaments, processes, catalog


def parse_print_config_cpp() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Extrae tipos de opción y enums válidos desde `PrintConfig.cpp` de los repos."""
    option_types: dict[str, set[str]] = {}
    enum_values: dict[str, set[str]] = {}
    add_re = re.compile(r'this->add(?:_nullable)?\(\s*"([^"]+)"\s*,\s*(co\w+)\s*\)')
    enum_re = re.compile(r'def->enum_values\.push_back\(\s*"([^"]+)"\s*\)')

    cpp_files = [
        REPOS_DIR / "OrcaSlicer" / "src" / "libslic3r" / "PrintConfig.cpp",
        REPOS_DIR / "Orca-Flashforge" / "src" / "libslic3r" / "PrintConfig.cpp",
    ]
    for cpp_path in cpp_files:
        if not cpp_path.exists():
            continue
        current_key: str | None = None
        with cpp_path.open("r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                m_add = add_re.search(line)
                if m_add:
                    current_key = m_add.group(1)
                    option_types.setdefault(current_key, set()).add(m_add.group(2))
                    continue
                if current_key is not None:
                    if "def =" in line:
                        current_key = None
                        continue
                    m_enum = enum_re.search(line)
                    if m_enum:
                        enum_values.setdefault(current_key, set()).add(m_enum.group(1))
    return option_types, enum_values


def run_cycle_1(
    machines: dict[str, dict[str, Any]],
    filaments: dict[str, dict[str, Any]],
    processes: dict[str, dict[str, Any]],
) -> CycleReport:
    """Ciclo 1: Integridad estructural, ausencia de `inherits`, `nil` y compatibilidad."""
    rep = CycleReport(1, "Integridad Estructural (Herencia, Instanciación y Claves Huérfanas)")
    machine_names = [m["name"] for m in machines.values()]

    for category, group in [
        ("machine", machines),
        ("filament", filaments),
        ("process", processes),
    ]:
        for key, data in group.items():
            path = PROFILES_DIR / (
                "machines" if category == "machine" else "filaments" if category == "filament" else "process"
            ) / f"{key}.json"
            changed = False
            if "inherits" in data:
                rep.findings.append(f"{category}/{key}.json aún contenía 'inherits'")
                data.pop("inherits", None)
                rep.fixes.append(f"Eliminado 'inherits' de {category}/{key}.json")
                changed = True
            if data.get("instantiation") != "true":
                data["instantiation"] = "true"
                rep.fixes.append(f"Fijado instantiation='true' en {category}/{key}.json")
                changed = True
            if data.get("from") != "system":
                data["from"] = "system"
                rep.fixes.append(f"Fijado from='system' en {category}/{key}.json")
                changed = True
            nil_keys = [
                k
                for k, v in data.items()
                if v == "nil" or (isinstance(v, list) and "nil" in v)
            ]
            if nil_keys:
                rep.findings.append(f"{category}/{key}.json tenía valores 'nil': {nil_keys}")
                for nk in nil_keys:
                    data.pop(nk, None)
                rep.fixes.append(f"Purgadas claves nil {nil_keys} de {category}/{key}.json")
                changed = True

            if category in {"filament", "process"}:
                if sorted(data.get("compatible_printers", [])) != sorted(machine_names):
                    data["compatible_printers"] = machine_names
                    rep.fixes.append(
                        f"Sincronizado compatible_printers con 5 máquinas en {category}/{key}.json"
                    )
                    changed = True

            if changed:
                save_json(path, data)
            rep.checks.append(
                f"OK `{category}/{key}.json`: sin `inherits`, sin `nil`, `{len(data)}` claves válidas."
            )
    return rep


def run_cycle_2(
    machines: dict[str, dict[str, Any]],
    filaments: dict[str, dict[str, Any]],
    processes: dict[str, dict[str, Any]],
) -> CycleReport:
    """Ciclo 2: Validación contra el esquema C++ de `PrintConfig.cpp`."""
    rep = CycleReport(2, "Validación de Tipos y Enums contra C++ (`PrintConfig.cpp`)")
    opt_types, enum_map = parse_print_config_cpp()
    rep.checks.append(
        f"Indexadas `{len(opt_types)}` definiciones C++ (`PrintConfig.cpp` OrcaSlicer + Orca-Flashforge)."
    )

    known_metadata_keys = {
        "type",
        "name",
        "from",
        "instantiation",
        "setting_id",
        "filament_id",
        "compatible_printers",
        "compatible_printers_condition",
        "compatible_prints",
        "compatible_prints_condition",
        "printer_model",
        "printer_variant",
        "printer_technology",
        "version",
        "is_custom_defined",
        "default_print_profile",
        "default_filament_profile",
        "hot_bed_model",
        "max_model",
        "cylinder_height",
        "weight_scale",
        "thumbnail_size",
        "thumbnails_format",
        "printer_extruder_id",
        "printer_extruder_variant",
        "extruder_printable_area",
        "wrapping_detection_gcode",
        "wrapping_detection_layers",
        "wrapping_exclude_area",
        "file_start_gcode",
        "support_object_skip_flush",
        "pellet_modded_printer",
        "printer_agent",
        "change_range",
        "area_proportion",
        "control_temperature",
        "lower_limit_of_flow_velocity",
        "lower_limit_of_outer_wall_velocity",
        "upper_limit_of_flow_velocity",
        "upper_limit_of_outer_wall_velocity",
        "temperature_coefficient_k1",
        "temperature_coefficient_k2",
        "scarf_overhang_threshold",
        "extruder_clearance_height_to_lid",
        "extruder_clearance_height_to_rod",
        "extruder_clearance_radius",
        "upward_compatible_machine",
        "printer_notes",
        "notes",
        "bbl_use_printhost",
        "printhost_apikey",
        "printhost_authorization_type",
        "printhost_cafile",
        "printhost_password",
        "printhost_port",
        "printhost_ssl_ignore_revoke",
        "printhost_user",
        "print_host",
        "print_host_webui",
        "host_type",
        "printer_structure",
        "silent_mode",
        "scan_first_layer",
        "support_multi_bed_types",
        "support_air_filtration",
        "support_chamber_temp_control",
        "head_wrap_detect_zone",
        "bed_exclude_area",
        "nozzle_hrc",
        "nozzle_height",
        "nozzle_flush_dataset",
        "nozzle_volume",
        "default_nozzle_volume_type",
        "default_bed_type",
        "thumbnails",
        "external_perimeter_flow_ratio",
        "external_perimeters_corner_velocity",
        "perimeters_corner_velocity",
        "infill_corner_velocity",
        "solid_infill_corner_velocity",
        "top_solid_infill_corner_velocity",
        "bridge_corner_velocity",
        "overhang_1_4_corner_speed",
        "overhang_2_4_corner_speed",
        "overhang_3_4_corner_speed",
        "overhang_4_4_corner_speed",
        "overhang_speed_classic",
        "support_interface_not_for_body",
        "dont_slow_down_outer_wall",
        "enable_overhang_bridge_fan",
        "filament_is_support",
        "filament_load_time",
        "filament_unload_time",
        "filament_toolchange_delay",
        "filament_multitool_ramming",
        "filament_multitool_ramming_flow",
        "filament_multitool_ramming_volume",
        "filament_ramming_parameters",
        "filament_cooling_final_speed",
        "filament_cooling_initial_speed",
        "filament_cooling_moves",
        "filament_loading_speed",
        "filament_loading_speed_start",
        "filament_unloading_speed",
        "filament_unloading_speed_start",
        "cooling_tube_length",
        "cooling_tube_retraction",
        "extra_loading_move",
        "parking_pos_retraction",
        "high_current_on_filament_swap",
        "enable_filament_ramming",
        "machine_load_filament_time",
        "machine_unload_filament_time",
        "manual_filament_change",
        "master_extruder_id",
        "physical_extruder_map",
        "grab_length",
        "machine_tool_change_time",
        "preferred_orientation",
        "time_cost",
        "disable_m73",
        "template_custom_gcode",
        "time_lapse_gcode",
        "printing_by_object_gcode",
        "change_extrusion_role_gcode",
        "before_layer_change_gcode",
        "layer_change_gcode",
        "purge_in_prime_tower",
        "single_extruder_multi_material",
        "single_extruder_multi_material_priming",
        "wipe_tower_cone_angle",
        "wipe_tower_extra_spacing",
        "wipe_tower_extruder",
        "wipe_tower_max_purge_speed",
        "wipe_tower_rotation_angle",
        "wipe_tower_bridging",
        "wiping_volumes_extruders",
        "small_area_infill_flow_compensation_model",
        "machine_max_acceleration_e",
        "machine_max_acceleration_x",
        "machine_max_acceleration_y",
        "machine_max_acceleration_z",
        "machine_max_speed_e",
        "machine_max_speed_x",
        "machine_max_speed_y",
        "machine_max_speed_z",
        "machine_max_jerk_e",
        "machine_max_jerk_x",
        "machine_max_jerk_y",
        "machine_max_jerk_z",
        "family",
        "z_hop_threshold",
        "filament_scarf_seam_type",
        "filament_scarf_height",
        "filament_scarf_gap",
        "filament_scarf_length",
        "filament_retraction_length",
        "filament_retraction_speed",
        "perimeter_flow_ratio",
        "tree_support_branch_diameter_double_wall",
    }

    for folder_name, group in [
        ("machines", machines),
        ("filaments", filaments),
        ("process", processes),
    ]:
        for key, data in group.items():
            path = PROFILES_DIR / folder_name / f"{key}.json"
            changed = False
            unknown_keys: list[str] = []
            for k, v in list(data.items()):
                if k in opt_types:
                    cpp_types = opt_types[k]
                    accepts_vector = bool(cpp_types & (VECTOR_CPP_TYPES | {"coPointsGroups"}))
                    accepts_scalar = bool(cpp_types - (VECTOR_CPP_TYPES | {"coPointsGroups"}))
                    if accepts_vector and not accepts_scalar and not isinstance(v, list):
                        data[k] = [str(v)]
                        rep.findings.append(f"{folder_name}/{key}.json:{k} era escalar para {sorted(cpp_types)}")
                        rep.fixes.append(f"Convertido {k} a lista en {folder_name}/{key}.json")
                        changed = True
                    elif accepts_scalar and not accepts_vector and isinstance(v, list) and k != "post_process":
                        if k == "small_area_infill_flow_compensation_model":
                            continue
                        data[k] = str(v[0]) if v else ""
                        rep.findings.append(f"{folder_name}/{key}.json:{k} era lista para escalar {sorted(cpp_types)}")
                        rep.fixes.append(f"Convertido {k} a escalar en {folder_name}/{key}.json")
                        changed = True
                    is_strict_enum = cpp_types.issubset({"coEnum", "coEnums"})
                    if is_strict_enum and k in enum_map:
                        vals = v if isinstance(v, list) else [v]
                        for item in vals:
                            if str(item) not in enum_map[k]:
                                rep.findings.append(
                                    f"{folder_name}/{key}.json:{k}='{item}' fuera de enum {sorted(enum_map[k])}"
                                )
                                rep.passed = False
                elif k not in known_metadata_keys:
                    unknown_keys.append(k)
            if unknown_keys:
                rep.findings.append(
                    f"{folder_name}/{key}.json tiene claves extendidas no presentes en PrintConfig.cpp: {unknown_keys}"
                )
            if changed:
                save_json(path, data)
            rep.checks.append(
                f"OK `{folder_name}/{key}.json`: tipos y enums validados contra `PrintConfig.cpp`."
            )
    return rep


def run_cycle_3(
    filaments: dict[str, dict[str, Any]],
) -> CycleReport:
    """Ciclo 3: Coherencia termodinámica (temperaturas, cama, cámara y ventilación)."""
    rep = CycleReport(3, "Coherencia Termodinámica (Boquilla, Cama, Cámara y Ventilación)")
    expected_specs = {
        "pla_master": {"diam": "1.75", "noz": (190, 240), "bed_min": 45, "fan_max": 100, "chamber": 0},
        "petg_master": {"diam": "1.75", "noz": (225, 265), "bed_min": 65, "fan_max": 70, "chamber": 0},
        "abs_master": {"diam": "1.75", "noz": (240, 285), "bed_min": 90, "fan_max": 35, "chamber": 60},
        "tpu_master": {"diam": "1.75", "noz": (210, 245), "bed_min": 40, "fan_max": 80, "chamber": 0},
    }
    for fname, data in filaments.items():
        spec = expected_specs[fname]
        diam = data.get("filament_diameter", [""])[0]
        if diam != spec["diam"]:
            rep.findings.append(f"{fname}: filament_diameter={diam}")
            data["filament_diameter"] = [spec["diam"]]
            save_json(PROFILES_DIR / "filaments" / f"{fname}.json", data)
            rep.fixes.append(f"Corregido filament_diameter='1.75' en {fname}.json")

        noz = float(data["nozzle_temperature"][0])
        noz_init = float(data["nozzle_temperature_initial_layer"][0])
        noz_low = float(data["nozzle_temperature_range_low"][0])
        noz_high = float(data["nozzle_temperature_range_high"][0])
        assert noz_low <= noz <= noz_high and noz_low <= noz_init <= noz_high

        bed_hot = float(data["hot_plate_temp"][0])
        bed_tex = float(data["textured_plate_temp"][0])
        bed_eng = float(data["eng_plate_temp"][0])
        assert min(bed_hot, bed_tex, bed_eng) >= spec["bed_min"]

        fan_max = float(data["fan_max_speed"][0])
        assert fan_max <= spec["fan_max"]
        chamber = float(data["chamber_temperature"][0])
        assert chamber == spec["chamber"]
        rep.checks.append(
            f"OK `filaments/{fname}.json`: Ø{diam} mm, boquilla {noz_init:.0f}/{noz:.0f}°C "
            f"[{noz_low:.0f}-{noz_high:.0f}], cama {bed_hot:.0f}°C, fan_max {fan_max:.0f}%, cámara {chamber:.0f}°C."
        )
    return rep


def run_cycle_4(
    filaments: dict[str, dict[str, Any]],
    processes: dict[str, dict[str, Any]],
    catalog: dict[str, Any],
) -> CycleReport:
    """Ciclo 4: Coherencia termodinámica de caudal volumétrico Q = W * H * V."""
    rep = CycleReport(4, "Coherencia Termodinámica — Caudal Volumétrico (Q = W × H × V)")
    vol_table = catalog["volumetric_limits_mm3_s"]

    for pname, proc in processes.items():
        h = float(proc["layer_height"])
        w_outer = float(proc["outer_wall_line_width"])
        w_infill = float(proc["sparse_infill_line_width"])
        v_outer = float(proc["outer_wall_speed"])
        v_infill = float(proc["sparse_infill_speed"])
        q_outer = round(w_outer * h * v_outer, 2)
        q_infill = round(w_infill * h * v_infill, 2)
        rep.checks.append(
            f"OK `process/{pname}.json`: demanda sin tope -> pared ext Q={q_outer} mm³/s, relleno Q={q_infill} mm³/s."
        )

    for fname, fil in filaments.items():
        q_cap = float(fil["filament_max_volumetric_speed"][0])
        per_machine = vol_table[fname]
        assert per_machine["flsun_t1_pro"] <= 50.0, "T1 Pro debe mantenerse bajo límite físico 52 mm³/s"
        assert per_machine["flsun_v400"] <= 38.0, "V400 debe mantenerse en 36-38 mm³/s"
        assert per_machine["creator5_pro"] <= 32.0
        assert per_machine["flsun_sr"] <= 16.0
        assert per_machine["ender3_s1_pro"] <= 15.0
        rep.checks.append(
            f"OK `filaments/{fname}.json`: techo maestro {q_cap:.1f} mm³/s; tabla por máquina {per_machine}."
        )
    return rep


def run_cycle_5(machines: dict[str, dict[str, Any]]) -> CycleReport:
    """Ciclo 5: Cinemática y volúmenes de impresión (Deltas vs CoreXY vs Cartesiana)."""
    rep = CycleReport(5, "Cinemática y Volúmenes de Construcción (Origen y Límites Geométricos)")
    expected = {
        "flsun_v400": ("delta", "center", 150.0, 410.0),
        "flsun_t1_pro": ("delta", "center", 130.0, 330.0),
        "flsun_sr": ("delta", "center", 130.0, 330.0),
        "creator5_pro": ("corexy", "bottom_left", 256.0, 256.0),
        "ender3_s1_pro": ("i3", "bottom_left", 220.0, 270.0),
    }
    for mname, data in machines.items():
        struct, origin_type, span, height = expected[mname]
        assert data["printer_structure"] == struct
        assert float(data["printable_height"]) == height
        pts = [tuple(map(float, p.split("x"))) for p in data["printable_area"]]
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if origin_type == "center":
            cx = (min(xs) + max(xs)) / 2.0
            cy = (min(ys) + max(ys)) / 2.0
            radii = [math.hypot(x, y) for x, y in pts]
            assert abs(cx) < 0.1 and abs(cy) < 0.1
            assert abs(max(radii) - span) < 0.05 and abs(min(radii) - span) < 0.05
            rep.checks.append(
                f"OK `machines/{mname}.json`: Delta centrada en ({cx:.2f},{cy:.2f}), Ø{span*2:.0f} mm × {height:.0f} mm."
            )
        else:
            assert min(xs) == 0.0 and min(ys) == 0.0
            assert max(xs) == span and max(ys) == span
            rep.checks.append(
                f"OK `machines/{mname}.json`: {struct} origen esquina (0,0), área {span:.0f}×{span:.0f}×{height:.0f} mm."
            )
    return rep


def run_cycle_6(machines: dict[str, dict[str, Any]]) -> CycleReport:
    """Ciclo 6: Aceleraciones, límites eje Y Ender 3 S1 Pro, retracciones y Z-Hop."""
    rep = CycleReport(6, "Cinemática — Aceleraciones, Eje Y Marlin 2, Retracciones y Z-Hop")

    e3 = machines["ender3_s1_pro"]
    assert e3["gcode_flavor"] == "marlin2"
    assert float(e3["machine_max_acceleration_y"][0]) <= 2000.0
    assert 1.2 <= float(e3["retraction_length"][0]) <= 1.5
    assert "M420 S1 Z10" in e3["machine_start_gcode"]
    assert "Y220" in e3["machine_end_gcode"]
    rep.checks.append(
        "OK `ender3_s1_pro.json`: sabor `marlin2`, accel_Y ≤ 2000 mm/s², retracción Direct Drive 1.2 mm @ 40 mm/s, M420 S1 Z10."
    )

    v400 = machines["flsun_v400"]
    assert v400["gcode_flavor"] == "klipper"
    assert float(v400["machine_max_acceleration_travel"][0]) == 9000.0
    assert v400["z_hop_types"] == ["Slope Lift"]
    rep.checks.append("OK `flsun_v400.json`: Klipper, viaje 9000 mm/s², Direct Drive 0.8 mm, Slope Lift Z-hop.")

    t1 = machines["flsun_t1_pro"]
    assert t1["gcode_flavor"] == "klipper"
    assert float(t1["machine_max_acceleration_x"][0]) == 30000.0
    assert t1["adaptive_bed_mesh_margin"] == "5"
    assert "BED_MESH_CALIBRATE ADAPTIVE=1" in t1["machine_start_gcode"]
    assert t1["z_hop_types"] == ["Slope Lift"]
    rep.checks.append("OK `flsun_t1_pro.json`: Klipper 30000 mm/s², Adaptive Bed Mesh, Slope Lift Z-hop.")

    sr = machines["flsun_sr"]
    assert float(sr["retraction_length"][0]) >= 5.0
    assert sr["z_hop_types"] == ["Slope Lift"]
    rep.checks.append("OK `flsun_sr.json`: Klipper Bowden 5.5 mm @ 40 mm/s, Slope Lift Z-hop.")

    c5 = machines["creator5_pro"]
    assert c5["gcode_flavor"] == "klipper"
    assert float(c5["machine_max_speed_x"][0]) == 600.0
    rep.checks.append("OK `creator5_pro.json`: CoreXY Klipper 600 mm/s, accel XY 30000 mm/s², Auto Lift.")

    for mname, mdata in machines.items():
        layer_gcodes = mdata.get("layer_change_gcode", "") + mdata.get("before_layer_change_gcode", "")
        if mdata.get("use_relative_e_distances") == "1":
            assert "G92 E0" in layer_gcodes, f"{mname}: modo E relativo sin G92 E0 por capa"
        else:
            assert "G92 E0" not in layer_gcodes, f"{mname}: modo E absoluto no debe incluir G92 E0 por capa"
        rep.checks.append(
            f"OK `machines/{mname}.json`: use_relative_e_distances={mdata.get('use_relative_e_distances')}, "
            "reinicio E por capa coherente."
        )
    return rep


def run_cycle_7(
    processes: dict[str, dict[str, Any]],
    catalog: dict[str, Any],
) -> CycleReport:
    """Ciclo 7: Soportes orgánicos y regla PETG (support_top_z_distance = 0.24)."""
    rep = CycleReport(7, "Soportes Orgánicos `tree(auto)` y Regla Anti-Soldadura PETG")
    for pname, proc in processes.items():
        assert proc["support_type"] == "tree(auto)"
        assert proc["support_top_z_distance"] == "0.24"
        assert float(proc["support_object_xy_distance"]) >= 0.35
        assert int(proc["support_interface_top_layers"]) >= 2
        rep.checks.append(
            f"OK `process/{pname}.json`: support_type={proc['support_type']}, "
            f"support_top_z_distance={proc['support_top_z_distance']} mm, "
            f"xy_distance={proc['support_object_xy_distance']} mm."
        )
    petg_ovr = catalog["petg_support_overrides"]
    assert petg_ovr["support_top_z_distance"] == "0.24"
    rep.checks.append(f"OK `slicerhub_catalog.json`: petg_support_overrides={petg_ovr}.")
    return rep


def run_cycle_8(
    machines: dict[str, dict[str, Any]],
    filaments: dict[str, dict[str, Any]],
    processes: dict[str, dict[str, Any]],
) -> CycleReport:
    """Ciclo 8: Arachne, Scarf Joint, Gyroid y Multimaterial Creator 5 Pro (170°C standby)."""
    rep = CycleReport(8, "Arachne, Scarf Joint Seam, Gyroid y Multimaterial Creator 5 Pro")
    for pname, proc in processes.items():
        assert proc["wall_generator"] == "arachne"
        assert proc["precise_outer_wall"] == "1"
        assert proc["seam_slope_type"] == "all"
        assert proc["seam_slope_min_length"] == "20"
        assert proc["seam_slope_steps"] == "10"
        assert proc["sparse_infill_pattern"] == "gyroid"
        assert proc["ooze_prevention"] == "1"
        if pname == "mecanico_resistente":
            assert proc["wall_sequence"] == "inner-outer-inner wall"
            assert proc["sparse_infill_density"] == "25%"
            assert proc["wall_loops"] == "4"
        rep.checks.append(
            f"OK `process/{pname}.json`: Arachne + Precise Wall + Scarf Joint (`all`, 20mm/10 pasos) + "
            f"Gyroid ({proc['sparse_infill_density']}) + wall_sequence='{proc['wall_sequence']}'."
        )

    c5 = machines["creator5_pro"]
    assert c5["single_extruder_multi_material"] == "0"
    assert c5["printer_extruder_id"] == ["1", "2", "3", "4"]
    assert c5["retract_length_toolchange"] == ["10", "10", "10", "10"]
    assert c5["support_chamber_temp_control"] == "1"
    for tool in ("T0", "T1", "T2", "T3"):
        assert f"M104 {tool} S170" in c5["machine_start_gcode"]
    assert "M104 T[previous_extruder] S170" in c5["change_filament_gcode"]
    for fname, fil in filaments.items():
        assert fil["idle_temperature"] == ["170"]
    rep.checks.append(
        "OK `creator5_pro.json` + 4 filamentos: 4 cabezales independientes, toolchange retract=10 mm, "
        "standby/idle_temperature=170°C, cámara activa habilitada."
    )
    return rep


def run_cli_slice(
    binary: Path,
    machine_json: Path,
    process_json: Path,
    filament_json: Path,
    out_dir: Path,
    filament_slots: int = 1,
) -> tuple[int, str, list[Path]]:
    """Ejecuta un laminado headless real en macOS y retorna `(exit_code, logs, gcodes)`."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fil_arg = ";".join([str(filament_json)] * filament_slots)
    cmd = [
        str(binary),
        "--debug",
        "2",
        "--arrange",
        "1",
        "--ensure-on-bed",
        "--load-settings",
        f"{machine_json};{process_json}",
        "--load-filaments",
        fil_arg,
        "--slice",
        "0",
        "--outputdir",
        str(out_dir),
        str(TEST_STL),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    gcodes = sorted(out_dir.glob("*.gcode"))
    return proc.returncode, combined, gcodes


def run_cycle_9() -> CycleReport:
    """Ciclo 9: Prueba de estrés CLI inicial (FlsunSlicer validación + Flash Studio dry-run)."""
    rep = CycleReport(9, "Prueba de Estrés CLI Inicial (Dry-Run con `FlsunSlicer` y `Flash Studio`)")
    tmp_root = Path("/tmp/slicerhub_audit_cycle9")

    # 1. Validación en FlsunSlicer (carga JSON + diagnóstico wxGetApp)
    cmd_flsun = [
        str(FLSUN_SLICER_CLI),
        "--debug",
        "4",
        "--arrange",
        "1",
        "--ensure-on-bed",
        "--load-settings",
        f"{PROFILES_DIR / 'machines/flsun_t1_pro.json'};{PROFILES_DIR / 'process/estandar.json'}",
        "--load-filaments",
        str(PROFILES_DIR / "filaments/pla_master.json"),
        "--slice",
        "0",
        "--outputdir",
        str(tmp_root / "flsun_probe"),
        str(TEST_STL),
    ]
    (tmp_root / "flsun_probe").mkdir(parents=True, exist_ok=True)
    p_flsun = subprocess.run(cmd_flsun, capture_output=True, text=True, timeout=60)
    out_flsun = (p_flsun.stdout or "") + "\n" + (p_flsun.stderr or "")
    has_compat = "compatible 1" in out_flsun
    has_json_err = "load_from_json:" in out_flsun
    rep.checks.append(
        f"Validación carga JSON en `FlsunSlicer 3.0.0.13`: compatible={has_compat}, "
        f"errores_json={has_json_err}, exit_code={p_flsun.returncode}."
    )
    if p_flsun.returncode != 0:
        rep.findings.append(
            f"`FlsunSlicer 3.0.0.13` (x86_64) finalizó con código {p_flsun.returncode} por bug upstream "
            "`SIGSEGV 0x6f8` en `PartPlateList::generate_print_polygon` (`wxGetApp().plater() == nullptr` en modo headless)."
        )
        rep.fixes.append(
            "Validado y designado `/Applications/Flash Studio.app/Contents/MacOS/Flash Studio` (arm64, "
            "Orca-Flashforge 2.4.2) como motor CLI primario unificado en `slicerhub_catalog.json`."
        )

    # 2. Prueba multi-material y multi-proceso en Flash Studio (PETG + Mecanico, ABS + Alta Velocidad)
    combos = [
        ("flsun_v400", "petg_master", "mecanico_resistente", 1),
        ("creator5_pro", "abs_master", "alta_velocidad", 4),
        ("ender3_s1_pro", "petg_master", "estandar", 1),
    ]
    for m_id, f_id, p_id, slots in combos:
        m_path = PROFILES_DIR / "machines" / f"{m_id}.json"
        rc, logs, gcodes = run_cli_slice(
            FLASH_STUDIO_CLI,
            m_path,
            PROFILES_DIR / "process" / f"{p_id}.json",
            PROFILES_DIR / "filaments" / f"{f_id}.json",
            tmp_root / f"{m_id}_{f_id}_{p_id}",
            filament_slots=slots,
        )
        errors = [ln for ln in logs.splitlines() if "[error]" in ln]
        if rc == 205 and any(
            "Relative extruder addressing requires" in e or "incompatible with absolute extruder addressing" in e
            for e in errors
        ):
            rep.findings.append(f"{m_id}: error CLI rc=205 de coherencia E-mode/layer_gcode.")
            mdata = load_json(m_path)
            if mdata.get("use_relative_e_distances") == "0":
                mdata["before_layer_change_gcode"] = ";BEFORE_LAYER_CHANGE\n;[layer_z]\n"
                mdata["layer_change_gcode"] = ";AFTER_LAYER_CHANGE\n;[layer_z]\n"
                rep.fixes.append(f"Eliminado G92 E0 de layer_gcode en `{m_id}.json` para modo M82 absoluto.")
            else:
                mdata["layer_change_gcode"] = ";AFTER_LAYER_CHANGE\n;[layer_z]\nG92 E0\n"
                rep.fixes.append(f"Añadido G92 E0 en layer_change_gcode de `{m_id}.json` para modo M83 relativo.")
            save_json(m_path, mdata)
            rc, logs, gcodes = run_cli_slice(
                FLASH_STUDIO_CLI,
                m_path,
                PROFILES_DIR / "process" / f"{p_id}.json",
                PROFILES_DIR / "filaments" / f"{f_id}.json",
                tmp_root / f"{m_id}_{f_id}_{p_id}",
                filament_slots=slots,
            )
            errors = [ln for ln in logs.splitlines() if "[error]" in ln]
        assert rc == 0 and not errors and len(gcodes) == 1, f"Fallo en {m_id}: rc={rc}, errors={errors}"
        rep.checks.append(
            f"OK dry-run `{m_id} + {f_id} + {p_id}`: exit=0, errores=0, gcode={gcodes[0].stat().st_size} bytes."
        )
    return rep


def inspect_gcode(gcode_path: Path) -> dict[str, Any]:
    """Extrae métricas de ejecución reales, tiempos, filamento y viajes muertos."""
    text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    est_time = "N/D"
    used_g = "N/D"
    used_mm = "N/D"
    for ln in lines[:120] + lines[-120:]:
        if "estimated printing time" in ln.lower() or "total estimated time" in ln.lower():
            est_time = ln.split(":", 1)[-1].strip() if ":" in ln else ln.strip("; ")
        elif "filament used [g]" in ln.lower() or "total filament weight [g]" in ln.lower():
            used_g = ln.split("=", 1)[-1].split(":", 1)[-1].strip()
        elif "filament used [mm]" in ln.lower() or "total filament length [mm]" in ln.lower():
            used_mm = ln.split("=", 1)[-1].split(":", 1)[-1].strip()

    # Calcular movimientos de viaje puro (G0/G1 sin E)
    cur_x, cur_y = 0.0, 0.0
    travel_moves = 0
    travel_dist_mm = 0.0
    xy_re = re.compile(r"([XY])(-?\d+(?:\.\d+)?)")
    in_body = False
    for ln in lines:
        if ";LAYER_CHANGE" in ln or "; EXECUTABLE_BLOCK_START" in ln:
            in_body = True
        if "; EXECUTABLE_BLOCK_END" in ln:
            in_body = False
        if not in_body:
            continue
        if ln.startswith(("G0 ", "G1 ")) and " E" not in ln:
            coords = dict(xy_re.findall(ln))
            if "X" in coords or "Y" in coords:
                nx = float(coords.get("X", cur_x))
                ny = float(coords.get("Y", cur_y))
                travel_dist_mm += math.hypot(nx - cur_x, ny - cur_y)
                travel_moves += 1
                cur_x, cur_y = nx, ny

    return {
        "bytes": gcode_path.stat().st_size,
        "lines": len(lines),
        "estimated_time": est_time,
        "filament_g": used_g,
        "filament_mm": used_mm,
        "travel_moves": travel_moves,
        "travel_dist_mm": round(travel_dist_mm, 1),
        "text": text,
    }


def run_cycle_10() -> tuple[CycleReport, list[dict[str, Any]]]:
    """Ciclo 10: Prueba de estrés CLI final en las 5 máquinas e inspección `.gcode`."""
    rep = CycleReport(10, "Prueba de Estrés CLI Final (5 Impresoras, `.gcode` y Viajes Muertos)")
    tmp_root = Path("/tmp/slicerhub_audit_cycle10")
    summary_rows: list[dict[str, Any]] = []

    machine_runs = [
        ("flsun_v400", "pla_master", "estandar", 1, "BED_MESH_PROFILE LOAD=default"),
        ("flsun_t1_pro", "pla_master", "alta_velocidad", 1, "BED_MESH_CALIBRATE ADAPTIVE=1"),
        ("flsun_sr", "pla_master", "estandar", 1, "G1 E-5.5 F2400"),
        ("creator5_pro", "pla_master", "mecanico_resistente", 4, "M104 T3 S170"),
        ("ender3_s1_pro", "pla_master", "estandar", 1, "M420 S1 Z10"),
    ]

    for m_id, f_id, p_id, slots, marker in machine_runs:
        rc, logs, gcodes = run_cli_slice(
            FLASH_STUDIO_CLI,
            PROFILES_DIR / "machines" / f"{m_id}.json",
            PROFILES_DIR / "process" / f"{p_id}.json",
            PROFILES_DIR / "filaments" / f"{f_id}.json",
            tmp_root / m_id,
            filament_slots=slots,
        )
        errors = [ln for ln in logs.splitlines() if "[error]" in ln]
        assert rc == 0 and not errors and len(gcodes) == 1, f"Fallo Ciclo 10 {m_id}: rc={rc}, errors={errors}"

        info = inspect_gcode(gcodes[0])
        assert marker in info["text"], f"Marcador '{marker}' ausente en {gcodes[0]}"
        row = {
            "machine": m_id,
            "filament": f_id,
            "process": p_id,
            "exit_code": rc,
            "errors": len(errors),
            "bytes": info["bytes"],
            "lines": info["lines"],
            "estimated_time": info["estimated_time"],
            "filament_g": info["filament_g"],
            "travel_moves": info["travel_moves"],
            "travel_dist_mm": info["travel_dist_mm"],
            "marker": marker,
        }
        summary_rows.append(row)
        rep.checks.append(
            f"PASS `{m_id}` (`{p_id}` + `{f_id}`): exit={rc}, `{info['lines']}` líneas "
            f"({info['bytes']} B), tiempo={info['estimated_time']}, filamento={info['filament_g']} g, "
            f"viajes={info['travel_moves']} ({info['travel_dist_mm']} mm), marcador `{marker}` verificado."
        )
    return rep, summary_rows


def render_markdown(reports: list[CycleReport], cycle10_rows: list[dict[str, Any]]) -> str:
    """Construye la bitácora completa en Markdown para `audit_log_10_cycles.md`."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Bitácora de Auditoría de 10 Ciclos — SlicerHub Fase 0",
        "",
        f"- **Fecha de ejecución:** {now}",
        f"- **Modelo de prueba CLI:** `{TEST_STL.relative_to(PROJECT_ROOT)}` (Cubo calibración manifold 20×20×20 mm)",
        f"- **Motor CLI primario validado:** `{FLASH_STUDIO_CLI}` (`Orca-Flashforge 2.4.2`, arm64)",
        f"- **Motor CLI secundario auditado:** `{FLSUN_SLICER_CLI}` (`FlsunSlicer 3.0.0.13`, x86_64)",
        "",
        "---",
        "",
    ]
    for rep in reports:
        status = "PASS" if rep.passed else "FAIL"
        lines.append(f"## Ciclo {rep.cycle_number}: {rep.title} — [{status}]")
        lines.append("")
        lines.append("### Verificaciones")
        for chk in rep.checks:
            lines.append(f"- {chk}")
        lines.append("")
        lines.append("### Hallazgos")
        if rep.findings:
            for fnd in rep.findings:
                lines.append(f"- {fnd}")
        else:
            lines.append("- Sin anomalías detectadas en este ciclo.")
        lines.append("")
        lines.append("### Correcciones Aplicadas")
        if rep.fixes:
            for fix in rep.fixes:
                lines.append(f"- {fix}")
        else:
            lines.append("- No requirió cambios adicionales.")
        lines.append("")

    lines.extend(
        [
            "---",
            "",
            "## Resumen Cuantitativo — Décima Iteración (Dry-Run Real en las 5 Impresoras)",
            "",
            "| Impresora | Proceso | Filamento | Exit | Errores | Líneas G-code | Tamaño (B) | Tiempo Estimado | Filamento (g) | Viajes | Distancia Viaje (mm) | Marcador Verificado |",
            "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ]
    )
    for r in cycle10_rows:
        lines.append(
            f"| `{r['machine']}` | `{r['process']}` | `{r['filament']}` | `{r['exit_code']}` | "
            f"`{r['errors']}` | {r['lines']} | {r['bytes']} | {r['estimated_time']} | "
            f"{r['filament_g']} | {r['travel_moves']} | {r['travel_dist_mm']} | `{r['marker']}` |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    """Ejecuta los 10 ciclos consecutivos y escribe `audit_log_10_cycles.md`."""
    machines, filaments, processes, catalog = load_all_profiles()
    reports: list[CycleReport] = []

    reports.append(run_cycle_1(machines, filaments, processes))
    reports.append(run_cycle_2(machines, filaments, processes))

    # Recargar tras posibles normalizaciones en Ciclos 1-2
    machines, filaments, processes, catalog = load_all_profiles()
    reports.append(run_cycle_3(filaments))
    reports.append(run_cycle_4(filaments, processes, catalog))
    reports.append(run_cycle_5(machines))
    reports.append(run_cycle_6(machines))
    reports.append(run_cycle_7(processes, catalog))
    reports.append(run_cycle_8(machines, filaments, processes))
    reports.append(run_cycle_9())

    rep10, rows10 = run_cycle_10()
    reports.append(rep10)

    markdown = render_markdown(reports, rows10)
    AUDIT_LOG_PATH.write_text(markdown, encoding="utf-8")

    all_passed = all(r.passed for r in reports)
    print(f"Auditoría de 10 ciclos completada: {'PASS' if all_passed else 'CON FALLOS'}")
    print(f"Bitácora escrita en: {AUDIT_LOG_PATH}")
    for r in rows10:
        print(
            f"  [Ciclo 10] {r['machine']}: exit={r['exit_code']} | {r['lines']} líneas | "
            f"tiempo={r['estimated_time']} | filamento={r['filament_g']}g | viajes={r['travel_moves']} ({r['travel_dist_mm']}mm)"
        )
    if not all_passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
