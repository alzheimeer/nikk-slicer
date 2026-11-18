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
    compute_default_support_xy,
    compute_heterogeneous_speed_cap,
    compute_optimal_temperatures,
    get_printer_config,
    get_slot_volumetric_limit,
    load_catalog,
    negotiate_multimaterial_bed_temp,
)
from app.models.schemas import (
    AIRecommendRequest,
    AIRecommendResponse,
    AISupportOrientResponse,
    AITelemetryDiagnosisResponse,
    MeshAnalysisResponse,
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
            "kinematics": printer.kinematics,
            "max_volumetric_flow_mm3_s": printer.max_volumetric_flow_mm3_s,
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
