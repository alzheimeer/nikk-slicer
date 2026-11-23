"""Servidor MCP Interno Autodescubierto de Nikk Slicer (HTTP/SSE en FastAPI + stdio)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

# Asegurar que `app.*` sea importable tanto desde `backend/` como desde la raíz del repo
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from app.config import (
    MESH_CACHE_DIR,
    TEMP_DIR,
    get_printer_config,
    get_printer_instance,
    load_catalog,
    load_printers_config,
)
from app.connectors import (
    control_flashforge,
    control_moonraker,
    marlin_manager,
    query_flashforge_status,
    query_moonraker_status,
    upload_and_start_flashforge,
    upload_and_start_moonraker,
)
from app.core.ai_copilot import (
    analyze_model_for_ai,
    evaluate_orientations_with_ai,
)
from app.core.error_journal import read_error_journal
from app.core.gcode_postprocessor import apply_layer_pauses_to_file
from app.core.mesh_analyzer import (
    analyze_model_file,
    auto_arrange_instances,
    evaluate_orientation_candidates,
    split_mesh_into_scene_objects,
)
from app.core.platform_detector import (
    get_system_environment,
    save_ai_config,
    scan_installed_slicers,
    set_slicer_path,
)
from app.core.project_manager import (
    delete_full_project,
    get_full_project,
    list_recent_projects,
)
from app.models.schemas import (
    AIAnalyzeModelRequest,
    DimensionsMM,
    ModelInstanceTransform,
    SliceRequest,
)

mcp = MCPServer("NikkSlicerMCP")


def _json_str(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, default=str)


def _resolve_model_path(model_path: str | None, mesh_id: str | None) -> tuple[str, Path]:
    if mesh_id:
        for ext in (".3mf", ".stl"):
            cand = MESH_CACHE_DIR / f"{mesh_id}{ext}"
            if cand.is_file():
                return mesh_id, cand
    if model_path:
        p = Path(model_path).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Archivo no encontrado: {p}")
        import hashlib

        mid = hashlib.sha1(p.read_bytes()).hexdigest()[:12]
        MESH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached = MESH_CACHE_DIR / f"{mid}{p.suffix.lower()}"
        if not cached.is_file():
            cached.write_bytes(p.read_bytes())
        return mid, cached
    raise ValueError("Debes proporcionar `model_path` o `mesh_id` válido.")


# ==============================================================================
# 1. MCP RESOURCES
# ==============================================================================


@mcp.resource("nikk://printers")
def resource_printers() -> str:
    """Catálogo y configuración actual de las 6 impresoras de Nikk Slicer."""
    cfg = load_printers_config()
    return _json_str(cfg.model_dump() if hasattr(cfg, "model_dump") else cfg)


@mcp.resource("nikk://projects/recent")
def resource_recent_projects() -> str:
    """Los 5 proyectos más recientes guardados en Nikk Slicer."""
    return _json_str({"projects": list_recent_projects(limit=5)})


@mcp.resource("nikk://environment")
def resource_environment() -> str:
    """Estado del sistema operativo, laminadores instalados, IA y MCP."""
    return _json_str(get_system_environment(mcp_tools_count=19))


# ==============================================================================
# 2. ENTORNO, LAMINADORES Y CONFIGURACIÓN IA
# ==============================================================================


@mcp.tool()
def nikk_get_system_environment() -> str:
    """Devuelve sistema operativo, laminadores detectados, proveedor IA activo y endpoints MCP."""
    return _json_str(get_system_environment(mcp_tools_count=19))


@mcp.tool()
def nikk_rescan_slicers() -> str:
    """Re-escanea el sistema (macOS / Windows) en busca de OrcaSlicer, Orca-Flashforge y FLSun Slicer."""
    return _json_str({"slicers": scan_installed_slicers()})


@mcp.tool()
def nikk_set_slicer_path(
    slicer_id: Literal["orcaslicer", "orca_flashforge", "flsun_slicer"],
    executable_path: str,
) -> str:
    """Configura manualmente la ruta del ejecutable de un laminador."""
    return _json_str(set_slicer_path(slicer_id, executable_path))


@mcp.tool()
def nikk_configure_ai(
    provider: Literal["deepseek", "gemini"],
    api_key: str,
) -> str:
    """Guarda localmente el proveedor IA activo (deepseek o gemini) y su API Key."""
    return _json_str(save_ai_config(provider, api_key))


# ==============================================================================
# 3. ANÁLISIS DE MALLA, MULTI-OBJETO Y CAD
# ==============================================================================


@mcp.tool()
def nikk_analyze_model(
    printer_id: str = "creator5_pro_1",
    model_path: str | None = None,
    mesh_id: str | None = None,
    scale_percent: float = 100.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
) -> str:
    """Analiza un STL o 3MF con trimesh (dimensiones, voladizos, colores T0-T3 y objetos separados)."""
    mid, path = _resolve_model_path(model_path, mesh_id)
    printer = get_printer_config(printer_id)
    res = analyze_model_file(
        path,
        printer=printer,
        mesh_id=mid,
        scale_percent=scale_percent,
        rot_x=rot_x,
        rot_y=rot_y,
        rot_z=rot_z,
    )
    return _json_str(res.model_dump())


@mcp.tool()
def nikk_split_objects(
    model_path: str | None = None,
    mesh_id: str | None = None,
) -> str:
    """Divide una malla STL o 3MF en objetos independientes sobre la cama."""
    mid, path = _resolve_model_path(model_path, mesh_id)
    objs = split_mesh_into_scene_objects(path, mid)
    return _json_str({"mesh_id": mid, "scene_objects": [o.model_dump() for o in objs]})


@mcp.tool()
def nikk_auto_arrange(
    printer_id: str,
    mesh_id: str,
    count: int = 2,
    scale_percent: float = 100.0,
) -> str:
    """Distribuye automáticamente `count` copias del modelo sin colisiones en la cama activa."""
    _, path = _resolve_model_path(None, mesh_id)
    printer = get_printer_config(printer_id)
    insts = [
        ModelInstanceTransform(instance_id=f"inst_{i + 1}", scale_percent=scale_percent)
        for i in range(max(1, min(20, count)))
    ]
    res = auto_arrange_instances(path, printer=printer, instances=insts)
    return _json_str(res.model_dump())


@mcp.tool()
def nikk_evaluate_orientations(
    printer_id: str = "creator5_pro_1",
    material: str = "petg",
    model_path: str | None = None,
    mesh_id: str | None = None,
    scale_percent: float = 100.0,
) -> str:
    """Evalúa 5 orientaciones óptimas con trimesh + IA (altura Z, contacto en cama y voladizos)."""
    mid, path = _resolve_model_path(model_path, mesh_id)
    printer = get_printer_config(printer_id)
    geom = evaluate_orientation_candidates(path, printer=printer, mesh_id=mid, scale_percent=scale_percent)
    res = evaluate_orientations_with_ai(geom, printer_name=printer.display_name, material=material)
    return _json_str(res.model_dump())


# ==============================================================================
# 4. ANÁLISIS IA, LAMINADO Y PAUSAS POR CAPA
# ==============================================================================


@mcp.tool()
def nikk_ai_analyze_model(
    printer_id: str,
    material: str = "pla",
    model_path: str | None = None,
    mesh_id: str | None = None,
    nozzle_diameter: float = 0.4,
    high_speed_filament: bool = False,
    lithophane_mode: bool = False,
) -> str:
    """Ejecuta Análisis IA (6 resoluciones 0.08-0.28 mm y título corto en español)."""
    mid, path = _resolve_model_path(model_path, mesh_id)
    printer = get_printer_config(printer_id)
    an = analyze_model_file(path, printer=printer, mesh_id=mid)
    req = AIAnalyzeModelRequest(
        printer_id=printer_id,
        material=material,  # type: ignore[arg-type]
        filename=path.name,
        nozzle_diameter=nozzle_diameter,
        high_speed_filament=high_speed_filament,
        lithophane_mode=lithophane_mode,
        dimensions_mm=DimensionsMM(
            x=an.dimensions_mm.x,
            y=an.dimensions_mm.y,
            z=an.dimensions_mm.z,
        ),
        volume_cm3=(an.dimensions_mm.x * an.dimensions_mm.y * an.dimensions_mm.z) / 1000.0,
        base_contact_area_mm2=an.base_contact_area_mm2,
        overhang_ratio=an.overhang_ratio,
        parts_count=max(1, len(an.multimaterial_parts)),
        is_multicolor=an.is_multicolor,
        detected_extruder_count=an.detected_extruder_count,
    )
    res = analyze_model_for_ai(req)
    return _json_str(res.model_dump())


@mcp.tool()
async def nikk_slice_model(
    printer_id: str = "flsun_t1_pro_1",
    material: str = "pla",
    model_path: str | None = None,
    mesh_id: str | None = None,
    layer_height_mm: float = 0.20,
    supports: bool = False,
    scale_percent: float = 100.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
) -> str:
    """Lamina un modelo 3D con blindaje Q_max, primera capa monotónica y anti-stringing."""
    from app.main import _execute_slice

    mid, path = _resolve_model_path(model_path, mesh_id)
    req = SliceRequest(
        printer_id=printer_id,
        material=material,  # type: ignore[arg-type]
        nozzle_temp=240 if material == "petg" else 210,
        bed_temp=75 if material == "petg" else 60,
        supports=supports,
        layer_height_override=layer_height_mm,
        mesh_id=mid,
        model_filename=path.name,
        scale_percent=scale_percent,
        rot_x=rot_x,
        rot_y=rot_y,
        rot_z=rot_z,
    )
    res = await _execute_slice(req, mid, path)
    return _json_str(res.model_dump())


@mcp.tool()
def nikk_apply_layer_pauses(
    job_id: str,
    printer_id: str,
    pauses_json: str,
) -> str:
    """Inyecta pausas por capa (PAUSE Klipper / M25 FlashForge) sobre un G-code ya laminado (<50ms)."""
    out_dir = TEMP_DIR / job_id / "output"
    cands = [p for p in sorted(out_dir.glob("*.gcode")) if p.name != "model.flashforge.gcode"]
    if not cands:
        raise FileNotFoundError(f"No se encontró .gcode para job_id={job_id}")
    pauses = json.loads(pauses_json)
    _, applied = apply_layer_pauses_to_file(cands[0], printer_id, pauses)
    return _json_str({"job_id": job_id, "applied_pauses": applied})


# ==============================================================================
# 5. CALCULADORA COMERCIAL EN COP
# ==============================================================================


@mcp.tool()
def nikk_calculate_quote(
    printer_id: str,
    material: str,
    hours: int,
    minutes: int,
    grams: float,
    filament_price_per_kg: float = 100000.0,
    energy_rate_kwh: float = 900.0,
    multiplier: float = 3.0,
    units: int = 1,
) -> str:
    """Calcula costo real de taller y precio de venta al cliente en COP$."""
    watts_map = {
        "flsun_t1_pro": 180,
        "flsun_v400": 160,
        "creator5_pro": 150,
        "flsun_sr": 130,
        "ender3_s1_pro": 115,
    }
    cfg = get_printer_config(printer_id)
    watts = watts_map.get(cfg.profile_id, 150)
    total_hours = max(0.0, hours + minutes / 60.0)
    mat_cost = (grams / 1000.0) * filament_price_per_kg
    energy_cost = (watts / 1000.0) * total_hours * energy_rate_kwh
    wear_cost = (600000.0 / 4320.0) * total_hours
    err_pct = 0.05 if material == "pla" else 0.10
    subtotal = mat_cost + energy_cost + wear_cost
    err_cost = subtotal * err_pct
    unit_cost = subtotal + err_cost
    unit_price = unit_cost * multiplier
    return _json_str(
        {
            "printer": cfg.display_name,
            "watts": watts,
            "material_cost_cop": round(mat_cost),
            "energy_cost_cop": round(energy_cost),
            "wear_cost_cop": round(wear_cost),
            "error_margin_cop": round(err_cost),
            "unit_break_even_cop": round(unit_cost),
            "unit_sale_price_cop": round(unit_price),
            "total_sale_price_cop": round(unit_price * max(1, units)),
        }
    )


# ==============================================================================
# 6. GESTIÓN DE PROYECTOS GUARDADOS
# ==============================================================================


@mcp.tool()
def nikk_list_recent_projects(limit: int = 5) -> str:
    """Lista los proyectos recientes guardados en Nikk Slicer con título corto y métricas."""
    return _json_str({"projects": list_recent_projects(limit=max(1, min(20, limit)))})


@mcp.tool()
def nikk_get_project(project_id: str) -> str:
    """Recupera la configuración completa y G-code de un proyecto guardado."""
    proj = get_full_project(project_id)
    if proj is None:
        raise ValueError(f"Proyecto no encontrado: {project_id}")
    return _json_str(proj)


@mcp.tool()
def nikk_delete_project(project_id: str) -> str:
    """Elimina un proyecto guardado del historial."""
    return _json_str({"deleted": delete_full_project(project_id), "project_id": project_id})


@mcp.tool()
def nikk_get_sliced_profile_snapshot(
    job_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Devuelve la instantánea exacta de 7 secciones del perfil efectivo con el que se laminó un `job_id` o `project_id`."""
    if project_id:
        proj = get_full_project(project_id)
        if proj is None:
            raise ValueError(f"Proyecto no encontrado: {project_id}")
        snap = (proj.get("state") or {}).get("sliced_profile_snapshot")
        if isinstance(snap, dict):
            return _json_str({"source": "project", "project_id": project_id, "sliced_profile_snapshot": snap})
        raise ValueError(f"El proyecto {project_id} no contiene sliced_profile_snapshot.")

    if job_id:
        snap_path = TEMP_DIR / job_id / "sliced_profile_snapshot.json"
        if snap_path.is_file():
            return _json_str(
                {
                    "source": "job",
                    "job_id": job_id,
                    "sliced_profile_snapshot": json.loads(snap_path.read_text(encoding="utf-8")),
                }
            )
        out_dir = TEMP_DIR / job_id / "output"
        if out_dir.is_dir():
            for gcode_p in sorted(out_dir.glob("*.gcode")):
                for line in reversed(gcode_p.read_text(encoding="utf-8", errors="ignore").splitlines()):
                    s = line.strip()
                    if s.startswith("; NIKK_SLICER_PROFILE_JSON:"):
                        return _json_str(
                            {
                                "source": "gcode",
                                "job_id": job_id,
                                "sliced_profile_snapshot": json.loads(s.split(":", 1)[1].strip()),
                            }
                        )
        raise FileNotFoundError(f"No se encontró sliced_profile_snapshot para job_id={job_id}")

    raise ValueError("Debes indicar `job_id` o `project_id`.")


# ==============================================================================
# 7. TELEMETRÍA Y CONTROL EN VIVO DE LAS 6 IMPRESORAS
# ==============================================================================


@mcp.tool()
async def nikk_get_printers_status() -> str:
    """Consulta el estado en vivo (temperaturas, progreso, IP y estado) de las 6 impresoras."""
    catalog = load_catalog()
    printers = catalog.get("printers") or []
    out: list[dict[str, Any]] = []
    for p in printers:
        pid = p.get("printer_id", "")
        cfg = get_printer_instance(pid) or {}
        proto = cfg.get("protocol", p.get("protocol", ""))
        try:
            if proto == "moonraker":
                st = await query_moonraker_status(cfg)
            elif proto == "flashforge_lan":
                st = await query_flashforge_status(cfg)
            else:
                st = marlin_manager.get_status(cfg)
            out.append(st.model_dump() if hasattr(st, "model_dump") else dict(st))
        except Exception as exc:
            out.append({"printer_id": pid, "online": False, "error": str(exc)})
    return _json_str({"printers": out})


@mcp.tool()
async def nikk_upload_and_print(
    printer_id: str,
    job_id: str,
    start_print: bool = False,
) -> str:
    """Sube el G-code de `job_id` a la impresora por LAN (Moonraker / FlashForge :8898)."""
    cfg = get_printer_instance(printer_id)
    if not cfg:
        raise ValueError(f"Impresora no encontrada: {printer_id}")
    out_dir = TEMP_DIR / job_id / "output"
    cands = [p for p in sorted(out_dir.glob("*.gcode")) if p.name != "model.flashforge.gcode"]
    if not cands:
        raise FileNotFoundError(f"No hay .gcode en job_id={job_id}")
    gcode_path = cands[0]
    proto = cfg.get("protocol", "")
    if proto == "moonraker":
        msg = await upload_and_start_moonraker(cfg, gcode_path, gcode_path.name, start_immediately=start_print)
    elif proto == "flashforge_lan":
        ff_path = out_dir / "model.flashforge.gcode"
        target = ff_path if ff_path.is_file() else gcode_path
        msg = await upload_and_start_flashforge(cfg, target, gcode_path.name, start_immediately=start_print)
    else:
        raise ValueError(f"Protocolo '{proto}' requiere envío USB/SD desde la UI.")
    return _json_str({"ok": True, "message": msg})


@mcp.tool()
async def nikk_control_printer(
    printer_id: str,
    action: Literal["pause", "resume", "cancel"],
) -> str:
    """Envía un comando de control (pause, resume, cancel) a una impresora en red."""
    cfg = get_printer_instance(printer_id)
    if not cfg:
        raise ValueError(f"Impresora no encontrada: {printer_id}")
    proto = cfg.get("protocol", "")
    if proto == "moonraker":
        msg = await control_moonraker(cfg, action)
    elif proto == "flashforge_lan":
        msg = await control_flashforge(cfg, action)
    else:
        msg = marlin_manager.control(cfg, action)
    return _json_str({"ok": True, "printer_id": printer_id, "action": action, "message": msg})


@mcp.tool()
def nikk_get_error_journal(limit: int = 20) -> str:
    """Consulta la bitácora reciente de errores de laminado y hardware."""
    return _json_str({"entries": read_error_journal(limit=limit)})


@mcp.tool()
def nikk_search_printer_catalog(
    query: str = "",
    vendor: str = "",
    multicolor_only: bool = False,
    limit: int = 30,
) -> str:
    """Busca impresoras en el Catálogo Universal de OrcaSlicer por marca, modelo o soporte multicolor."""
    from app.core.orca_catalog import search_orca_catalog

    return _json_str(
        search_orca_catalog(
            q=query,
            vendor=vendor,
            multicolor_only=multicolor_only,
            limit=limit,
        )
    )


@mcp.tool()
def nikk_add_custom_printer(
    catalog_id: str,
    display_name: str = "",
    nozzle_diameter: float = 0.4,
    connection_mode: Literal["lan", "usb_sd"] = "lan",
    ip: str = "",
    port: int | None = None,
    protocol: str = "",
    is_multicolor: bool | None = None,
    tool_count: int | None = None,
) -> str:
    """Agrega una impresora del catálogo OrcaSlicer a la granja del usuario (`user_printers.json`)."""
    from app.core.printer_registry import add_user_printer_from_catalog

    record = add_user_printer_from_catalog(
        catalog_id=catalog_id,
        display_name=display_name or None,
        nozzle_diameter=nozzle_diameter,
        connection_mode=connection_mode,
        ip=ip,
        port=port,
        protocol=protocol or None,
        is_multicolor=is_multicolor,
        tool_count=tool_count,
    )
    return _json_str({"ok": True, "printer": record})


def get_mcp_asgi_app():
    """Devuelve la sub-aplicación ASGI Streamable HTTP de MCP para montar en `/mcp`."""
    return mcp.streamable_http_app(streamable_http_path="/")


if __name__ == "__main__":
    mcp.run(transport="stdio")
