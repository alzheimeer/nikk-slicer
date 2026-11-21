"""Copiloto IA (Gemini / DeepSeek API con fallback heurístico) con prioridad 'Cero Soportes Primero'."""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any

from app.config import (
    DEFAULT_SUPPORT_Z_BY_MATERIAL,
    clamp_speed_by_volumetric_flow,
    compute_default_support_xy,
    compute_heterogeneous_speed_cap,
    compute_optimal_temperatures,
    get_machine_thermal_kinematic_limits,
    get_printer_config,
    get_slot_volumetric_limit,
    load_catalog,
    negotiate_multimaterial_bed_temp,
    resolve_profile_id,
)
from app.models.schemas import (
    AIAnalyzeModelRequest,
    AIAnalyzeModelResponse,
    AIDefectDiagnoseRequest,
    AIDefectDiagnoseResponse,
    AILayerResolutionGroup,
    AIOptimizeSliceRequest,
    AIOptimizeSliceResponse,
    AIOrientationsResponse,
    AIPresetOption,
    AISubOption,
    AIRecommendRequest,
    AIRecommendResponse,
    AISupportOrientResponse,
    AITelemetryDiagnosisResponse,
    MeshAnalysisResponse,
    OrientationOption,
    OrientationRotation,
    PostPrintCompendium,
    PrinterLiveStatus,
    TelemetrySessionSummary,
)


def _compute_adhesion_recommendation(
    material: str,
    height_z_mm: float,
    base_area_mm2: float,
) -> tuple[str, float, str]:
    """Calcula adherencia óptima (none / brim 4-10 mm / raft minimalista) para cama PEI texturizada."""
    slenderness = height_z_mm / max(math.sqrt(base_area_mm2), 1.0)
    if (base_area_mm2 < 80.0 and height_z_mm > 80.0) or (base_area_mm2 < 50.0 and height_z_mm > 45.0):
        return (
            "raft",
            6.0,
            f"Balsa Minimalista 2 capas · Apoyo puntual ({base_area_mm2:.0f} mm²)",
        )
    if base_area_mm2 >= 600.0 and material in ("pla", "petg") and slenderness <= 4.5:
        return (
            "none",
            0.0,
            f"Sin Balsa · Base estable {base_area_mm2:,.0f} mm²",
        )
    if material == "abs" or base_area_mm2 < 100.0:
        bw = 10.0
    elif base_area_mm2 < 220.0:
        bw = 8.0
    elif base_area_mm2 < 450.0:
        bw = 6.0
    else:
        bw = 4.0
    return (
        "brim",
        bw,
        f"Brim Exterior {int(bw)} mm · Gap 0.12 mm",
    )


def _hex_luminance(hex_color: str) -> float:
    clean = hex_color.strip().lstrip("#")
    if len(clean) != 6:
        return 0.5
    try:
        r = int(clean[0:2], 16) / 255.0
        g = int(clean[2:4], 16) / 255.0
        b = int(clean[4:6], 16) / 255.0
        return 0.2126 * r + 0.7152 * g + 0.0722 * b
    except ValueError:
        return 0.5


def _compute_prime_tower_recommendation(
    profile_id: str,
    parts_count: int,
    extruder_colors: list[str],
    detected_extruder_count: int = 1,
    is_multicolor: bool = False,
) -> tuple[bool, str, str]:
    """Evalúa si la Torre de Purga es necesaria en Creator 5 Pro (4 cabezales independientes)."""
    if profile_id != "creator5_pro":
        return False, "off", ""
    eff_colors_count = max(parts_count, detected_extruder_count, 2 if is_multicolor else 1)
    if eff_colors_count <= 1:
        return (
            False,
            "off",
            "Torre de Purga: Desactivada (Ahorro 4 cabezales · pieza monocromo)",
        )
    lums = [_hex_luminance(c) for c in extruder_colors if c]
    contrast = (max(lums) - min(lums)) if len(lums) >= 2 else 0.0
    if contrast >= 0.45 or eff_colors_count >= 3:
        return (
            True,
            "ultra_save",
            "Activada Ultra-Ahorro 20mm + Purga en Relleno",
        )
    return (
        False,
        "off",
        "Torre de Purga: Desactivada (Ahorro 4 cabezales · cabezales independientes)",
    )


def _heuristic_recommend(req: AIRecommendRequest) -> AIRecommendResponse:
    """Sistema experto local con regla #1 'Cero Soportes Primero' y soporte especializado Litofanía."""
    printer = get_printer_config(req.printer_id)
    eff_material = "pla" if req.lithophane_mode else req.material
    temps = compute_optimal_temperatures(
        printer_id=req.printer_id,
        material=eff_material,
        high_speed=req.high_speed_filament,
        nozzle_diameter=req.nozzle_diameter,
    )
    nozzle_init = temps["nozzle_temp_initial_layer"]
    nozzle_norm = temps["nozzle_temp"]
    base_bed = temps["bed_temp"]

    if printer.profile_id == "creator5_pro" and req.extruders_config:
        slot_mats = [s.material for s in req.extruders_config]
        if len({m for m in slot_mats if m != "soporte"}) > 1:
            base_bed = negotiate_multimaterial_bed_temp(slot_mats)

    if req.lithophane_mode:
        dx, dy, dz = req.dimensions_mm.x, req.dimensions_mm.y, req.dimensions_mm.z
        suggest_reorient = False
        rec_rx: float | None = None
        rec_ry: float | None = None
        rec_rz: float | None = None
        orient_note = "Orientación vertical lista para litofanía."
        if dz < max(dx, dy) * 0.45 and dz < 30.0:
            suggest_reorient = True
            rec_rx = 90.0
            orient_note = "Coloca la litofanía en posición vertical (rot_x=90°) para máxima definición."
        elif printer.profile_id == "ender3_s1_pro" and dx > dy * 1.25:
            suggest_reorient = True
            rec_rz = 90.0
            orient_note = "Alinea la litofanía paralela al eje Y (rot_z=90°) para evitar balanceo en Ender 3 S1 Pro."

        pt_enabled, pt_mode, pt_reason = _compute_prime_tower_recommendation(
            printer.profile_id,
            req.multimaterial_parts_count,
            req.extruder_colors,
            detected_extruder_count=req.detected_extruder_count,
            is_multicolor=req.is_multicolor,
        )
        return AIRecommendResponse(
            supports=False,
            support_type="tree(auto)",
            support_on_build_plate_only=True,
            support_z_distance=0.20,
            support_xy_distance=compute_default_support_xy("pla", req.nozzle_diameter),
            adhesion_type="brim",
            brim_width_mm=8.0,
            adhesion_label="Brim Exterior 8 mm · Gap 0.12 mm (Litofanía)",
            prime_tower_enabled=pt_enabled,
            prime_tower_mode=pt_mode,  # type: ignore[arg-type]
            prime_tower_reason=pt_reason,
            nozzle_temp_initial_layer=nozzle_init,
            nozzle_temp=nozzle_norm,
            bed_temp=base_bed,
            quality_preset="estandar",
            reasoning=f"Modo Litofanía (PLA): soportes desactivados sobre la cara de imagen, brim exterior 8 mm y relleno 99% rectilíneo. {orient_note}",
            provider="HEURISTICA_LOCAL",
            suggest_reorient=suggest_reorient,
            recommended_rot_x=rec_rx,
            recommended_rot_y=rec_ry,
            recommended_rot_z=rec_rz,
        )

    # Regla #1: Cero Soportes Primero (tolerancia de puente/voladizo <= 2.5%)
    zero_supports_ok = req.overhang_ratio <= 0.025
    needs_supports = not zero_supports_ok
    suggest_reorient = req.overhang_ratio > 0.04
    support_type = "tree(auto)" if req.overhang_ratio <= 0.25 else "normal(auto)"
    on_plate_only = req.overhang_ratio < 0.09
    z_dist = float(DEFAULT_SUPPORT_Z_BY_MATERIAL.get(req.material, 0.20))
    xy_dist = compute_default_support_xy(req.material, req.nozzle_diameter)

    adhesion, brim_w, adhesion_lbl = _compute_adhesion_recommendation(
        req.material, req.dimensions_mm.z, req.base_contact_area_mm2
    )
    pt_enabled, pt_mode, pt_reason = _compute_prime_tower_recommendation(
        printer.profile_id,
        req.multimaterial_parts_count,
        req.extruder_colors,
        detected_extruder_count=req.detected_extruder_count,
        is_multicolor=req.is_multicolor,
    )

    max_dim = max(req.dimensions_mm.x, req.dimensions_mm.y, req.dimensions_mm.z)
    if req.material == "tpu":
        preset = "estandar"
    elif max_dim > 180.0 and req.nozzle_diameter >= 0.4 and printer.max_volumetric_flow_mm3_s >= 28.0:
        preset = "rapidez_extrema"
    elif req.high_speed_filament and printer.max_volumetric_flow_mm3_s >= 24.0:
        preset = "alta_velocidad"
    else:
        preset = "estandar"

    notes: list[str] = []
    if zero_supports_ok:
        notes.append(
            "Regla Cero Soportes Primero: voladizos mínimos (<=2.5%), pieza autosoportada sin soportes."
        )
    else:
        origin_label = "solo placa" if on_plate_only else "figura y placa"
        reorient_hint = "Prueba 'Auto-Orientar sin Escalar' si deseas intentar reducirlos. "
        notes.append(
            f"{reorient_hint}Voladizos del {req.overhang_ratio * 100:.1f}% exigen soportes {support_type} ({origin_label}) con Z={z_dist:.2f} mm."
        )

    if adhesion == "raft":
        notes.append(f"{adhesion_lbl}.")
    elif adhesion == "brim":
        notes.append(f"{adhesion_lbl}.")
    else:
        notes.append(f"{adhesion_lbl}.")
    if pt_reason:
        notes.append(pt_reason)

    if printer.profile_id == "creator5_pro" and req.extruders_config:
        slot_mats = [s.material for s in req.extruders_config]
        slot_flows = [
            float(s.max_volumetric_speed)
            if s.max_volumetric_speed is not None
            else get_slot_volumetric_limit(req.printer_id, s.material, high_speed=bool(s.high_speed))
            for s in req.extruders_config
        ]
        distinct_body = sorted({m.upper() for m in slot_mats if m != "soporte"})
        if len(distinct_body) > 1:
            sc = compute_heterogeneous_speed_cap(slot_flows, slot_mats, nozzle_diameter=req.nozzle_diameter)
            notes.append(
                f"Multi-material ({'+'.join(distinct_body)}): cama negociada {base_bed}°C y velocidad tope {sc['max_linear_speed']} mm/s ({sc['min_volumetric_flow']} mm³/s)."
            )
            if "PLA" in distinct_body and ("PETG" in distinct_body or "ABS" in distinct_body):
                notes.append("Alerta: PLA y PETG/ABS tienen baja adhesión estructural entre sí.")
        else:
            notes.append(f"Temperaturas automáticas: 1.ª capa {nozzle_init}°C → impresión {nozzle_norm}°C.")
    else:
        notes.append(f"Temperaturas automáticas: 1.ª capa {nozzle_init}°C → impresión {nozzle_norm}°C.")

    return AIRecommendResponse(
        supports=needs_supports,
        support_type=support_type,
        support_on_build_plate_only=on_plate_only,
        support_z_distance=z_dist,
        support_xy_distance=xy_dist,
        adhesion_type=adhesion,
        brim_width_mm=brim_w,
        adhesion_label=adhesion_lbl,
        prime_tower_enabled=pt_enabled,
        prime_tower_mode=pt_mode,  # type: ignore[arg-type]
        prime_tower_reason=pt_reason,
        nozzle_temp_initial_layer=nozzle_init,
        nozzle_temp=nozzle_norm,
        bed_temp=base_bed,
        quality_preset=preset,
        reasoning=" ".join(notes),
        provider="HEURISTICA_LOCAL",
        suggest_reorient=suggest_reorient,
    )


def _build_prompt(req: AIRecommendRequest, fallback: AIRecommendResponse) -> str:
    printer = get_printer_config(req.printer_id)
    eff_mat = "pla" if req.lithophane_mode else req.material
    learnings_ctx: dict[str, Any] | None = None
    try:
        from app.core.print_telemetry_recorder import get_machine_material_learnings

        learnings = get_machine_material_learnings(req.printer_id, eff_mat, limit=3)
        if learnings.runs_count > 0:
            learnings_ctx = {
                "runs_count": learnings.runs_count,
                "avg_real_nozzle_c": learnings.avg_nozzle_temp,
                "avg_real_bed_c": learnings.avg_bed_temp,
                "avg_real_speed_mms": learnings.avg_speed_mms,
                "avg_mcu_max_c": learnings.avg_mcu_max,
                "accumulated_improvements": learnings.accumulated_improvements,
            }
    except Exception:
        learnings_ctx = None

    slots_summary = [
        {
            "extruder": f"T{s.extruder_index}",
            "material": s.material,
            "high_speed": s.high_speed,
            "spool_min_c": s.spool_min,
            "spool_max_c": s.spool_max,
            "nozzle_temp_initial_layer": s.nozzle_temp_initial_layer,
            "nozzle_temp": s.nozzle_temp,
            "max_volumetric_speed_mm3_s": (
                s.max_volumetric_speed
                if s.max_volumetric_speed is not None
                else get_slot_volumetric_limit(req.printer_id, s.material, high_speed=s.high_speed)
            ),
            "usage_pct": req.extruder_triangle_percentages.get(f"T{s.extruder_index}"),
        }
        for s in req.extruders_config
    ]
    payload = {
        "printer": {
            "id": printer.printer_id,
            "name": printer.display_name,
            "vendor": printer.vendor,
            "model_name": printer.model_name,
            "bed_shape": printer.bed_shape,
            "gcode_flavor": printer.gcode_flavor,
            "kinematics": printer.kinematics,
            "estimated_q_max": printer.max_volumetric_flow_mm3_s,
            "max_volumetric_flow_mm3_s": printer.max_volumetric_flow_mm3_s,
            "is_multicolor": printer.is_multicolor,
            "tool_count": printer.extruder_slots,
            "has_heated_chamber": printer.has_heated_chamber,
            "is_high_speed": printer.is_high_speed,
            "nozzle_diameter": req.nozzle_diameter,
        },
        "material": "pla" if req.lithophane_mode else req.material,
        "nozzle_diameter_mm": req.nozzle_diameter,
        "high_speed_filament": req.high_speed_filament,
        "lithophane_mode": req.lithophane_mode,
        "multimaterial_parts_count": req.multimaterial_parts_count,
        "detected_extruder_count": req.detected_extruder_count,
        "is_multicolor": req.is_multicolor,
        "extruder_colors": req.extruder_colors,
        "extruder_triangle_percentages": req.extruder_triangle_percentages,
        "extruders_t0_t3": slots_summary,
        "past_real_learnings": learnings_ctx,
        "bed_surface": "PEI texturizado",
        "mesh_metrics": {
            "dimensions_mm": req.dimensions_mm.model_dump(),
            "overhang_ratio": req.overhang_ratio,
            "base_contact_area_mm2": req.base_contact_area_mm2,
            "is_watertight": req.is_watertight,
        },
    }
    return (
        "Eres un ingeniero experto en impresión 3D FDM. REGLA ESTRICTA DE PRIORIDAD:\n"
        "1) 'CERO SOPORTES PRIMERO': Evalúa primero si rotando la pieza o aprovechando puentes (overhang_ratio <= 0.025) "
        "se pueden eliminar los soportes por completo (supports=false). Si overhang_ratio > 0.025 pero rotar ayudaría, indica suggest_reorient=true.\n"
        "2) Si la geometría exige soportes obligatoriamente, activa el desprendimiento más limpio según material: "
        "PETG support_z_distance=0.30 / support_xy_distance=0.60, PLA=0.20/0.50, ABS=0.24/0.55, TPU=0.28/0.60.\n"
        "3) Adherencia en cama PEI texturizada: usa 'none' si base_contact_area_mm2 >= 600 en PLA/PETG; usa 'brim' (brim_width_mm entre 4 y 10 mm) si la base es mediana/estrecha o ABS; usa 'raft' solo si es apoyo puntual (<80 mm² y Z>80mm).\n"
        "4) En Creator 5 Pro (4 cabezales independientes T0-T3): revisa tanto detected_extruder_count/is_multicolor (un .3mf pintado por triángulo puede tener 1 objeto con 4 colores) como multimaterial_parts_count. Si es monocromo (detected_extruder_count<=1 y !is_multicolor), pon prime_tower_enabled=false y prime_tower_mode='off'; si hay >=3 colores o alto contraste (ej. Blanco+Negro/Rojo/Naranja), usa prime_tower_enabled=true y prime_tower_mode='ultra_save'.\n"
        + (
            "5) APRENDIZAJE REAL DE CORRIDAS PREVIAS DISPONIBLE: si past_real_learnings no es null, ajusta temperaturas/velocidad/soporte considerando lo que funcionó y las mejoras acumuladas en impresiones físicas anteriores de esta misma máquina y material.\n"
            if learnings_ctx
            else ""
        )
        + (
            "6) MODO LITOFANÍA ACTIVO: NUNCA actives soportes sobre la cara de imagen (supports=false siempre), exige brim exterior de 8 a 10 mm ('brim', brim_width_mm=8) y verifica que la pieza esté vertical (y paralela al eje Y si printer.id=='ender3_s1_pro').\n"
            if req.lithophane_mode
            else ""
        )
        + "Responde ÚNICAMENTE con JSON válido con estas claves exactas: "
        "supports (bool), support_type ('tree(auto)'|'normal(auto)'), support_on_build_plate_only (bool), "
        "support_z_distance (float), support_xy_distance (float), adhesion_type ('none'|'brim'|'raft'), brim_width_mm (float 4-10), "
        "prime_tower_enabled (bool), prime_tower_mode ('off'|'ultra_save'), prime_tower_reason (string max 100 chars), "
        "nozzle_temp_initial_layer (int), nozzle_temp (int), bed_temp (int), quality_preset ('estandar'|'mecanico_resistente'|'alta_velocidad'|'rapidez_extrema'), "
        "suggest_reorient (bool), recommended_rot_x (float|null), recommended_rot_y (float|null), recommended_rot_z (float|null), "
        "reasoning (string conciso en español, max 240 chars).\n"
        f"Contexto: {json.dumps(payload, ensure_ascii=False)}\n"
        f"Referencia base: {json.dumps(fallback.model_dump(exclude={'provider', 'reasoning'}), ensure_ascii=False)}"
    )


def _merge_llm_response(
    raw_json: dict[str, Any],
    fallback: AIRecommendResponse,
    provider: str,
    lithophane_mode: bool = False,
) -> AIRecommendResponse:
    valid_presets = {"estandar", "mecanico_resistente", "alta_velocidad", "rapidez_extrema"}
    valid_sup_types = {"tree(auto)", "normal(auto)"}
    valid_adhesion = {"none", "brim", "raft"}

    sup_type = raw_json.get("support_type", fallback.support_type)
    if sup_type not in valid_sup_types:
        sup_type = fallback.support_type

    adhesion = raw_json.get("adhesion_type", fallback.adhesion_type)
    if adhesion not in valid_adhesion:
        adhesion = fallback.adhesion_type

    preset = raw_json.get("quality_preset", fallback.quality_preset)
    if preset not in valid_presets:
        preset = fallback.quality_preset

    z_dist = float(raw_json.get("support_z_distance", fallback.support_z_distance))
    z_dist = round(max(0.12, min(0.45, z_dist)), 2)
    xy_dist = float(raw_json.get("support_xy_distance", fallback.support_xy_distance))
    xy_dist = round(max(0.25, min(1.50, xy_dist)), 2)

    init_t = int(raw_json.get("nozzle_temp_initial_layer", fallback.nozzle_temp_initial_layer))
    norm_t = int(raw_json.get("nozzle_temp", fallback.nozzle_temp))
    bed_t = int(raw_json.get("bed_temp", fallback.bed_temp))

    def _opt_float(key: str) -> float | None:
        v = raw_json.get(key)
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    try:
        brim_w = round(max(4.0, min(10.0, float(raw_json.get("brim_width_mm", fallback.brim_width_mm)))), 1)
    except (TypeError, ValueError):
        brim_w = fallback.brim_width_mm

    if adhesion == "raft":
        adhesion_lbl = fallback.adhesion_label if fallback.adhesion_type == "raft" else "Balsa Minimalista 2 capas"
    elif adhesion == "brim":
        adhesion_lbl = f"Brim Exterior {int(round(brim_w))} mm · Gap 0.12 mm"
    else:
        adhesion_lbl = fallback.adhesion_label if fallback.adhesion_type == "none" else "Sin Balsa · Base estable"

    eff_supports = False if lithophane_mode else bool(raw_json.get("supports", fallback.supports))
    if lithophane_mode:
        adhesion = "brim"
        brim_w = round(max(8.0, min(10.0, brim_w)), 1)
        adhesion_lbl = f"Brim Exterior {int(round(brim_w))} mm · Gap 0.12 mm (Litofanía)"

    if fallback.prime_tower_enabled:
        pt_enabled = True
        pt_mode = "ultra_save"
        pt_reason = fallback.prime_tower_reason
    else:
        pt_enabled = bool(raw_json.get("prime_tower_enabled", fallback.prime_tower_enabled))
        pt_mode_raw = raw_json.get("prime_tower_mode", fallback.prime_tower_mode)
        pt_mode = pt_mode_raw if pt_mode_raw in ("off", "ultra_save") else ("ultra_save" if pt_enabled else "off")
        pt_reason = str(raw_json.get("prime_tower_reason") or fallback.prime_tower_reason)[:120]

    return AIRecommendResponse(
        supports=eff_supports,
        support_type=sup_type,
        support_on_build_plate_only=bool(
            raw_json.get("support_on_build_plate_only", fallback.support_on_build_plate_only)
        ),
        support_z_distance=z_dist,
        support_xy_distance=xy_dist,
        adhesion_type=adhesion,
        brim_width_mm=brim_w,
        adhesion_label=adhesion_lbl,
        prime_tower_enabled=pt_enabled,
        prime_tower_mode=pt_mode,  # type: ignore[arg-type]
        prime_tower_reason=pt_reason,
        nozzle_temp_initial_layer=max(170, min(310, init_t)),
        nozzle_temp=max(170, min(310, norm_t)),
        bed_temp=max(0, min(120, bed_t)),
        quality_preset=preset,
        reasoning=str(raw_json.get("reasoning") or fallback.reasoning)[:260],
        provider=provider,  # type: ignore[arg-type]
        suggest_reorient=bool(raw_json.get("suggest_reorient", fallback.suggest_reorient)),
        recommended_rot_x=_opt_float("recommended_rot_x"),
        recommended_rot_y=_opt_float("recommended_rot_y"),
        recommended_rot_z=_opt_float("recommended_rot_z"),
    )


def _call_gemini(prompt: str, api_key: str) -> dict[str, Any]:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-2.5-flash:generateContent?key={api_key}"
    )
    body = json.dumps(
        {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def _call_deepseek(prompt: str, api_key: str) -> dict[str, Any]:
    url = "https://api.deepseek.com/chat/completions"
    body = json.dumps(
        {
            "model": "deepseek-chat",
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["choices"][0]["message"]["content"]
    return json.loads(text)


def generate_ai_recommendation(req: AIRecommendRequest) -> AIRecommendResponse:
    """Consulta Gemini o DeepSeek si hay API key en entorno; si no, usa el motor heurístico."""
    fallback = _heuristic_recommend(req)
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()

    if gemini_key:
        try:
            raw = _call_gemini(_build_prompt(req, fallback), gemini_key)
            return _merge_llm_response(raw, fallback, "GEMINI_API", lithophane_mode=req.lithophane_mode)
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            pass

    if deepseek_key:
        try:
            raw = _call_deepseek(_build_prompt(req, fallback), deepseek_key)
            return _merge_llm_response(raw, fallback, "DEEPSEEK_API", lithophane_mode=req.lithophane_mode)
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            pass

    return fallback


def generate_ai_support_decision(
    printer_id: str,
    material: str,
    nozzle_diameter: float,
    high_speed_filament: bool,
    mesh_id: str,
    best_euler: tuple[float, float, float],
    effective_scale: float,
    metrics: dict[str, Any],
    analysis: MeshAnalysisResponse,
    current_support_config: dict[str, Any] | None = None,
    current_slice_metrics: dict[str, Any] | None = None,
    lithophane_mode: bool = False,
) -> AISupportOrientResponse:
    """Evalúa con DeepSeek API si la pieza orientada requiere soportes o basta con puentes."""
    printer = get_printer_config(printer_id)
    bridge_speed = 25 if printer.profile_id == "ender3_s1_pro" else 35
    z_dist_default = float(DEFAULT_SUPPORT_Z_BY_MATERIAL.get(material, 0.20))
    xy_dist_default = compute_default_support_xy(material, nozzle_diameter)

    overhang_pct = round(analysis.overhang_ratio * 100.0, 2)
    detail_prot = float(metrics.get("detail_protected_pct", 100.0))
    apply_rotation = bool(metrics.get("apply_rotation", True))
    est_time_min = float(metrics.get("estimated_time_min", 0.0))
    est_sup_g = float(metrics.get("estimated_support_grams", 0.0))
    current_cand = metrics.get("current_candidate") or {}
    top_cands = metrics.get("top_candidates") or []

    # Tabla comparativa: Candidato #0 (actual) + Top 3 candidatos
    comparison_table: list[dict[str, Any]] = []
    seen_cmp: set[tuple[float, float, float]] = set()
    for idx_c, cand in enumerate(([current_cand] if current_cand else []) + list(top_cands)):
        if not isinstance(cand, dict):
            continue
        key = (
            float(cand.get("rot_x", 0.0)),
            float(cand.get("rot_y", 0.0)),
            float(cand.get("rot_z", 0.0)),
        )
        if key in seen_cmp:
            continue
        seen_cmp.add(key)
        comparison_table.append(
            {
                "label": "ACTUAL_USUARIO" if cand.get("is_current") else f"CANDIDATO_{idx_c}",
                "rot_x": key[0],
                "rot_y": key[1],
                "rot_z": key[2],
                "height_z_mm": cand.get("height_z_mm"),
                "base_contact_area_mm2": cand.get("base_contact_area_mm2"),
                "overhang_pct": round(float(cand.get("overhang_ratio", 0.0)) * 100.0, 1),
                "estimated_support_grams": cand.get("estimated_support_grams"),
                "estimated_time_min": cand.get("estimated_time_min"),
                "estimated_time_score": cand.get("estimated_time_score"),
                "fits": cand.get("fits", True),
            }
        )

    heuristic_needs = False if lithophane_mode else not (
        analysis.overhang_ratio <= 0.032 and float(metrics.get("steep_overhang_ratio", 0.0)) <= 0.025
    )
    heuristic_sup_type = "tree(auto)" if analysis.overhang_ratio <= 0.28 else "normal(auto)"
    heuristic_plate_only = analysis.overhang_ratio < 0.12
    heuristic_adhesion, heuristic_brim_w, heuristic_adhesion_lbl = _compute_adhesion_recommendation(
        "pla" if lithophane_mode else material,
        analysis.dimensions_mm.z,
        analysis.base_contact_area_mm2,
    )
    if lithophane_mode:
        heuristic_adhesion = "brim"
        heuristic_brim_w = round(max(8.0, min(10.0, heuristic_brim_w)), 1)
        heuristic_adhesion_lbl = f"Brim Exterior {int(round(heuristic_brim_w))} mm · Gap 0.12 mm (Litofanía)"

    heuristic_zone = (
        "Cara vertical de litofanía protegida sin soportes; brim 8 mm en base"
        if lithophane_mode
        else (
            "Puentes horizontales cortos autosoportados"
            if not heuristic_needs
            else f"Voladizos >48° ({overhang_pct:.1f}% del área; base {analysis.base_contact_area_mm2:.0f} mm²)"
        )
    )

    context = {
        "printer": {
            "id": printer.printer_id,
            "name": printer.display_name,
            "bridge_speed_mm_s": bridge_speed,
            "bridge_flow": 0.92,
            "thick_bridges": 1,
            "overhang_fan_speed": 100,
        },
        "material": "pla" if lithophane_mode else material,
        "nozzle_diameter_mm": nozzle_diameter,
        "high_speed_filament": high_speed_filament,
        "lithophane_mode": lithophane_mode,
        "apply_rotation_recommended": apply_rotation,
        "current_support_config": current_support_config or {},
        "current_slice_baseline": current_slice_metrics or {},
        "candidates_comparison": comparison_table,
        "selected_pose": {
            "rot_x": best_euler[0],
            "rot_y": best_euler[1],
            "rot_z": best_euler[2],
            "scale_percent": effective_scale,
            "dimensions_mm": analysis.dimensions_mm.model_dump(),
            "base_contact_area_mm2": analysis.base_contact_area_mm2,
            "overhang_ratio": analysis.overhang_ratio,
            "estimated_time_min": est_time_min,
            "estimated_support_grams": est_sup_g,
            "detail_protected_pct": detail_prot,
            "is_multimaterial": metrics.get("is_multimaterial", False),
        },
    }

    prompt = (
        "Eres el ingeniero jefe de impresión 3D FDM en Nikk Slider (Flash Studio / OrcaSlicer).\n"
        "Compara la orientación ACTUAL_USUARIO frente a los mejores candidatos físicos (altura Z, estabilidad de base y volumen de soporte).\n"
        f"Puentes optimizados activos: velocidad de puente {bridge_speed} mm/s, flujo 0.92, ventilación al 100%.\n"
        "REGLAS ESTRICTAS DE DECISIÓN:\n"
        "1) NUNCA empeores el tiempo ni dispares la altura Z respecto a ACTUAL_USUARIO cuando ACTUAL_USUARIO ya cabe en cama.\n"
        "2) Si `apply_rotation_recommended` es false, mantén `keep_current_orientation=true`.\n"
        "3) Si los voladizos son <= 3.2%, decide supports_required=false; si superan el 3.2%, decide supports_required=true ('tree(auto)' para orgánicas o 'normal(auto)' para rectas).\n"
        f"4) Usa support_z_distance={z_dist_default:.2f} mm y support_xy_distance={xy_dist_default:.2f} mm para {material.upper()}, más adhesion_type ('none'|'brim'|'raft').\n"
        + (
            "5) MODO LITOFANÍA OBLIGATORIO: la pieza es una litofanía. NUNCA actives soportes sobre la cara de imagen (supports_required=false siempre). Verifica que esté en postura vertical (y en ender3_s1_pro paralela al eje Y para evitar balanceo de cama) y mantén adhesion_type='brim' de 8–10 mm.\n"
            if lithophane_mode
            else ""
        )
        + "REGLAS DE REDACCIÓN EN ESPAÑOL HUMANO Y CLARO:\n"
        "- PROHIBIDO mencionar cadenas técnicas o internas como 'Candidato 1', '0.2588>0.032', 'tree(auto)', porcentajes heurísticos inventados o comparativas en minutos estimados ('16.1 min vs 20.5 min').\n"
        "- En `critical_zone_description`: describe brevemente en español qué zonas requieren atención (máx 110 chars).\n"
        "- En `reasoning`: explica en 2 líneas claras qué se ajustó (rotación, tipo de soporte en árbol/normal, separación Z/XY, brim) y por qué protege o agiliza esta pieza.\n"
        "- En `estimated_savings_summary`: resumen humano sin inventar tiempos del slicer (máx 120 chars).\n"
        "Responde ÚNICAMENTE JSON válido con estas claves exactas: "
        "keep_current_orientation (bool), supports_required (bool), support_type ('tree(auto)'|'normal(auto)'), "
        "support_on_build_plate_only (bool), support_z_distance (float), support_xy_distance (float), adhesion_type ('none'|'brim'|'raft'), "
        "estimated_savings_summary (string), critical_zone_description (string), reasoning (string).\n"
        f"Contexto geométrico: {json.dumps(context, ensure_ascii=False)}"
    )

    provider = "HEURISTICA_LOCAL"
    raw_json: dict[str, Any] | None = None
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if deepseek_key:
        try:
            raw_json = _call_deepseek(prompt, deepseek_key)
            provider = "DEEPSEEK_API"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            raw_json = None
    elif gemini_key:
        try:
            raw_json = _call_gemini(prompt, gemini_key)
            provider = "GEMINI_API"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            raw_json = None

    if raw_json is not None:
        sup_req = bool(raw_json.get("supports_required", heuristic_needs))
        sup_type = raw_json.get("support_type", heuristic_sup_type)
        if sup_type not in ("tree(auto)", "normal(auto)"):
            sup_type = heuristic_sup_type
        plate_only = bool(raw_json.get("support_on_build_plate_only", heuristic_plate_only))
        try:
            z_d = round(max(0.12, min(0.45, float(raw_json.get("support_z_distance", z_dist_default)))), 2)
        except (TypeError, ValueError):
            z_d = z_dist_default
        try:
            xy_d = round(max(0.25, min(1.50, float(raw_json.get("support_xy_distance", xy_dist_default)))), 2)
        except (TypeError, ValueError):
            xy_d = xy_dist_default
        adh = raw_json.get("adhesion_type", heuristic_adhesion)
        if adh not in ("none", "brim", "raft"):
            adh = heuristic_adhesion
        crit_zone = str(raw_json.get("critical_zone_description") or heuristic_zone).strip()
        reasoning = str(raw_json.get("reasoning") or heuristic_zone).strip()
        savings_summary = str(raw_json.get("estimated_savings_summary") or "").strip()
    else:
        sup_req = heuristic_needs
        sup_type = heuristic_sup_type
        plate_only = heuristic_plate_only
        z_d = z_dist_default
        xy_d = xy_dist_default
        adh = heuristic_adhesion
        crit_zone = heuristic_zone
        savings_summary = ""
        reasoning = (
            f"Ángulo óptimo ({best_euler[0]}°, {best_euler[1]}°, {best_euler[2]}°) con "
            f"{overhang_pct:.1f}% de voladizos; detalles protegidos al {detail_prot:.0f}%."
        )

    if not savings_summary:
        if apply_rotation:
            savings_summary = "Nueva orientación y soportes listos para validar con el laminador real."
        else:
            savings_summary = "Se conserva la orientación actual de menor altura y mayor estabilidad."

    if lithophane_mode:
        sup_req = False
        adh = "brim"
        badge_status = "SIN_SOPORTES"
        badge_label = "MODO LITOFANÍA · SIN SOPORTES + BRIM 8 MM"
    elif not apply_rotation:
        badge_status = "SIN_SOPORTES" if not sup_req else "SOPORTES_OBLIGATORIOS"
        badge_label = "Orientación Actual Confirmada"
    elif not sup_req:
        badge_status = "SIN_SOPORTES"
        badge_label = "SIN SOPORTES (Puentes + Ángulo Óptimo)"
    else:
        badge_status = "SOPORTES_OBLIGATORIOS"
        badge_label = "SOPORTES OBLIGATORIOS ACTIVADOS"

    return AISupportOrientResponse(
        mesh_id=mesh_id,
        rot_x=best_euler[0],
        rot_y=best_euler[1],
        rot_z=best_euler[2],
        scale_percent=effective_scale,
        apply_rotation=apply_rotation,
        estimated_time_min=est_time_min,
        estimated_support_grams=est_sup_g,
        estimated_savings_summary=savings_summary,
        supports_required=sup_req,
        badge_status=badge_status,
        badge_label=badge_label,
        support_type=sup_type,  # type: ignore[arg-type]
        support_on_build_plate_only=plate_only,
        support_z_distance=z_d,
        support_xy_distance=xy_d,
        adhesion_type=adh,  # type: ignore[arg-type]
        brim_width_mm=heuristic_brim_w,
        adhesion_label=heuristic_adhesion_lbl,
        critical_zone_description=crit_zone,
        reasoning=reasoning,
        provider=provider,  # type: ignore[arg-type]
        analysis=analysis,
    )


def diagnose_live_telemetry(status: PrinterLiveStatus) -> AITelemetryDiagnosisResponse:
    """Analiza telemetría en tiempo real con DeepSeek API (y fallback heurístico)."""
    telemetry_ctx = {
        "printer_id": status.printer_id,
        "display_name": status.display_name,
        "protocol": status.protocol,
        "state": status.state,
        "nozzle_temp": status.nozzle_temp,
        "nozzle_target": status.nozzle_target,
        "bed_temp": status.bed_temp,
        "bed_target": status.bed_target,
        "progress_percent": status.progress_percent,
        "current_file": status.current_file,
        "current_layer": status.current_layer,
        "total_layers": status.total_layers,
        "print_speed_mms": status.print_speed_mms,
        "speed_factor_percent": status.speed_factor_percent,
        "flow_factor_percent": status.flow_factor_percent,
        "fan_speed_percent": status.fan_speed_percent,
        "mcu_temp": status.mcu_temp,
        "host_temp": status.host_temp,
        "chamber_temp": status.chamber_temp,
        "chamber_target": status.chamber_target,
        "chamber_mode": status.chamber_mode,
        "filament_used_g": status.filament_used_g,
        "elapsed_seconds": status.elapsed_seconds,
        "eta_seconds": status.eta_seconds,
    }

    # Diagnóstico heurístico base
    recs: list[str] = []
    badge: str = "OPTIMO"
    if not status.online:
        badge = "CRITICO"
        summary = f"{status.display_name} está fuera de línea ({status.message})."
        recs = [
            "Verifica alimentación eléctrica y conectividad Wi-Fi/LAN de la máquina.",
            "Ejecuta 'Auto-Descubrir en Red' en Configuración si cambió la IP DHCP.",
        ]
    else:
        noz_diff = (
            abs((status.nozzle_temp or 0.0) - (status.nozzle_target or 0.0))
            if status.nozzle_target and status.nozzle_target > 0
            else 0.0
        )
        bed_diff = (
            abs((status.bed_temp or 0.0) - (status.bed_target or 0.0))
            if status.bed_target and status.bed_target > 0
            else 0.0
        )
        if status.mcu_temp is not None and status.mcu_temp >= 65.0:
            badge = "ATENCION"
            recs.append(
                f"MCU a {status.mcu_temp}°C elevado; revisa ventilación de electrónica."
            )
        if noz_diff > 6.0 or bed_diff > 6.0:
            badge = "ATENCION"
            recs.append(
                f"Desviación térmica detectada (boquilla Δ{noz_diff:.1f}°C, cama Δ{bed_diff:.1f}°C); vigila estabilidad PID."
            )
        if status.chamber_temp is not None:
            is_pla_tpu = (
                status.chamber_mode == "extraction"
                or (status.chamber_target is not None and status.chamber_target <= 35)
                or (status.nozzle_target is not None and 0 < status.nozzle_target <= 225)
            )
            is_abs_asa = (
                status.chamber_mode == "preheat_closed"
                or (status.chamber_target is not None and status.chamber_target >= 48)
                or (status.bed_target is not None and status.bed_target >= 95)
            )
            if is_pla_tpu and status.chamber_temp > 36.0:
                badge = "CRITICO" if status.chamber_temp >= 40.0 else "ATENCION"
                recs.append(
                    f"Cabina a {status.chamber_temp:.1f}°C (>36°C con PLA/TPU): riesgo de atasco por heat creep; activa extracción o abre puerta superior."
                )
            elif is_abs_asa and status.state == "printing" and status.chamber_temp < 42.0:
                badge = "ATENCION"
                recs.append(
                    f"Cabina a {status.chamber_temp:.1f}°C (<42°C con ABS/ASA): riesgo de warping/delaminación; mantén cámara cerrada."
                )
        if status.state == "printing":
            if status.current_layer is not None and status.current_layer <= 2 and status.fan_speed_percent > 30:
                badge = "ATENCION"
                recs.append(
                    "Capa inicial con ventilador >30%: reduce ventilación de capa al 0–20% para mejorar adherencia."
                )
            elif status.fan_speed_percent == 0 and (status.current_layer or 0) > 3 and (status.nozzle_target or 0) <= 225:
                recs.append(
                    "Si imprimes PLA pasado la capa 3 con ventilador en 0%, sube ventilación al 70–100% para evitar stringing."
                )
            if status.speed_factor_percent > 115:
                recs.append(
                    f"Velocidad al {status.speed_factor_percent:.0f}%: verifica flujo ({status.flow_factor_percent:.0f}%) y aumenta +5°C si notas subextrusión."
                )
            if not recs:
                recs = [
                    "Estabilidad térmica de boquilla y cama dentro de rango objetivo.",
                    "Flujo al 100% y velocidad acordes a la cinemática de la impresora.",
                ]
            summary = (
                f"{status.display_name} imprimiendo '{status.current_file or 'trabajo activo'}' "
                f"({status.progress_percent:.1f}%)"
                + (f", capa {status.current_layer}/{status.total_layers}." if status.total_layers else ".")
            )
        else:
            if not recs:
                recs = [
                    f"Máquina en reposo ({status.state}) lista para recibir trabajo desde el Wizard o Memoria.",
                    "Luz, sensores de temperatura y comunicación de red operando con normalidad.",
                ]
            summary = (
                f"{status.display_name} en línea en estado '{status.state}' "
                f"(boquilla {status.nozzle_temp or 0}°C, cama {status.bed_temp or 0}°C)."
            )

    prompt = (
        "Eres el ingeniero jefe de diagnóstico en vivo para una granja de impresión 3D FDM.\n"
        "Analiza esta telemetría real en vivo y responde ÚNICAMENTE JSON válido con las claves exactas:\n"
        "status_badge ('OPTIMO' | 'ATENCION' | 'CRITICO'), "
        "summary (string español claro max 160 chars), "
        "recommendations (array de 2 a 3 strings en español concisos con ajustes accionables: velocidad, flujo, ventilador o temperaturas).\n"
        f"Telemetría actual: {json.dumps(telemetry_ctx, ensure_ascii=False)}"
    )

    provider = "HEURISTICA_LOCAL"
    raw_json: dict[str, Any] | None = None
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if deepseek_key:
        try:
            raw_json = _call_deepseek(prompt, deepseek_key)
            provider = "DEEPSEEK_API"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            raw_json = None
    elif gemini_key:
        try:
            raw_json = _call_gemini(prompt, gemini_key)
            provider = "GEMINI_API"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            raw_json = None

    if raw_json is not None:
        raw_badge = str(raw_json.get("status_badge") or badge).upper()
        if raw_badge in ("OPTIMO", "ATENCION", "CRITICO"):
            badge = raw_badge
        if raw_json.get("summary"):
            summary = str(raw_json["summary"])[:200]
        raw_recs = raw_json.get("recommendations")
        if isinstance(raw_recs, list) and raw_recs:
            recs = [str(r)[:180] for r in raw_recs[:3] if str(r).strip()]

    return AITelemetryDiagnosisResponse(
        printer_id=status.printer_id,
        status_badge=badge,  # type: ignore[arg-type]
        summary=summary,
        recommendations=recs,
        provider=provider,  # type: ignore[arg-type]
    )


def _detect_material_from_session(filename: str, stats: TelemetrySessionSummary) -> str:
    upper = (filename or "").upper()
    for token in ("PETG", "TPU", "ABS", "ASA", "PLA"):
        if token in upper:
            return token
    avg_noz = stats.overall.nozzle_avg or 0.0
    avg_bed = stats.overall.bed_avg or 0.0
    if avg_noz >= 252 or avg_bed >= 90:
        return "ABS"
    if avg_noz >= 232 or avg_bed >= 70:
        return "PETG"
    if 0 < avg_noz <= 230:
        return "PLA"
    return "PLA"


def generate_post_print_compendium(
    session_data: dict[str, Any],
    is_partial: bool = False,
) -> PostPrintCompendium:
    """Genera un Compendio Final (o parcial acumulado) de mejoras con DeepSeek API."""
    printer_id = str(session_data.get("printer_id") or "")
    display_name = str(session_data.get("display_name") or printer_id)
    filename = str(session_data.get("filename") or "trabajo_impresion.gcode")
    session_id = str(session_data.get("session_id") or "")
    raw_stats = session_data.get("live_stats") or session_data.get("stats") or {}
    stats = TelemetrySessionSummary.model_validate(raw_stats)
    detected_material = _detect_material_from_session(filename, stats)

    # Heurística base determinística por si falla red o API key
    anomalies = list(stats.anomalies)
    overall = stats.overall
    rating: str = "EXCELENTE"
    improvements: list[str] = []

    raw_samples = session_data.get("samples") or []
    chamber_vals = [
        float(s["chamber_temp"])
        for s in raw_samples
        if isinstance(s, dict) and s.get("chamber_temp") is not None
    ]
    chamber_avg = round(sum(chamber_vals) / len(chamber_vals), 1) if chamber_vals else None
    chamber_max = round(max(chamber_vals), 1) if chamber_vals else None
    chamber_target = (
        30
        if detected_material in ("PLA", "TPU")
        else 50
        if detected_material in ("ABS", "ASA")
        else 40
    )

    if anomalies or (overall.mcu_max is not None and overall.mcu_max >= 65.0):
        rating = "REQUIERE_AJUSTE" if len(anomalies) >= 2 else "BUENA_CON_MEJORAS"
    elif (
        (overall.nozzle_max is not None and overall.nozzle_min is not None and (overall.nozzle_max - overall.nozzle_min) >= 6.0)
        or (stats.phase_initial_0_5.fan_avg is not None and stats.phase_initial_0_5.fan_avg > 35.0)
        or (detected_material in ("PLA", "TPU") and chamber_max is not None and chamber_max > 36.0)
        or (detected_material in ("ABS", "ASA") and chamber_avg is not None and chamber_avg < 42.0)
    ):
        rating = "BUENA_CON_MEJORAS"

    if detected_material in ("PLA", "TPU") and chamber_max is not None and chamber_max > 36.0:
        improvements.append(
            f"Cabina alcanzó {chamber_max:.1f}°C (>36°C con {detected_material}): riesgo de atasco por heat creep; aumenta extracción (M106 P2) o imprime con puerta entreabierta."
        )
    elif detected_material in ("ABS", "ASA") and chamber_avg is not None and chamber_avg < 42.0:
        improvements.append(
            f"Cabina promedió {chamber_avg:.1f}°C (<42°C con {detected_material}, obj {chamber_target}°C): prolonga precalentamiento con cama cerrada para evitar warping."
        )

    if overall.nozzle_avg is not None and overall.nozzle_min is not None and overall.nozzle_max is not None:
        spread = overall.nozzle_max - overall.nozzle_min
        if spread >= 6.0:
            improvements.append(
                f"Estabiliza PID o sube +4°C la boquilla en cuerpo medio (osciló entre {overall.nozzle_min:.1f}°C y {overall.nozzle_max:.1f}°C)."
            )
    if stats.phase_initial_0_5.fan_avg is not None and stats.phase_initial_0_5.fan_avg > 30.0:
        improvements.append(
            f"Reduce ventilación en primeras capas (0–5%) del {stats.phase_initial_0_5.fan_avg:.0f}% actual a 0–25% para reforzar adherencia."
        )
    if overall.mcu_max is not None:
        if overall.mcu_max < 58.0:
            improvements.append(
                f"MCU muy fresca (máx {overall.mcu_max:.1f}°C): margen seguro para elevar velocidad de relleno al 105–110% en el próximo laminado."
            )
        elif overall.mcu_max >= 65.0:
            improvements.append(
                f"MCU alcanzó {overall.mcu_max:.1f}°C: mejora ventilación de electrónica o limita aceleración en tiradas largas."
            )
    if not improvements:
        improvements = [
            f"Mantén el perfil térmico actual para {detected_material} ({overall.nozzle_avg or 210:.0f}°C boquilla / {overall.bed_avg or 60:.0f}°C cama) dada su alta estabilidad.",
            "Conserva el flujo y ventilación observados; puedes probar +5% de velocidad en relleno manteniendo calidad.",
        ]
    if anomalies and len(improvements) < 4:
        improvements.append(f"Revisar eventos detectados durante la corrida: {anomalies[0]}")

    dur_min = max(1, round((stats.real_elapsed_seconds or stats.duration_recorded_seconds or 60) / 60))
    scope_txt = "parcial acumulada" if is_partial else "completa"
    executive_summary = (
        f"Corrida {scope_txt} en {display_name} para '{filename}' ({detected_material}, {stats.samples_count} muestras, ~{dur_min} min): "
        f"boquilla {overall.nozzle_avg or 0:.1f}°C, cama {overall.bed_avg or 0:.1f}°C"
        + (f", MCU máx {overall.mcu_max:.1f}°C." if overall.mcu_max is not None else ".")
    )

    prompt_ctx = {
        "printer_id": printer_id,
        "display_name": display_name,
        "filename": filename,
        "detected_material": detected_material,
        "chamber_target_c": chamber_target,
        "chamber_avg_c": chamber_avg,
        "chamber_max_c": chamber_max,
        "is_partial": is_partial,
        "progress_pct": session_data.get("last_progress_pct", 0.0),
        "session_status": session_data.get("status", "completed"),
        "stats": stats.model_dump(),
    }
    prompt = (
        "Eres el ingeniero jefe de optimización de procesos de una granja de impresión 3D FDM.\n"
        "Analiza la línea de tiempo consolidada por fases (0-5% primera capa, 5-85% cuerpo medio, 85-100% cierre superior) "
        "y responde ÚNICAMENTE con JSON válido con estas claves exactas:\n"
        "rating ('EXCELENTE' | 'BUENA_CON_MEJORAS' | 'REQUIERE_AJUSTE'), "
        "executive_summary (string en español claro max 220 chars resumiendo estabilidad térmica, MCU, velocidad/flujo y duración), "
        "improvements (array de 3 a 4 strings en español concretos y accionables para el próximo laminado de esta pieza citando temperaturas/velocidades/ventilación reales).\n"
        f"Datos de la sesión: {json.dumps(prompt_ctx, ensure_ascii=False)}"
    )

    provider = "HEURISTICA_LOCAL"
    raw_json: dict[str, Any] | None = None
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    if deepseek_key:
        try:
            raw_json = _call_deepseek(prompt, deepseek_key)
            provider = "DEEPSEEK_API"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            raw_json = None
    elif gemini_key:
        try:
            raw_json = _call_gemini(prompt, gemini_key)
            provider = "GEMINI_API"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            raw_json = None

    if raw_json is not None:
        raw_rating = str(raw_json.get("rating") or rating).upper()
        if raw_rating in ("EXCELENTE", "BUENA_CON_MEJORAS", "REQUIERE_AJUSTE"):
            rating = raw_rating
        if raw_json.get("executive_summary"):
            executive_summary = str(raw_json["executive_summary"])[:260]
        raw_imp = raw_json.get("improvements")
        if isinstance(raw_imp, list) and raw_imp:
            cleaned_imp = [str(item)[:220] for item in raw_imp[:4] if str(item).strip()]
            if cleaned_imp:
                improvements = cleaned_imp

    return PostPrintCompendium(
        compendium_id=uuid.uuid4().hex[:12],
        session_id=session_id,
        printer_id=printer_id,
        display_name=display_name,
        filename=filename,
        detected_material=detected_material,
        rating=rating,  # type: ignore[arg-type]
        executive_summary=executive_summary,
        improvements=improvements,
        provider=provider,  # type: ignore[arg-type]
        generated_at=datetime.now(timezone.utc).isoformat(),
        is_partial=is_partial,
        stats=stats,
    )


def _call_ai_json(prompt: str) -> tuple[dict[str, Any] | None, str]:
    """Llama al proveedor IA activo (DeepSeek o Google Gemini) y devuelve `(json_dict, provider)`."""
    from app.core.platform_detector import get_active_ai_config

    cfg = get_active_ai_config()
    preferred = cfg.get("provider", "deepseek")
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()

    order = (
        [("gemini", gemini_key), ("deepseek", deepseek_key)]
        if preferred == "gemini"
        else [("deepseek", deepseek_key), ("gemini", gemini_key)]
    )
    for prov, key in order:
        if not key:
            continue
        try:
            if prov == "gemini":
                return _call_gemini(prompt, key), "GEMINI_API"
            return _call_deepseek(prompt, key), "DEEPSEEK_API"
        except (urllib.error.URLError, KeyError, ValueError, TimeoutError):
            continue
    return None, "HEURISTICA_LOCAL"


def _format_est_time(seconds: int) -> str:
    sec = max(60, int(seconds))
    h = sec // 3600
    m = (sec % 3600) // 60
    if h > 0:
        return f"~{h}h {m}m"
    return f"~{max(1, m)}m"


def _parse_time_seconds_from_metrics(metrics: dict[str, Any]) -> int:
    raw_sec = metrics.get("estimated_time_seconds")
    if isinstance(raw_sec, (int, float)) and raw_sec > 0:
        return int(raw_sec)
    txt = str(metrics.get("estimated_time") or metrics.get("estimated_time_str") or "")
    total = 0
    mh = re.search(r"(\d+)\s*h", txt, re.I)
    mm = re.search(r"(\d+)\s*m", txt, re.I)
    ms = re.search(r"(\d+)\s*s", txt, re.I)
    if mh:
        total += int(mh.group(1)) * 3600
    if mm:
        total += int(mm.group(1)) * 60
    if ms:
        total += int(ms.group(1))
    return total if total > 0 else 3600


def _calibrated_speed_and_temp_for_layer(
    printer_id: str,
    material: str,
    nozzle_diameter: float,
    layer_height: float,
    high_speed: bool = False,
    speed_factor: float = 0.85,
) -> tuple[int, int]:
    """Devuelve `(outer_wall_speed_mms, nozzle_temp_c)` calibrados por Q_max y altura."""
    mat = material if material in ("pla", "petg", "abs", "tpu") else "pla"
    limits = get_machine_thermal_kinematic_limits(printer_id)
    temps = compute_optimal_temperatures(
        printer_id, mat, high_speed=high_speed, nozzle_diameter=nozzle_diameter
    )
    outer_range = limits["outer_wall_speed_range"].get(mat, (55, 110))
    req_v = outer_range[1] if layer_height >= 0.24 else outer_range[0] + (outer_range[1] - outer_range[0]) * speed_factor
    lw = 0.48 if (layer_height >= 0.27 and nozzle_diameter <= 0.45) else (0.46 if (layer_height >= 0.24 and nozzle_diameter <= 0.45) else round(nozzle_diameter * 1.05, 2))
    guard = clamp_speed_by_volumetric_flow(
        printer_id,
        mat,
        layer_height,
        lw,
        {"outer_wall_speed": req_v},
        high_speed=high_speed,
    )
    spd = int(guard["clamped_speeds"]["outer_wall_speed"])
    if layer_height <= 0.12:
        spd = max(35, min(spd, int(round(outer_range[0] * 0.85))))
    temp = min(300, int(temps["nozzle_temp"]) + int(guard.get("temp_boost_c") or 0))
    return spd, temp


def _build_6_layer_resolutions(
    *,
    base_seconds: int,
    printer_id: str,
    material: str,
    nozzle_diameter: float,
    high_speed: bool,
    recommended_heights: list[float],
) -> list[AILayerResolutionGroup]:
    limits = get_machine_thermal_kinematic_limits(printer_id)
    mat = material if material in ("pla", "petg", "abs", "tpu") else "pla"
    q_max = float(limits["max_volumetric_speed"].get(mat, 12.0))
    flow_slowdown_024 = 1.0 if q_max >= 20.0 else (1.06 if q_max >= 14.0 else 1.12)
    flow_slowdown_028 = 1.0 if q_max >= 22.0 else (1.10 if q_max >= 14.0 else 1.18)

    specs: list[tuple[float, str, str, float]] = [
        (0.08, "Ultra Fino", "Miniaturas / Detalle Extremo", 2.20),
        (0.12, "Alta Calidad", "Figuras / Acabado Premium", 1.62),
        (0.16, "Detalle Óptimo", "Piezas Visibles", 1.25),
        (0.20, "Estándar Equilibrado", "Uso General", 1.00),
        (0.24, "Rápido Funcional", "Piezas Medianas / Soportes", 0.82 * flow_slowdown_024),
        (0.28, "Extra Rápido", "Piezas Grandes / Blindado", 0.71 * flow_slowdown_028),
    ]

    rec_set = {round(h, 2) for h in recommended_heights}
    groups: list[AILayerResolutionGroup] = []
    for lh, title, subtitle, mult in specs:
        base_h_sec = max(120, int(round(base_seconds * mult)))
        spd_group, temp_group = _calibrated_speed_and_temp_for_layer(
            printer_id, mat, nozzle_diameter, lh, high_speed=high_speed
        )
        if lh <= 0.16:
            sub_specs = [
                ("aesthetic_max", "Acabado Estético Máximo", "Pared externa lenta y primera capa segura 0.16–0.20 mm.", 1.04, 0.75),
                ("anti_support_angle", "Detalle + Ángulo Anti-Soportes", "Busca inclinación óptima para reducir marcas de soporte.", 0.96, 0.85),
            ]
        elif abs(lh - 0.20) < 0.01:
            sub_specs = [
                ("balanced", "Equilibrado General", "Balance óptimo de resistencia, calidad y velocidad.", 1.00, 0.85),
                ("fuzzy_skin", "Piel Difusa (Fuzzy Skin)", "Textura mate exterior que disimula líneas de capa.", 1.08, 0.75),
                ("anti_support_angle", "Ángulo Anti-Soportes", "Evalúa rotación para eliminar o reducir soportes.", 0.93, 0.85),
            ]
        else:
            sub_specs = [
                ("safe_fast", "Rápido Seguro (Anti-Delaminación)", f"Velocidad <= 0.90·Q_max ({q_max:.0f} mm³/s) + comp. térmica.", 1.00, 0.95),
                ("fuzzy_fast", "Rápido + Piel Difusa", "Disimula líneas de capa gruesa con textura exterior.", 1.06, 0.85),
                ("structural_fast", "Rápido Estructural", "Mayor solapamiento de línea y relleno reforzado.", 1.03, 0.90),
            ]

        options = []
        for pid, lbl, desc, sub_mult, spd_fac in sub_specs:
            sec = max(120, int(round(base_h_sec * sub_mult)))
            sub_spd, sub_temp = _calibrated_speed_and_temp_for_layer(
                printer_id, mat, nozzle_diameter, lh, high_speed=high_speed, speed_factor=spd_fac
            )
            options.append(
                AISubOption(
                    id=f"{lh:.2f}__{pid}",
                    label=lbl,
                    description=desc,
                    preset_id=pid,
                    layer_height=lh,
                    calibrated_speed_mms=sub_spd,
                    calibrated_temp_c=sub_temp,
                    estimated_time_str=_format_est_time(sec),
                    estimated_time_seconds=sec,
                )
            )
        groups.append(
            AILayerResolutionGroup(
                layer_height=lh,
                title=title,
                subtitle=subtitle,
                calibrated_speed_mms=spd_group,
                calibrated_temp_c=temp_group,
                estimated_time_str=_format_est_time(base_h_sec),
                estimated_time_seconds=base_h_sec,
                is_recommended=(round(lh, 2) in rec_set),
                options=options,
            )
        )
    return groups


def _build_contextual_fixed_options(
    *,
    category: str,
    base_seconds: int,
    printer_id: str,
    material: str,
    nozzle_diameter: float,
    high_speed: bool,
    has_supports: bool = False,
    is_multicolor: bool = False,
    hero_face_detected: bool = False,
    current_layer_height: float | None = None,
    color_list: list[str] | None = None,
) -> list[AISubOption]:
    mat = material if material in ("pla", "petg", "abs", "tpu") else "pla"
    limits = get_machine_thermal_kinematic_limits(printer_id)
    q_max = float(limits["max_volumetric_speed"].get(mat, 12.0))

    if category == "lithophane_flat":
        specs = [
            ("litho_ultra", "Litofanía Ultra HD (0.08 mm)", "Relleno 100% rectilíneo · Máxima escala de grises.", 0.08, 2.25, 0.70),
            ("litho_hd", "Litofanía Alta Definición (0.12 mm)", "Relleno 100% rectilíneo · Equilibrada y nítida.", 0.12, 1.62, 0.75),
            ("litho_vertical", "Litofanía Vertical Estable (0.12 mm)", "Balsa/Brim reforzado anti-oscilación + 5 paredes.", 0.12, 1.66, 0.72),
        ]
    elif category == "character_organic":
        specs = [
            ("char_premium", "Personaje Premium + Soportes Orgánicos", "0.12 mm · Soportes árbol suaves y pared fina.", 0.12, 1.62, 0.75),
            ("char_ultra", "Ultra Detalle Rostro / Miniatura", "0.08 mm · Máxima definición facial y líneas invisibles.", 0.08, 2.20, 0.70),
            ("char_smooth", "Figura Suave Equilibrada", "0.16 mm · Gran definición con tiempo moderado.", 0.16, 1.25, 0.85),
            ("fuzzy_skin", "Figura Mate / Piel Difusa", "0.20 mm · Textura orgánica mate exterior.", 0.20, 1.08, 0.75),
        ]
    elif category == "large_enclosure":
        specs = [
            ("turbo_shielded", "Turbo Blindado Pieza Grande (0.28 mm)", f"Ancho 0.48 mm, +6–8°C y velocidad <= 90% Q_max ({q_max:.0f} mm³/s).", 0.28, 0.73, 0.95),
            ("fuzzy_fast", "Rápido con Piel Difusa (0.24 mm)", "Disimula capas gruesas con acabado texturizado.", 0.24, 0.86, 0.85),
            ("balanced", "Estándar Limpio (0.20 mm)", "Acabado uniforme para cajas y organizadores.", 0.20, 1.00, 0.85),
        ]
    else:
        specs = [
            ("structural", "Estructural Reforzado (0.20 mm)", "4 paredes + Gyroid 25% para máxima rigidez.", 0.20, 1.08, 0.80),
            ("anti_support_fast", "Rápido Funcional Anti-Soportes (0.24 mm)", "Orientación óptima y ahorro de material.", 0.24, 0.82, 0.90),
            ("turbo_shielded", "Turbo Blindado Pieza Grande (0.28 mm)", f"Seguro anti-delaminación calibrado a Q_max ({q_max:.0f} mm³/s).", 0.28, 0.73, 0.95),
            ("fuzzy_skin", "Acabado Limpio + Piel Difusa (0.20 mm)", "Textura mate antideslizante en paredes externas.", 0.20, 1.08, 0.75),
        ]

    out: list[AISubOption] = []
    # Opciones de mejora real vinculadas a quality_overrides en json_patcher.py
    eff_lh = round(float(current_layer_height or (0.12 if category == "character_organic" else 0.20)), 2)
    base_spd, base_temp = _calibrated_speed_and_temp_for_layer(
        printer_id, mat, nozzle_diameter, eff_lh, high_speed=high_speed, speed_factor=0.80
    )
    if hero_face_detected or category == "character_organic":
        out.append(
            AISubOption(
                id="qo_adaptive_layers",
                label="Capa Adaptativa Rostro/Curvas (0.10–0.24 mm)",
                description="Suaviza rostro y cúpulas a 0.10–0.12 mm manteniendo velocidad en el cuerpo.",
                preset_id="estandar",
                layer_height=eff_lh,
                calibrated_speed_mms=base_spd,
                calibrated_temp_c=base_temp,
                estimated_time_str=_format_hms(max(120, int(round(base_seconds * 1.15)))),
                estimated_time_seconds=max(120, int(round(base_seconds * 1.15))),
                quality_overrides=["adaptive_layers"],
            )
        )
    if has_supports or mat == "petg":
        out.append(
            AISubOption(
                id="qo_dense_support_interface",
                label="Soportes Limpios PETG / Anti-Cicatriz",
                description="Interfaz densa rectilínea 3 capas (0.2 mm), Z 0.16 mm, puente 25 mm/s y 85% fan.",
                preset_id="estandar",
                layer_height=eff_lh,
                calibrated_speed_mms=base_spd,
                calibrated_temp_c=base_temp,
                estimated_time_str=_format_hms(max(120, int(round(base_seconds * 1.05)))),
                estimated_time_seconds=max(120, int(round(base_seconds * 1.05))),
                quality_overrides=["dense_support_interface"],
            )
        )
    if is_multicolor or (color_list and len(color_list) > 1):
        out.append(
            AISubOption(
                id="qo_high_contrast_purge",
                label="Purga Reforzada Oscuro → Claro (1.35×)",
                description="Multiplica flush_multiplier a 1.35× en cambios oscuro→claro y evita cruzar perímetros.",
                preset_id="estandar",
                layer_height=eff_lh,
                calibrated_speed_mms=base_spd,
                calibrated_temp_c=base_temp,
                estimated_time_str=_format_hms(max(120, int(round(base_seconds * 1.08)))),
                estimated_time_seconds=max(120, int(round(base_seconds * 1.08))),
                quality_overrides=["high_contrast_purge"],
            )
        )
    if category != "lithophane_flat" and (hero_face_detected or has_supports or is_multicolor):
        out.append(
            AISubOption(
                id="qo_full_character_polish",
                label="Acabado Profesional Completo (Todo en 1)",
                description="Combina Capa Adaptativa + Soportes Anti-Cicatriz + Purga Reforzada 1.35×.",
                preset_id="estandar",
                layer_height=eff_lh,
                calibrated_speed_mms=base_spd,
                calibrated_temp_c=base_temp,
                estimated_time_str=_format_hms(max(120, int(round(base_seconds * 1.22)))),
                estimated_time_seconds=max(120, int(round(base_seconds * 1.22))),
                quality_overrides=["full_character_polish"],
            )
        )

    for pid, lbl, desc, lh, mult, spd_fac in specs:
        sec = max(120, int(round(base_seconds * mult)))
        spd, temp = _calibrated_speed_and_temp_for_layer(
            printer_id, mat, nozzle_diameter, lh, high_speed=high_speed, speed_factor=spd_fac
        )
        out.append(
            AISubOption(
                id=f"ctx_{lh:.2f}__{pid}",
                label=lbl,
                description=desc,
                preset_id=pid,
                layer_height=lh,
                calibrated_speed_mms=spd,
                calibrated_temp_c=temp,
                estimated_time_str=_format_est_time(sec),
                estimated_time_seconds=sec,
            )
        )
    return out


def analyze_model_for_ai(req: AIAnalyzeModelRequest) -> AIAnalyzeModelResponse:
    """Fase 1 de Análisis IA: clasifica estrictamente el modelo y filtra resoluciones y opciones."""
    dims = req.dimensions_mm
    max_xy = max(dims.x, dims.y, 1.0)
    min_xy = min(dims.x, dims.y)
    aspect_z = dims.z / max_xy
    fname_low = (req.filename or "").lower()
    printer = get_printer_config(req.printer_id)
    eff_mat = "pla" if req.lithophane_mode else req.material

    is_litho = (
        req.lithophane_mode
        or any(tok in fname_low for tok in ("litho", "litof", "photo", "relieve"))
        or (min_xy < 12.0 and dims.z >= 40.0)
        or (dims.z <= 8.0 and max_xy >= 60.0 and req.overhang_ratio < 0.05)
    )
    is_large_box = (
        not is_litho
        and not req.is_multicolor
        and (
            any(tok in fname_low for tok in ("box", "caja", "tray", "bandeja", "organizador", "organizer", "bin", "drawer", "enclosure"))
            or (req.volume_cm3 >= 450.0 and req.overhang_ratio < 0.12)
        )
    )
    is_character = (
        not is_litho
        and (
            req.is_multicolor
            or any(tok in fname_low for tok in ("monty", "char", "fig", "head", "dragon", "cat", "dog", "body", "mask", "bust", "mini", "statue", "toy", "personaje", "figura"))
            or (req.overhang_ratio >= 0.12 and max(dims.x, dims.y, dims.z) < 200.0)
        )
    )

    if is_litho:
        category = "lithophane_flat"
        default_summary = "Detectado: Litofanía / relieve fotográfico de alta precisión Z"
    elif is_character:
        category = "character_organic"
        default_summary = "Detectado: Personaje / figura orgánica con detalles superficiales"
    elif is_large_box:
        category = "large_enclosure"
        default_summary = "Detectado: Caja / organizador o prototipo voluminoso"
    else:
        category = "mechanical_functional"
        default_summary = "Detectado: Pieza mecánica funcional / soporte estructural"

    allowed_by_cat: dict[str, tuple[float, ...]] = {
        "lithophane_flat": (0.08, 0.12),
        "character_organic": (0.08, 0.12, 0.16, 0.20),
        "mechanical_functional": (0.16, 0.20, 0.24, 0.28),
        "large_enclosure": (0.20, 0.24, 0.28),
    }
    rec_by_cat: dict[str, list[float]] = {
        "lithophane_flat": [0.08, 0.12],
        "character_organic": [0.12, 0.16],
        "mechanical_functional": [0.20, 0.24],
        "large_enclosure": [0.24, 0.28],
    }

    prompt_ctx = {
        "filename": req.filename,
        "printer_id": req.printer_id,
        "material": eff_mat,
        "detected_category": category,
        "allowed_heights": allowed_by_cat[category],
        "dimensions_mm": dims.model_dump(),
        "aspect_z": round(aspect_z, 2),
        "volume_cm3": round(req.volume_cm3, 2),
        "overhang_ratio": round(req.overhang_ratio, 3),
        "is_multicolor": req.is_multicolor,
        "has_supports": req.has_supports,
        "layer_height": req.layer_height,
        "color_list": req.color_list,
        "hero_face_detected": req.hero_face_detected,
    }
    prompt = (
        "Eres un ingeniero experto en impresión 3D FDM.\n"
        "Redacta un resumen corto, un título de proyecto en español (2 a 4 palabras máximo, ej. 'Robot Articulado Multicolor', 'Soporte Base Laptop', 'Litofanía Fotográfica', 'Organizador Modular', 'Busto Personaje') y elige 1 o 2 alturas recomendadas DENTRO de `allowed_heights`.\n"
        "Responde SOLO JSON válido con:\n"
        "- detected_type_summary (string en español <= 12 palabras)\n"
        "- short_spanish_title (string en español de 2 a 4 palabras máximo)\n"
        "- recommended_heights (array de 1 o 2 números de `allowed_heights`)\n"
        f"Datos: {json.dumps(prompt_ctx, ensure_ascii=False)}"
    )
    raw_json, provider = _call_ai_json(prompt)
    summary = default_summary
    rec_heights = list(rec_by_cat[category])

    fname_low = (req.filename or "").lower()
    if category == "lithophane_flat":
        short_title = "Litofanía Fotográfica"
    elif category == "character_organic":
        if "robot" in fname_low or "robo" in fname_low or "mech" in fname_low:
            short_title = "Robot Articulado Multicolor" if req.is_multicolor else "Robot Articulado 3D"
        elif "bust" in fname_low or "head" in fname_low:
            short_title = "Busto Personaje"
        else:
            short_title = "Figura Coleccionable Multicolor" if req.is_multicolor else "Figura Coleccionable 3D"
    elif category == "large_enclosure":
        if "stand" in fname_low or "laptop" in fname_low:
            short_title = "Soporte Base Laptop"
        else:
            short_title = "Organizador Modular"
    else:
        if "stand" in fname_low or "soporte" in fname_low:
            short_title = "Soporte Funcional 3D"
        elif "box" in fname_low or "case" in fname_low or "caja" in fname_low:
            short_title = "Carcasa Protectora 3D"
        else:
            short_title = "Pieza Mecánica Multicolor" if req.is_multicolor else "Pieza Mecánica Funcional"

    allowed_set = set(allowed_by_cat[category])
    if raw_json:
        raw_sum = str(raw_json.get("detected_type_summary") or "").strip()
        if raw_sum:
            summary = raw_sum[:110]
        raw_title = str(raw_json.get("short_spanish_title") or "").strip()
        if raw_title:
            words = raw_title.split()[:4]
            if words:
                short_title = " ".join(words)[:60]
        raw_heights = raw_json.get("recommended_heights")
        if isinstance(raw_heights, list) and raw_heights:
            valid_h = [round(float(h), 2) for h in raw_heights if round(float(h), 2) in allowed_set]
            if valid_h:
                rec_heights = valid_h[:2]

    base_sec = _parse_time_seconds_from_metrics(req.current_slice_metrics)
    all_resolutions = _build_6_layer_resolutions(
        base_seconds=base_sec,
        printer_id=req.printer_id,
        material=eff_mat,
        nozzle_diameter=req.nozzle_diameter,
        high_speed=req.high_speed_filament,
        recommended_heights=rec_heights,
    )
    filtered_resolutions = [g for g in all_resolutions if round(g.layer_height, 2) in allowed_set]
    contextual_options = _build_contextual_fixed_options(
        category=category,
        base_seconds=base_sec,
        printer_id=req.printer_id,
        material=eff_mat,
        nozzle_diameter=req.nozzle_diameter,
        high_speed=req.high_speed_filament,
        has_supports=req.has_supports,
        is_multicolor=req.is_multicolor,
        hero_face_detected=req.hero_face_detected or (category == "character_organic"),
        current_layer_height=req.layer_height,
        color_list=req.color_list,
    )

    min_h = min(allowed_by_cat[category])
    max_h = max(allowed_by_cat[category])
    cat_labels = {
        "lithophane_flat": "Modo Litofanía",
        "character_organic": "Modo Personaje/Orgánico",
        "mechanical_functional": "Modo Pieza Mecánica",
        "large_enclosure": "Modo Caja/Prototipo Grande",
    }
    has_flat_base = float(getattr(req, "base_contact_area_mm2", 0.0) or 0.0) >= 40.0
    base_badge = " · Base Monotónica + Anti-Cicatrices Z-Hop 0.4mm" if has_flat_base else ""
    filter_note = (
        f"{cat_labels[category]} detectado: mostrando exclusivamente resoluciones "
        f"{min_h:.2f}–{max_h:.2f} mm para {printer.display_name} + {eff_mat.upper()}{base_badge}."
    )

    presets = [
        AIPresetOption(
            id=opt.preset_id,
            label=opt.label,
            description=opt.description,
            badge=f"{opt.layer_height:.2f} mm",
        )
        for opt in contextual_options
    ]

    return AIAnalyzeModelResponse(
        detected_type_summary=summary,
        short_spanish_title=short_title,
        model_category=category,  # type: ignore[arg-type]
        filter_note=filter_note,
        contextual_options=contextual_options,
        recommended_presets=presets,
        layer_resolutions=filtered_resolutions,
        all_layer_resolutions=all_resolutions,
        provider=provider,  # type: ignore[arg-type]
    )


def optimize_slice_with_ai(
    req: AIOptimizeSliceRequest,
    best_euler: tuple[float, float, float] | None = None,
) -> AIOptimizeSliceResponse:
    """Fase 2 de Análisis IA: calcula ángulo, soportes, capa, velocidad, flujo y fuzzy_skin."""
    printer = get_printer_config(req.printer_id)
    eff_mat = "pla" if req.lithophane_mode else req.material
    temps = compute_optimal_temperatures(
        req.printer_id,
        eff_mat,
        high_speed=req.high_speed_filament,
        nozzle_diameter=req.nozzle_diameter,
    )
    base_z = DEFAULT_SUPPORT_Z_BY_MATERIAL.get(eff_mat, 0.20)
    base_xy = compute_default_support_xy(eff_mat, req.nozzle_diameter)
    adh_type, brim_w, _ = _compute_adhesion_recommendation(
        eff_mat, req.dimensions_mm.z, req.base_contact_area_mm2
    )

    preset = (req.preset_id or "balanced").strip().lower()
    notes_low = (req.user_notes or "").lower()
    want_fuzzy = (
        preset in ("fuzzy_skin", "fuzzy_fast")
        or "difus" in notes_low
        or "textur" in notes_low
        or "fuzzy" in notes_low
    )

    # Heurística base según estrategia elegida
    strategy_labels = {
        "aesthetic_max": "Acabado Estético Máximo",
        "premium_finish": "Acabado Premium",
        "fuzzy_skin": "Piel Difusa (Fuzzy Skin)",
        "fuzzy_fast": "Rápido + Piel Difusa",
        "safe_fast": "Rápido Seguro (Anti-Delaminación)",
        "structural_fast": "Rápido Estructural",
        "structural": "Estructural Reforzado",
        "turbo_shielded": "Turbo Blindado Pieza Grande",
        "anti_support_fast": "Rápido Funcional Anti-Soportes",
        "litho_ultra": "Litofanía Ultra HD",
        "litho_hd": "Litofanía Alta Definición",
        "litho_vertical": "Litofanía Vertical Estable",
        "char_premium": "Personaje Premium + Soportes Orgánicos",
        "char_ultra": "Ultra Detalle Rostro / Miniatura",
        "char_smooth": "Figura Suave Equilibrada",
        "balanced": "Equilibrado General",
        "speed_opt": "Optimizar Velocidad",
        "anti_support_angle": "Ángulo Anti-Soporte",
    }
    target_lh = float(req.target_layer_height) if req.target_layer_height is not None else None
    base_label = strategy_labels.get(preset, "Optimización IA")
    strategy_label = f"{base_label} ({target_lh:.2f} mm)" if target_lh is not None else base_label

    max_printer_speed = compute_heterogeneous_speed_cap(
        [printer.max_volumetric_flow_mm3_s],
        [eff_mat],
        nozzle_diameter=req.nozzle_diameter,
    )["max_linear_speed"]
    machine_limits = get_machine_thermal_kinematic_limits(req.printer_id)
    profile_id = resolve_profile_id(req.printer_id)
    q_max_mat = float(machine_limits["max_volumetric_speed"].get(eff_mat, 12.0))
    outer_range = machine_limits["outer_wall_speed_range"].get(eff_mat, (55, 110))
    line_w = round(req.nozzle_diameter * 1.05, 2)

    max_lh = round(min(0.28, req.nozzle_diameter * 0.7), 2)
    min_lh = round(max(0.08, req.nozzle_diameter * 0.2), 2)
    layer_height = round(max(min_lh, min(max_lh, target_lh)), 2) if target_lh is not None else 0.20
    outer_speed = min(outer_range[1], max(outer_range[0], int(round(max_printer_speed * 0.65))))
    flow_ratio = 0.98 if eff_mat in ("petg", "abs") else 1.00
    infill_density = 15
    nozzle_temp = int(temps["nozzle_temp"])
    apply_rot = False
    rx, ry, rz = req.rot_x, req.rot_y, req.rot_z
    supports_req = req.overhang_ratio >= 0.08
    sup_type = "tree(auto)"
    z_dist = base_z
    explanation = f"Capa {layer_height:.2f} mm calibrada con límites físicos de {printer.display_name}."

    if preset in ("litho_ultra", "litho_hd", "litho_vertical"):
        if target_lh is None:
            layer_height = 0.08 if preset == "litho_ultra" else 0.12
        outer_speed = max(35, min(60, int(round(outer_range[0] * 0.72))))
        infill_density = 100
        supports_req = False
        if preset == "litho_vertical":
            adh_type = "brim"
            brim_w = 10.0
        explanation = f"Litofanía {layer_height:.2f} mm, relleno 100% rectilíneo y {outer_speed} mm/s anti-ghosting."
    elif preset in ("premium_finish", "aesthetic_max", "char_premium", "char_ultra", "char_smooth"):
        if target_lh is None:
            layer_height = 0.08 if preset == "char_ultra" else (0.16 if preset == "char_smooth" else 0.12)
        outer_speed = max(35, min(outer_range[1], int(round(outer_range[0] * 0.85))))
        z_dist = round(max(0.14, base_z - 0.04), 2)
        if preset == "char_premium":
            supports_req = req.overhang_ratio >= 0.06
            sup_type = "tree(auto)"
        explanation = f"Capa {layer_height:.2f} mm, pared externa a {outer_speed} mm/s y Z de soporte reducido para detalle fino."
    elif preset in ("fuzzy_skin", "fuzzy_fast"):
        if target_lh is None:
            layer_height = 0.24 if preset == "fuzzy_fast" else 0.20
        outer_speed = max(45, min(outer_range[1], int(round(outer_range[0] * 0.95))))
        explanation = f"Piel Difusa exterior en {layer_height:.2f} mm para disimular líneas de capa con textura uniforme."
    elif preset in ("speed_opt", "safe_fast", "structural_fast", "structural", "turbo_shielded"):
        if target_lh is None:
            layer_height = 0.28 if preset == "turbo_shielded" else (0.20 if preset == "structural" else 0.24)
        outer_speed = outer_range[1]
        infill_density = 25 if preset == "structural" else (20 if preset == "structural_fast" else 12)
        supports_req = req.overhang_ratio >= 0.14
        explanation = f"Capa {layer_height:.2f} mm protegida por 0.90·Q_max ({q_max_mat:.0f} mm³/s) y compensación térmica."
    elif preset in ("anti_support_angle", "anti_support_fast"):
        if best_euler is not None and (
            abs(best_euler[0] - req.rot_x) > 3.0 or abs(best_euler[1] - req.rot_y) > 3.0
        ):
            apply_rot = True
            rx, ry, rz = best_euler
            supports_req = req.overhang_ratio >= 0.18
            explanation = f"Orientación optimizada a ({rx:.1f}°, {ry:.1f}°, {rz:.1f}°) en {layer_height:.2f} mm para reducir soportes."
        else:
            apply_rot = True
            rx = round((req.rot_x + 35.0) % 360.0, 1)
            supports_req = False if req.overhang_ratio < 0.14 else True
            explanation = f"Inclinación estratégica ({rx:.1f}°) en {layer_height:.2f} mm para evitar voladizos."

    prompt_ctx = {
        "printer_id": req.printer_id,
        "profile_id": profile_id,
        "printer_profile": {
            "vendor": printer.vendor,
            "model_name": printer.model_name,
            "display_name": printer.display_name,
            "bed_shape": printer.bed_shape,
            "gcode_flavor": printer.gcode_flavor,
            "kinematics": printer.kinematics,
            "estimated_q_max": printer.max_volumetric_flow_mm3_s,
            "is_multicolor": printer.is_multicolor,
            "tool_count": printer.extruder_slots,
            "has_heated_chamber": printer.has_heated_chamber,
            "is_high_speed": printer.is_high_speed,
            "nozzle_diameter": req.nozzle_diameter,
        },
        "printer_max_speed": max_printer_speed,
        "machine_limits": {
            "q_max_mm3_s": q_max_mat,
            "outer_wall_speed_range_mms": outer_range,
            "default_acceleration": machine_limits["default_acceleration"],
            "outer_wall_acceleration": machine_limits["outer_wall_acceleration"],
            "v_max_at_0_20mm": round(q_max_mat / (0.20 * line_w), 1),
            "v_max_at_0_28mm": round(q_max_mat / (0.28 * line_w), 1),
        },
        "material": eff_mat,
        "nozzle_diameter": req.nozzle_diameter,
        "preset_id": preset,
        "user_notes": req.user_notes,
        "current_rotation": {"rot_x": req.rot_x, "rot_y": req.rot_y, "rot_z": req.rot_z},
        "best_euler_candidate": best_euler,
        "dimensions_mm": req.dimensions_mm.model_dump(),
        "overhang_ratio": round(req.overhang_ratio, 3),
        "base_contact_area_mm2": round(req.base_contact_area_mm2, 1),
        "current_support_config": req.current_support_config,
        "current_slice_metrics": req.current_slice_metrics,
        "default_temp": nozzle_temp,
    }
    prompt = (
        "Eres el ingeniero jefe de laminado FDM. Optimiza conjuntamente rotación, soportes y calidad.\n"
        "RESPETA OBLIGATORIAMENTE `machine_limits` (`q_max_mm3_s` y `outer_wall_speed_range_mms`): "
        "nunca sugieras velocidades de T1 Pro para V400, Creator 5 Pro, Super Racer o Ender 3 S1 Pro.\n"
        "Si el usuario pide sin soportes o preset 'anti_support_angle', evalúa inclinar 30-45° o usar best_euler_candidate.\n"
        "Responde SOLO JSON válido con:\n"
        "strategy_label (string), explanation (string en español max 180 chars), "
        "apply_rotation (bool), rot_x (float), rot_y (float), rot_z (float), "
        "supports_required (bool), support_type ('tree(auto)'|'normal(auto)'), "
        "support_on_build_plate_only (bool), support_z_distance (float 0.12..0.35), "
        "layer_height (float 0.12..0.28), outer_wall_speed (int 35..260), "
        "flow_ratio (float 0.90..1.05), nozzle_temp (int), infill_density (int 8..40), "
        "fuzzy_skin (bool), fuzzy_skin_thickness (float 0.15..0.35), fuzzy_skin_point_distance (float 0.3..0.8).\n"
        f"Datos: {json.dumps(prompt_ctx, ensure_ascii=False)}"
    )
    raw_json, provider = _call_ai_json(prompt)
    fuzzy_thick = 0.25
    fuzzy_dist = 0.40
    sup_plate_only = True
    if raw_json:
        if raw_json.get("strategy_label"):
            strategy_label = str(raw_json["strategy_label"])[:60]
        if raw_json.get("explanation"):
            explanation = str(raw_json["explanation"])[:220]
        if isinstance(raw_json.get("apply_rotation"), bool):
            apply_rot = raw_json["apply_rotation"]
        for key, default_val in (("rot_x", rx), ("rot_y", ry), ("rot_z", rz)):
            try:
                if raw_json.get(key) is not None:
                    val = float(raw_json[key])
                    if key == "rot_x":
                        rx = val
                    elif key == "rot_y":
                        ry = val
                    else:
                        rz = val
            except (TypeError, ValueError):
                pass
        if isinstance(raw_json.get("supports_required"), bool):
            supports_req = raw_json["supports_required"]
        if raw_json.get("support_type") in ("tree(auto)", "normal(auto)", "tree(manual)", "normal(manual)"):
            sup_type = str(raw_json["support_type"])
        if isinstance(raw_json.get("support_on_build_plate_only"), bool):
            sup_plate_only = raw_json["support_on_build_plate_only"]
        try:
            if raw_json.get("support_z_distance") is not None:
                z_dist = round(max(0.10, min(0.40, float(raw_json["support_z_distance"]))), 2)
        except (TypeError, ValueError):
            pass
        try:
            if target_lh is None and raw_json.get("layer_height") is not None:
                layer_height = round(max(min_lh, min(max_lh, float(raw_json["layer_height"]))), 2)
        except (TypeError, ValueError):
            pass
        try:
            if raw_json.get("outer_wall_speed") is not None:
                outer_speed = max(30, min(max_printer_speed, int(round(float(raw_json["outer_wall_speed"])))))
        except (TypeError, ValueError):
            pass
        try:
            if raw_json.get("flow_ratio") is not None:
                flow_ratio = round(max(0.88, min(1.08, float(raw_json["flow_ratio"]))), 2)
        except (TypeError, ValueError):
            pass
        try:
            if raw_json.get("nozzle_temp") is not None:
                nozzle_temp = max(175, min(300, int(round(float(raw_json["nozzle_temp"])))))
        except (TypeError, ValueError):
            pass
        try:
            if raw_json.get("infill_density") is not None:
                infill_density = max(5, min(100, int(round(float(raw_json["infill_density"])))))
        except (TypeError, ValueError):
            pass
        if isinstance(raw_json.get("fuzzy_skin"), bool):
            want_fuzzy = raw_json["fuzzy_skin"] or preset == "fuzzy_skin"
        try:
            if raw_json.get("fuzzy_skin_thickness") is not None:
                fuzzy_thick = round(max(0.10, min(0.50, float(raw_json["fuzzy_skin_thickness"]))), 2)
        except (TypeError, ValueError):
            pass
        try:
            if raw_json.get("fuzzy_skin_point_distance") is not None:
                fuzzy_dist = round(max(0.20, min(1.20, float(raw_json["fuzzy_skin_point_distance"]))), 2)
        except (TypeError, ValueError):
            pass

    # Seguro físico obligatorio de caudal volumétrico Q_max = h * w * v
    flow_guard = clamp_speed_by_volumetric_flow(
        req.printer_id,
        eff_mat,
        layer_height,
        line_w,
        {"outer_wall_speed": outer_speed},
        high_speed=req.high_speed_filament,
    )
    outer_speed = int(flow_guard["clamped_speeds"]["outer_wall_speed"])
    temp_boost = int(flow_guard.get("temp_boost_c") or 0)
    if temp_boost > 0:
        nozzle_temp = min(300, nozzle_temp + temp_boost)

    return AIOptimizeSliceResponse(
        strategy_label=strategy_label,
        explanation=explanation,
        apply_rotation=apply_rot,
        rot_x=round(rx, 2),
        rot_y=round(ry, 2),
        rot_z=round(rz, 2),
        supports_required=supports_req,
        support_type=sup_type,  # type: ignore[arg-type]
        support_on_build_plate_only=sup_plate_only,
        support_z_distance=z_dist,
        support_xy_distance=base_xy,
        adhesion_type=adh_type,  # type: ignore[arg-type]
        brim_width_mm=brim_w,
        layer_height=layer_height,
        outer_wall_speed=outer_speed,
        flow_ratio=flow_ratio,
        nozzle_temp=nozzle_temp,
        infill_density=infill_density,
        fuzzy_skin=want_fuzzy,
        fuzzy_skin_thickness=fuzzy_thick,
        fuzzy_skin_point_distance=fuzzy_dist,
        provider=provider,  # type: ignore[arg-type]
    )


def diagnose_print_defect(
    req: AIDefectDiagnoseRequest,
    project_data: dict[str, Any],
) -> AIDefectDiagnoseResponse:
    """Analiza un defecto físico reportado tras imprimir usando los parámetros exactos del proyecto."""
    params = project_data.get("params") if isinstance(project_data.get("params"), dict) else {}
    defect = req.defect_description.strip()
    defect_low = defect.lower()

    cur_lh = float(params.get("layer_height") or 0.20)
    cur_speed = int(params.get("outer_wall_speed") or 120)
    cur_temp = int(params.get("nozzle_temp") or 215)
    cur_bed = int(params.get("bed_temp") or 60)
    cur_flow = float(params.get("flow_ratio") or 1.0)
    cur_z = float(params.get("support_z_distance") or 0.20)
    cur_xy = float(params.get("support_xy_distance") or 0.50)

    proj_pid = str(project_data.get("printer_id") or "creator5_pro_1")
    proj_mat = str(project_data.get("material") or "pla").lower()
    proj_nozzle = float(project_data.get("nozzle_diameter") or 0.4)
    line_w = round(proj_nozzle * 1.05, 2)
    machine_limits = get_machine_thermal_kinematic_limits(proj_pid)
    q_max = float(machine_limits["max_volumetric_speed"].get(proj_mat, 12.0))
    q_real = round(cur_lh * line_w * cur_speed, 2)
    v_max_safe = round(q_max / max(0.02, cur_lh * line_w), 1)
    exceeded_hotend = q_real > (q_max * 0.95)

    corrected: dict[str, Any] = {}
    root_cause = "Desajuste de velocidad/flujo respecto a la geometría del modelo."
    explanation = "Se ajustaron velocidad de pared externa y flujo para estabilizar la extrusión."

    if exceeded_hotend and any(k in defect_low for k in ("delamin", "despeg", "capas", "band", "línea", "linea", "sub", "extrus")):
        safe_speed = max(40, min(int(v_max_safe * 0.85), machine_limits["outer_wall_speed_range"].get(proj_mat, (55, 100))[1]))
        new_temp = min(295, cur_temp + 5)
        corrected = {
            "outer_wall_speed_override": safe_speed,
            "nozzle_temp": new_temp,
            "layer_height_override": cur_lh,
            "flow_ratio_override": round(min(1.03, cur_flow + 0.02), 2),
        }
        root_cause = (
            f"Caudal volumétrico excedido ({q_real:.1f} mm³/s > Q_max {q_max:.1f} mm³/s de {proj_pid} "
            f"a {cur_lh:.2f} mm), causando sub-extrusión/delaminación."
        )
        explanation = (
            f"Recortada pared externa a {safe_speed} mm/s (<= v_max {v_max_safe} mm/s) y +5°C en boquilla ({new_temp}°C)."
        )
    elif any(k in defect_low for k in ("band", "línea", "linea", "capa", "z", "ring", "vibrac", "ghost", "delamin")):
        new_speed = max(45, int(round(cur_speed * 0.68)))
        new_lh = round(max(0.12, cur_lh - 0.04), 2)
        corrected = {
            "outer_wall_speed_override": new_speed,
            "layer_height_override": new_lh,
            "flow_ratio_override": round(max(0.94, cur_flow - 0.02), 2),
        }
        root_cause = f"Velocidad de pared externa ({cur_speed} mm/s) o vibración mecánica generando banding/ringing."
        explanation = f"Reducida pared externa a {new_speed} mm/s, capa a {new_lh} mm y flujo a {corrected['flow_ratio_override']}."
    elif any(k in defect_low for k in ("soport", "cicatriz", "marca", "pegad")):
        new_z = round(min(0.32, cur_z + 0.06), 2)
        new_xy = round(min(1.00, cur_xy + 0.15), 2)
        corrected = {
            "supports": True,
            "support_type": "tree(auto)",
            "support_z_distance": new_z,
            "support_xy_distance": new_xy,
        }
        root_cause = f"Distancia Z de soporte ({cur_z} mm) demasiado pegada al modelo."
        explanation = f"Incrementada separación Z a {new_z} mm y XY a {new_xy} mm con soporte árbol orgánico."
    elif any(k in defect_low for k in ("hilo", "string", "telara", "babeo")):
        new_temp = max(185, cur_temp - 8)
        corrected = {
            "nozzle_temp": new_temp,
            "flow_ratio_override": round(max(0.93, cur_flow - 0.03), 2),
        }
        root_cause = f"Temperatura de boquilla elevada ({cur_temp}°C) provocando rezume en viajes."
        explanation = f"Reducida temperatura de boquilla a {new_temp}°C y flujo a {corrected['flow_ratio_override']}."
    elif any(k in defect_low for k in ("despeg", "warp", "adher", "primera capa")):
        new_bed = min(110, cur_bed + 5)
        corrected = {
            "bed_temp": new_bed,
            "adhesion_type": "brim",
            "brim_width_mm": 8.0,
        }
        root_cause = f"Adherencia insuficiente en primera capa (cama {cur_bed}°C sin brim amplio)."
        explanation = f"Elevada cama a {new_bed}°C y activado Brim exterior de 8 mm."
    else:
        corrected = {
            "outer_wall_speed_override": max(50, int(round(cur_speed * 0.75))),
            "flow_ratio_override": round(max(0.95, cur_flow - 0.02), 2),
        }

    prompt_ctx = {
        "defect_description": defect,
        "volumetric_audit": {
            "q_real_mm3_s": q_real,
            "q_max_mm3_s": q_max,
            "v_max_safe_mms": v_max_safe,
            "exceeded_hotend": exceeded_hotend,
            "machine_limits": machine_limits,
        },
        "project": {
            "printer_id": project_data.get("printer_id"),
            "material": project_data.get("material"),
            "nozzle_diameter": project_data.get("nozzle_diameter"),
            "params": params,
            "metrics": project_data.get("metrics"),
        },
    }
    prompt = (
        "Eres un especialista en control de calidad de impresión 3D FDM.\n"
        "Inspecciona los parámetros exactos del proyecto y el defecto reportado por el usuario.\n"
        "Responde SOLO JSON válido con:\n"
        "- root_cause (string en español citando el parámetro exacto causante)\n"
        "- explanation (string en español max 200 chars con la corrección aplicada)\n"
        "- corrected_params (objeto JSON usando solo claves válidas de: "
        "layer_height_override, outer_wall_speed_override, flow_ratio_override, infill_density_override, "
        "nozzle_temp, bed_temp, supports, support_type, support_z_distance, support_xy_distance, "
        "adhesion_type, brim_width_mm, fuzzy_skin).\n"
        f"Datos: {json.dumps(prompt_ctx, ensure_ascii=False)}"
    )
    raw_json, provider = _call_ai_json(prompt)
    if raw_json:
        if raw_json.get("root_cause"):
            root_cause = str(raw_json["root_cause"])[:220]
        if raw_json.get("explanation"):
            explanation = str(raw_json["explanation"])[:240]
        raw_corr = raw_json.get("corrected_params")
        if isinstance(raw_corr, dict) and raw_corr:
            allowed_keys = {
                "layer_height_override",
                "outer_wall_speed_override",
                "flow_ratio_override",
                "infill_density_override",
                "nozzle_temp",
                "bed_temp",
                "supports",
                "support_type",
                "support_z_distance",
                "support_xy_distance",
                "adhesion_type",
                "brim_width_mm",
                "fuzzy_skin",
            }
            filtered = {k: v for k, v in raw_corr.items() if k in allowed_keys}
            if filtered:
                corrected = filtered

    return AIDefectDiagnoseResponse(
        root_cause=root_cause,
        explanation=explanation,
        corrected_params=corrected,
        provider=provider,  # type: ignore[arg-type]
    )


def evaluate_orientations_with_ai(
    geom_result: dict[str, Any],
    *,
    printer_name: str,
    material: str,
) -> AIOrientationsResponse:
    """Enriquece con DeepSeek IA las 5 orientaciones geométricas calculadas con trimesh."""
    raw_options: list[dict[str, Any]] = list(geom_result.get("options") or [])
    recommended_id = str(geom_result.get("recommended_id") or "original")
    is_multicolor = bool(geom_result.get("is_multicolor"))
    multicolor_parts = int(geom_result.get("multicolor_parts_count") or 1)
    model_name = str(geom_result.get("model_name") or "modelo")
    hero_face_detected = bool(geom_result.get("hero_face_detected"))
    hero_face_normal = geom_result.get("hero_face_normal")

    prompt_ctx = {
        "model_name": model_name,
        "printer": printer_name,
        "material": material.upper(),
        "is_multicolor": is_multicolor,
        "multicolor_parts_count": multicolor_parts,
        "hero_face_detected": hero_face_detected,
        "hero_face_normal": hero_face_normal,
        "options": [
            {
                "id": o["id"],
                "title": o["title"],
                "rotation": o["rotation"],
                "z_height_mm": o["z_height_mm"],
                "overhang_ratio_pct": o["overhang_ratio_pct"],
                "contact_area_mm2": o["contact_area_mm2"],
                "stability_warning": o.get("stability_warning"),
                "estimated_time_delta_pct": o["estimated_time_delta_pct"],
                "fits_bed": o["fits_bed"],
                "hero_face_elevation_deg": o.get("hero_face_elevation_deg"),
            }
            for o in raw_options
        ],
    }
    prompt = (
        "Eres un experto en impresión 3D FDM y laminado multicolor (OrcaSlicer). "
        "Analiza estas 5 orientaciones candidatas medidas con trimesh y devuelve JSON estricto con:\n"
        "- recommended_id: el id de la mejor orientación ('original', 'back_down', 'tilted_45', 'min_z' o 'max_stability'). "
        "NUNCA recomiendes una opción que tenga stability_warning o fits_bed=false si existe una estable. "
        "Si hero_face_detected=true (personaje/figura con rostro): penaliza orientaciones con hero_face_elevation_deg < -8° (soportes en el rostro) "
        "y también > 65° (cara casi paralela a la cama <25°, efecto escalera en frente/ojos); "
        "prioriza ángulos inclinados 15°–60° (reclinado 20°–45° / elevación frontal 45°–75°) donde los soportes quedan ocultos atrás.\n"
        "- explanations: objeto {id: frase_corta_max_150_chars} explicando en español qué mejora y dónde caerán los soportes.\n"
        f"Datos: {json.dumps(prompt_ctx, ensure_ascii=False)}"
    )

    raw_json, provider = _call_ai_json(prompt)
    opt_by_id = {str(o["id"]): o for o in raw_options}
    valid_ids = set(opt_by_id.keys())
    ai_explanations: dict[str, str] = {}
    if raw_json:
        cand_rec = str(raw_json.get("recommended_id") or "")
        if cand_rec in valid_ids:
            cand_obj = opt_by_id[cand_rec]
            has_stable_alt = any(
                bool(o["fits_bed"]) and not o.get("stability_warning")
                for o in raw_options
            )
            if (bool(cand_obj["fits_bed"]) and not cand_obj.get("stability_warning")) or not has_stable_alt:
                recommended_id = cand_rec
        raw_exp = raw_json.get("explanations")
        if isinstance(raw_exp, dict):
            for k, v in raw_exp.items():
                if str(k) in valid_ids and isinstance(v, str) and v.strip():
                    ai_explanations[str(k)] = v.strip()[:180]

    options_models: list[OrientationOption] = []
    for o in raw_options:
        oid = str(o["id"])
        rot = o["rotation"]
        options_models.append(
            OrientationOption(
                id=oid,
                title=str(o["title"]),
                badge=str(o["badge"]),
                rotation=OrientationRotation(
                    rx=float(rot["rx"]),
                    ry=float(rot["ry"]),
                    rz=float(rot["rz"]),
                ),
                z_height_mm=float(o["z_height_mm"]),
                overhang_ratio_pct=float(o["overhang_ratio_pct"]),
                contact_area_mm2=float(o["contact_area_mm2"]),
                estimated_time_delta_pct=str(o["estimated_time_delta_pct"]),
                explanation=ai_explanations.get(oid, str(o["explanation"])),
                stability_warning=o.get("stability_warning"),
                fits_bed=bool(o["fits_bed"]),
                is_recommended=(oid == recommended_id),
            )
        )

    options_models.sort(
        key=lambda m: (
            0 if m.is_recommended else 1,
            0 if m.fits_bed else 1,
            1 if m.stability_warning else 0,
        )
    )

    return AIOrientationsResponse(
        mesh_id=str(geom_result.get("mesh_id") or ""),
        model_name=model_name,
        is_multicolor=is_multicolor,
        multicolor_parts_count=multicolor_parts,
        ai_provider=provider,  # type: ignore[arg-type]
        hero_face_detected=hero_face_detected,
        hero_face_normal=hero_face_normal,
        recommended_id=recommended_id,
        options=options_models,
    )
