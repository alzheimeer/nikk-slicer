"""Servidor FastAPI principal de SlicerHub."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

logger = logging.getLogger("slicerhub.main")

from app.config import (
    DEFAULT_SUPPORT_XY_BY_MATERIAL,
    DEFAULT_SUPPORT_Z_BY_MATERIAL,
    MATERIAL_TO_PROFILE,
    MESH_CACHE_DIR,
    NOZZLE_DIAMETERS,
    PRESET_TO_PROFILE,
    PRINTER_REGISTRY,
    PROJECT_ROOT,
    PrinterConfig,
    TEMP_DIR,
    detect_macos_serial_and_volumes,
    get_masked_ai_keys,
    get_printer_config,
    get_printer_instance,
    load_catalog,
    load_printers_config,
    save_ai_keys_to_env,
    save_printers_config,
)
from app.connectors import (
    control_flashforge,
    control_moonraker,
    delete_flashforge_file,
    delete_moonraker_file,
    download_moonraker_file,
    get_flashforge_file_thumbnail,
    get_moonraker_file_thumbnail,
    list_flashforge_files,
    list_moonraker_files,
    list_moonraker_timelapses,
    marlin_manager,
    print_flashforge_file,
    print_moonraker_file,
    query_flashforge_status,
    query_moonraker_status,
    set_flashforge_light,
    set_moonraker_light,
    upload_and_start_flashforge,
    upload_and_start_moonraker,
)
from app.core.ai_copilot import (
    _call_ai_json,
    analyze_model_for_ai,
    diagnose_live_telemetry,
    diagnose_print_defect,
    evaluate_orientations_with_ai,
    generate_ai_recommendation,
    generate_ai_support_decision,
    optimize_slice_with_ai,
)
from app.core.platform_detector import (
    get_system_environment,
    save_ai_config,
    scan_installed_slicers,
    set_slicer_path,
)
from app.core.orca_catalog import (
    search_orca_catalog,
    sync_orca_catalog_from_github,
)
from app.core.printer_registry import (
    add_user_printer_from_catalog,
    delete_user_printer,
    update_user_printer,
)
from app.core.project_manager import (
    delete_full_project,
    get_full_project,
    get_project_model_path,
    get_project_thumbnail_path,
    list_recent_projects,
    save_full_project,
)
from app.core.project_store import (
    get_saved_project,
    list_saved_projects,
    save_slice_project,
)
from app.core.error_journal import (
    ERROR_JOURNAL_LOG_PATH,
    clear_error_journal,
    read_error_journal,
    record_error,
)
from app.core.flashforge_3mf_exporter import export_flashforge_gcode_3mf
from app.core.gcode_3mf_packager import package_gcode_as_3mf, prepare_flashforge_gcode
from app.core.local_timelapse_recorder import local_timelapse_recorder
from app.core.gcode_postprocessor import apply_layer_pauses_to_file
from app.core.json_patcher import (
    build_sliced_profile_snapshot,
    inject_profile_snapshot_into_gcode,
    patch_profiles_for_job,
)
from app.core.print_telemetry_recorder import (
    get_machine_material_learnings,
    telemetry_recorder,
    telemetry_recorder_worker,
)
from app.core.mesh_analyzer import (
    analyze_model_file,
    assemble_scene_objects_for_slicer,
    export_instances_with_support_paint_3mf,
    export_selection_to_file,
    auto_arrange_instances,
    auto_orient_mesh,
    compute_lay_on_face_candidates,
    cut_mesh_by_plane,
    evaluate_orientation_candidates,
    evaluate_plate_orientation_candidates,
    find_optimal_anti_support_orientation,
    get_scene_object_stl_path,
    import_models_to_plate,
    inject_support_blockers_into_3mf,
    load_and_transform_mesh,
    prepare_painted_3mf_for_slicer,
    sanitize_euler_rotation,
    split_mesh_into_scene_objects,
    transform_and_export_3mf_parts,
)
from app.core.slicer_router import run_slicer_cli
from app.models.schemas import (
    AIAnalyzeModelRequest,
    AIAnalyzeModelResponse,
    AIDefectDiagnoseRequest,
    AIDefectDiagnoseResponse,
    AIOptimizeSliceRequest,
    AIOptimizeSliceResponse,
    AIOrientationsResponse,
    AIRecommendRequest,
    AIRecommendResponse,
    AISupportOrientResponse,
    AITelemetryDiagnosisResponse,
    AdhesionType,
    ApplyPausesRequest,
    ApplyPausesResponse,
    AutoArrangeRequest,
    AutoArrangeResponse,
    AutoOrientResponse,
    CutMeshResponse,
    ExportSelectionRequest,
    ExtruderSlotConfig,
    ImportToPlateResponse,
    LayerPauseItem,
    LayOnFaceResponse,
    MachineMaterialLearningsResponse,
    MaterialType,
    MeshAnalysisResponse,
    ModelInstanceTransform,
    PostPrintCompendium,
    PrinterControlRequest,
    PrinterFileActionRequest,
    PrinterFilesResponse,
    PrinterId,
    PrinterLightRequest,
    PrinterLiveStatus,
    PrinterNetworkEntry,
    PrinterTelemetrySessionResponse,
    PrinterTimelapsesResponse,
    PrintersConfigPayload,
    PrintersConfigResponse,
    SaveProjectRequest,
    SceneObjectTransform,
    SplitObjectsResponse,
    QualityPreset,
    SendPrintRequest,
    SendPrintResponse,
    SliceRequest,
    SliceResponse,
    SupportType,
    UploadToPrinterRequest,
    ZColorRange,
)

async def _poll_enabled_for_recorder() -> list[PrinterLiveStatus]:
    configs = load_printers_config()
    tasks = [
        _query_single_printer(pid, cfg, timeout=2.2)
        for pid, cfg in configs.items()
        if cfg.get("enabled", True) and telemetry_recorder.should_poll_printer(pid, max_age_sec=9.0)
    ]
    if not tasks:
        return []
    results = list(await asyncio.gather(*tasks))
    for st in results:
        local_timelapse_recorder.ingest_status(st, st.camera_url)
    return results


@asynccontextmanager
async def lifespan(_app: FastAPI):
    telemetry_recorder.load_persisted_state()
    local_timelapse_recorder.load_persisted_state()
    worker_task = asyncio.create_task(
        telemetry_recorder_worker(_poll_enabled_for_recorder, interval_sec=10.0)
    )
    try:
        from app.mcp_server import mcp as _mcp_server
        async with _mcp_server.session_manager.run():
            yield
    except ImportError:
        yield
    finally:
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Nikk Slicer API",
    version="1.3.0",
    description="API de laminado unificado, caché STL, IA y conectores de hardware para macOS (Nikk Slicer).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def _http_exception_journal_handler(request: Request, exc: HTTPException):
    if exc.status_code >= 500 or request.url.path.startswith(("/api/slice", "/api/ai-")):
        detail_str = (
            json.dumps(exc.detail, ensure_ascii=False)
            if not isinstance(exc.detail, str)
            else exc.detail
        )
        # Evitar duplicar si slicer_router ya registró el error CLI exacto
        if "Error en laminado CLI" not in detail_str:
            record_error(
                f"http_{exc.status_code}",
                detail_str,
                detail=f"{request.method} {request.url.path}",
            )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def _unhandled_exception_journal_handler(request: Request, exc: Exception):
    err_msg = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    record_error(
        "unhandled_exception",
        err_msg,
        detail=f"{request.method} {request.url.path}",
    )
    return JSONResponse(status_code=500, content={"detail": err_msg})


@app.get("/api/health")
def health_endpoint() -> dict[str, str]:
    """Comprobación rápida de disponibilidad para el lanzador de escritorio."""
    return {"status": "ok", "app": "Nikk Slicer", "version": "1.3.0"}


@app.get("/api/logs/errors")
def get_error_journal_endpoint(limit: int = 60) -> dict[str, Any]:
    """Devuelve las entradas recientes de la bitácora de errores y la ruta del archivo `.log`."""
    entries = read_error_journal(limit=limit)
    return {
        "log_path": str(ERROR_JOURNAL_LOG_PATH),
        "count": len(entries),
        "entries": entries,
    }


@app.delete("/api/logs/errors")
def clear_error_journal_endpoint() -> dict[str, str]:
    """Limpia los archivos de bitácora de errores."""
    clear_error_journal()
    return {"status": "ok", "message": "Bitácora de errores limpiada."}


USER_PREFS_PATH = TEMP_DIR / "user_prefs.json"


@app.get("/api/prefs")
def get_user_prefs_endpoint() -> dict[str, Any]:
    """Lee las preferencias persistentes del usuario y la última sesión de modelo si aún existe en caché."""
    if not USER_PREFS_PATH.is_file():
        return {"prefs": {}}
    try:
        data = json.loads(USER_PREFS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"prefs": {}}
    except Exception:
        return {"prefs": {}}

    last_sess = data.get("last_session")
    if isinstance(last_sess, dict):
        mid = str(last_sess.get("mesh_id") or "").strip()
        if not mid or not any(MESH_CACHE_DIR.glob(f"{mid}.*")):
            data.pop("last_session", None)
    return {"prefs": data}


@app.put("/api/prefs")
def save_user_prefs_endpoint(payload: dict[str, Any]) -> dict[str, str]:
    """Guarda en disco las preferencias de usuario (incluidos T0-T3 y última sesión)."""
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload inválido.")
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if USER_PREFS_PATH.is_file():
        try:
            loaded = json.loads(USER_PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}
    existing.update(payload)
    tmp_path = USER_PREFS_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_path, USER_PREFS_PATH)
    return {"status": "ok"}


@app.delete("/api/prefs/last-session")
def clear_last_session_endpoint() -> dict[str, str]:
    """Elimina la última sesión guardada cuando el usuario decide iniciar un proyecto nuevo."""
    if USER_PREFS_PATH.is_file():
        try:
            data = json.loads(USER_PREFS_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "last_session" in data:
                data.pop("last_session", None)
                tmp_path = USER_PREFS_PATH.with_suffix(".json.tmp")
                tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp_path, USER_PREFS_PATH)
        except Exception:
            pass
    return {"status": "ok"}


def _save_upload(upload: UploadFile, target_path: Path) -> None:
    if not upload.filename or not upload.filename.lower().endswith((".stl", ".3mf")):
        raise HTTPException(
            status_code=400, detail="Solo se admiten archivos .stl o .3mf."
        )
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with target_path.open("wb") as fh:
        shutil.copyfileobj(upload.file, fh)


def _resolve_cached_stl(
    file: UploadFile | None,
    mesh_id: str | None,
) -> tuple[str, Path]:
    """Obtiene el STL/.3MF desde caché (`mesh_id`) o guarda el archivo recién subido."""
    if file is not None and file.filename:
        lower = file.filename.lower()
        if not lower.endswith((".stl", ".3mf")):
            raise HTTPException(
                status_code=400, detail="Solo se admiten archivos .stl o .3mf."
            )
        ext = ".3mf" if lower.endswith(".3mf") else ".stl"
        new_mesh_id = uuid.uuid4().hex[:12]
        cached_path = MESH_CACHE_DIR / f"{new_mesh_id}{ext}"
        _save_upload(file, cached_path)
        return new_mesh_id, cached_path

    if mesh_id:
        if not mesh_id.isalnum():
            raise HTTPException(status_code=400, detail="mesh_id inválido.")
        for ext in (".stl", ".3mf"):
            cached_path = MESH_CACHE_DIR / f"{mesh_id}{ext}"
            if cached_path.exists():
                return mesh_id, cached_path
        raise HTTPException(
            status_code=404,
            detail="Malla no encontrada en caché; vuelve a cargar el archivo .stl/.3mf.",
        )

    raise HTTPException(
        status_code=400,
        detail="Debes proporcionar un archivo .stl/.3mf o un mesh_id válido.",
    )


def _resolve_printer_or_400(printer_id: str) -> PrinterConfig:
    try:
        return get_printer_config(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/catalog")
def get_catalog() -> dict[str, Any]:
    """Retorna el catálogo completo de instancias de impresoras, perfiles base, boquillas y rangos."""
    catalog = load_catalog()
    configs = load_printers_config()
    printers: list[dict[str, Any]] = []
    for inst_id, inst_cfg in configs.items():
        if not inst_cfg.get("enabled", True):
            continue
        profile_id = str(inst_cfg.get("profile_id", "flsun_t1_pro"))
        base = PRINTER_REGISTRY.get(profile_id)
        if not base:
            continue
        resolved = get_printer_config(inst_id)
        printers.append(
            {
                "printer_id": inst_id,
                "profile_id": profile_id,
                "display_name": inst_cfg.get("name") or resolved.display_name,
                "vendor": resolved.vendor,
                "model_name": resolved.model_name,
                "ip": inst_cfg.get("ip", ""),
                "port": inst_cfg.get("port", 7125),
                "protocol": inst_cfg.get("protocol", "moonraker"),
                "connection_mode": inst_cfg.get("connection_mode", "lan" if inst_cfg.get("ip") else "usb_sd"),
                "camera_url": inst_cfg.get("camera_url", ""),
                "enabled": bool(inst_cfg.get("enabled", True)),
                "is_custom": bool(inst_cfg.get("is_custom", False)),
                "kinematics": resolved.kinematics,
                "origin": resolved.origin,
                "bed_shape": resolved.bed_shape,
                "diameter_mm": resolved.diameter_mm,
                "height_mm": resolved.height_mm,
                "bed_mm": list(resolved.bed_mm) if resolved.bed_mm else None,
                "usable_edge_z_mm": resolved.usable_edge_z_mm,
                "max_volumetric_flow_mm3_s": resolved.max_volumetric_flow_mm3_s,
                "extruder_slots": resolved.extruder_slots,
                "gcode_flavor": resolved.gcode_flavor,
                "is_multicolor": resolved.is_multicolor,
                "tool_count": resolved.extruder_slots,
                "has_heated_chamber": resolved.has_heated_chamber,
                "is_high_speed": resolved.is_high_speed,
                "nozzle_diameter": resolved.nozzle_diameter,
                "cli_binary": str(resolved.cli_binary),
            }
        )

    machine_profiles = [
        {
            "profile_id": cfg.profile_id,
            "display_name": cfg.display_name,
            "kinematics": cfg.kinematics,
            "origin": cfg.origin,
            "diameter_mm": cfg.diameter_mm,
            "height_mm": cfg.height_mm,
            "bed_mm": list(cfg.bed_mm) if cfg.bed_mm else None,
            "max_volumetric_flow_mm3_s": cfg.max_volumetric_flow_mm3_s,
            "extruder_slots": cfg.extruder_slots,
        }
        for cfg in PRINTER_REGISTRY.values()
    ]

    return {
        "printers": printers,
        "machine_profiles": machine_profiles,
        "materials": list(MATERIAL_TO_PROFILE.keys()),
        "quality_presets": list(PRESET_TO_PROFILE.keys()),
        "nozzle_diameters": list(NOZZLE_DIAMETERS),
        "default_support_z_distance": catalog.get(
            "default_support_z_distance", DEFAULT_SUPPORT_Z_BY_MATERIAL
        ),
        "default_support_xy_distance": catalog.get(
            "default_support_xy_distance", DEFAULT_SUPPORT_XY_BY_MATERIAL
        ),
        "material_temp_ranges": catalog.get("material_temp_ranges", {}),
        "volumetric_limits_mm3_s": catalog.get("volumetric_limits_mm3_s", {}),
        "high_speed_volumetric_limits_mm3_s": catalog.get(
            "high_speed_volumetric_limits_mm3_s", {}
        ),
        "cli_runtime": catalog.get("cli_runtime", {}),
    }


def _parse_instances_json(raw_json: str | None) -> list[ModelInstanceTransform]:
    if not raw_json:
        return []
    try:
        raw_list = json.loads(raw_json)
        if not isinstance(raw_list, list):
            raise ValueError("Se esperaba lista JSON en instances_json.")
        return [ModelInstanceTransform(**item) for item in raw_list]
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"instances_json inválido: {exc}"
        ) from exc


@app.post("/api/analyze-mesh", response_model=MeshAnalysisResponse)
def analyze_mesh_endpoint(
    printer_id: PrinterId = Form(...),
    mesh_id: str | None = Form(None),
    scale_percent: float = Form(100.0),
    scale_x: float | None = Form(None),
    scale_y: float | None = Form(None),
    scale_z: float | None = Form(None),
    rot_x: float = Form(0.0),
    rot_y: float = Form(0.0),
    rot_z: float = Form(0.0),
    offset_x: float = Form(0.0),
    offset_y: float = Form(0.0),
    offset_z: float = Form(0.0),
    drop_to_bed: bool = Form(True),
    instances_json: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> MeshAnalysisResponse:
    """Guarda/reutiliza la malla (.stl/.3mf) en caché, aplica transformaciones CAD y analiza volumen."""
    printer = _resolve_printer_or_400(printer_id)
    resolved_id, cached_path = _resolve_cached_stl(file, mesh_id)
    parsed_instances = _parse_instances_json(instances_json)
    try:
        return analyze_model_file(
            cached_path,
            printer,
            mesh_id=resolved_id,
            scale_percent=scale_percent,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
            offset_x=offset_x,
            offset_y=offset_y,
            offset_z=offset_z,
            drop_to_bed=drop_to_bed,
            instances=parsed_instances,
        )
    except ValueError as exc:
        if file is not None:
            cached_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/auto-arrange", response_model=AutoArrangeResponse)
def auto_arrange_endpoint(req: AutoArrangeRequest) -> AutoArrangeResponse:
    """Empaqueta N instancias en cama circular (Delta) o rectangular sin colisiones."""
    printer = _resolve_printer_or_400(req.printer_id)
    _, cached_path = _resolve_cached_stl(None, req.mesh_id)
    try:
        return auto_arrange_instances(
            cached_path,
            printer=printer,
            instances=req.instances,
            min_distance_mm=req.min_distance_mm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/lay-on-face", response_model=LayOnFaceResponse)
def lay_on_face_endpoint(
    printer_id: PrinterId = Form(...),
    mesh_id: str | None = Form(None),
    scale_percent: float = Form(100.0),
    scale_x: float | None = Form(None),
    scale_y: float | None = Form(None),
    scale_z: float | None = Form(None),
    rot_x: float = Form(0.0),
    rot_y: float = Form(0.0),
    rot_z: float = Form(0.0),
    file: UploadFile | None = File(None),
) -> LayOnFaceResponse:
    """Extrae facetas planas del casco convexo (`LayOnFace`) y rotaciones para Z = 0."""
    _ = _resolve_printer_or_400(printer_id)
    resolved_id, cached_path = _resolve_cached_stl(file, mesh_id)
    try:
        return compute_lay_on_face_candidates(
            cached_path,
            mesh_id=resolved_id,
            scale_percent=scale_percent,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/cut-mesh", response_model=CutMeshResponse)
def cut_mesh_endpoint(
    printer_id: PrinterId = Form(...),
    mesh_id: str | None = Form(None),
    cut_z_mm: float = Form(...),
    tilt_x_deg: float = Form(0.0),
    tilt_y_deg: float = Form(0.0),
    keep_mode: str = Form("both"),
    scale_percent: float = Form(100.0),
    scale_x: float | None = Form(None),
    scale_y: float | None = Form(None),
    scale_z: float | None = Form(None),
    rot_x: float = Form(0.0),
    rot_y: float = Form(0.0),
    rot_z: float = Form(0.0),
    file: UploadFile | None = File(None),
) -> CutMeshResponse:
    """Secciona un modelo en Z/ángulo devolviendo malla(s) cerrada(s) lista(s) para laminar."""
    if keep_mode not in ("upper", "lower", "both"):
        raise HTTPException(status_code=400, detail="keep_mode debe ser 'upper', 'lower' o 'both'.")
    printer = _resolve_printer_or_400(printer_id)
    _, cached_path = _resolve_cached_stl(file, mesh_id)
    try:
        new_id, _out_path, parts_count, analysis = cut_mesh_by_plane(
            cached_path,
            printer=printer,
            cut_z_mm=cut_z_mm,
            tilt_x_deg=tilt_x_deg,
            tilt_y_deg=tilt_y_deg,
            keep_mode=keep_mode,
            scale_percent=scale_percent,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
        )
        return CutMeshResponse(
            mesh_id=new_id,
            download_url=f"/api/meshes/{new_id}",
            keep_mode=keep_mode,  # type: ignore[arg-type]
            cut_z_mm=cut_z_mm,
            parts_count=parts_count,
            message=f"Corte por plano aplicado ({parts_count} sólido(s) cerrado(s) a Z={cut_z_mm:.1f} mm).",
            analysis=analysis,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/meshes/{mesh_id}")
def download_cached_mesh(mesh_id: str) -> FileResponse:
    """Descarga una malla STL/.3MF desde caché (`mesh_id`), ej. tras ejecutar corte geométrico."""
    if not mesh_id.isalnum():
        raise HTTPException(status_code=400, detail="mesh_id inválido.")
    for ext in (".stl", ".3mf"):
        cached = MESH_CACHE_DIR / f"{mesh_id}{ext}"
        if cached.exists():
            return FileResponse(
                path=cached,
                media_type="application/octet-stream",
                filename=f"slicerhub_{mesh_id}{ext}",
            )
    raise HTTPException(status_code=404, detail="Malla no encontrada en caché.")


@app.get("/api/models/{mesh_id}/objects/{object_id}.stl")
async def get_scene_object_stl_endpoint(mesh_id: str, object_id: str) -> FileResponse:
    """Sirve el archivo STL individual de un objeto extraído de `.3mf` o dividido."""
    stl_path = get_scene_object_stl_path(mesh_id, object_id)
    if stl_path is None:
        raise HTTPException(status_code=404, detail="Objeto 3D no encontrado en caché.")
    return FileResponse(path=stl_path, media_type="application/octet-stream", filename=f"{object_id}.stl")


@app.get("/api/models/{mesh_id}/objects/{object_id}.paint.json")
async def get_scene_object_paint_endpoint(mesh_id: str, object_id: str) -> Response:
    """Sirve el mapa `paint_color` por triángulo de un objeto dividido si existe."""
    stl_path = get_scene_object_stl_path(mesh_id, object_id)
    if stl_path is None:
        raise HTTPException(status_code=404, detail="Objeto 3D no encontrado en caché.")
    paint_path = stl_path.with_name(f"{object_id}.paint.json")
    if not paint_path.is_file():
        return JSONResponse({"paint_colors": [], "palette": []})
    return FileResponse(path=paint_path, media_type="application/json")


@app.post("/api/export-selection")
async def export_selection_endpoint(req: ExportSelectionRequest) -> FileResponse:
    """Exporta las piezas seleccionadas o el plato completo a .3MF, .STL (binario) o .OBJ."""
    printer = _resolve_printer_or_400(req.printer_id)
    export_dir = TEMP_DIR / f"export_{uuid.uuid4().hex[:10]}"
    try:
        out_path = export_selection_to_file(
            req.mesh_id,
            export_dir,
            printer,
            fmt=req.format,
            apply_transforms=req.apply_transforms,
            center_on_bed=req.center_on_bed,
            scene_objects=req.scene_objects,
            instances=req.instances,
            part_extruder_map=req.part_extruder_map,
            filename_base=req.filename_base,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    media_type = (
        "application/vnd.ms-package.3dmanufacturing-3dmodel+xml"
        if out_path.suffix.lower() == ".3mf"
        else "application/octet-stream"
    )
    return FileResponse(path=out_path, media_type=media_type, filename=out_path.name)


@app.post("/api/models/split-objects", response_model=SplitObjectsResponse)
async def split_objects_endpoint(
    printer_id: PrinterId = Form(...),
    mesh_id: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> SplitObjectsResponse:
    """Divide una malla STL/3MF en objetos independientes mediante `trimesh.split`."""
    _resolve_printer_or_400(printer_id)
    resolved_id, cached_path = _resolve_cached_stl(file, mesh_id)
    try:
        objs = split_mesh_into_scene_objects(cached_path, resolved_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SplitObjectsResponse(mesh_id=resolved_id, scene_objects=objs)


@app.post("/api/models/import-to-plate", response_model=ImportToPlateResponse)
async def import_to_plate_endpoint(
    printer_id: PrinterId = Form(...),
    mesh_id: str | None = Form(None),
    has_existing_scene_objects: bool = Form(False),
    base_extruder: int = Form(1),
    base_name: str = Form("Pieza 1"),
    files: list[UploadFile] = File(...),
) -> ImportToPlateResponse:
    """Importa archivos `.3mf`, `.stl`, `.obj`, `.amf`, `.step`/`.stp` o `.zip` al plato activo."""
    _resolve_printer_or_400(printer_id)
    if not files:
        raise HTTPException(status_code=400, detail="Debes adjuntar al menos un archivo 3D compatible.")
    tmp_dir = TEMP_DIR / f"import_{uuid.uuid4().hex[:10]}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    saved_inputs: list[tuple[Path, str]] = []
    try:
        for idx, up in enumerate(files):
            orig_name = Path(up.filename or f"modelo_{idx + 1}.stl").name
            target = tmp_dir / f"{idx}_{orig_name}"
            _save_upload(up, target)
            saved_inputs.append((target, orig_name))
        resolved_id, base_objs, imported_objs = import_models_to_plate(
            saved_inputs,
            base_mesh_id=mesh_id,
            has_existing_scene_objects=has_existing_scene_objects,
            base_extruder=base_extruder,
            base_name=base_name,
        )
        return ImportToPlateResponse(
            mesh_id=resolved_id,
            base_objects=base_objs,
            imported_objects=imported_objs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/auto-orient", response_model=AutoOrientResponse)
def auto_orient_endpoint(
    printer_id: PrinterId = Form(...),
    mesh_id: str | None = Form(None),
    scale_percent: float = Form(100.0),
    file: UploadFile | None = File(None),
) -> AutoOrientResponse:
    """Calcula rotación óptima con `oriented_bounds` manteniendo la escala actual."""
    printer = _resolve_printer_or_400(printer_id)
    resolved_id, cached_path = _resolve_cached_stl(file, mesh_id)
    try:
        return auto_orient_mesh(
            cached_path,
            printer=printer,
            mesh_id=resolved_id,
            scale_percent=scale_percent,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/ai/orientations", response_model=AIOrientationsResponse)
def ai_orientations_endpoint(
    printer_id: PrinterId = Form(...),
    material: MaterialType = Form("pla"),
    mesh_id: str | None = Form(None),
    scale_percent: float = Form(100.0),
    object_id: str | None = Form(None),
    scene_objects_json: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> AIOrientationsResponse:
    """Evalúa 5 orientaciones óptimas (trimesh + DeepSeek IA) por pieza o plato completo."""
    printer = _resolve_printer_or_400(printer_id)
    resolved_id, cached_path = _resolve_cached_stl(file, mesh_id)
    try:
        if object_id and object_id.strip():
            obj_stl = get_scene_object_stl_path(resolved_id, object_id.strip())
            if obj_stl is None:
                raise ValueError(f"Objeto '{object_id}' no encontrado en caché.")
            geom_result = evaluate_orientation_candidates(
                obj_stl,
                printer=printer,
                mesh_id=resolved_id,
                scale_percent=scale_percent,
            )
            geom_result["target_object_id"] = object_id.strip()
        elif scene_objects_json:
            raw_objs = json.loads(scene_objects_json)
            if isinstance(raw_objs, list) and len(raw_objs) > 1:
                geom_result = evaluate_plate_orientation_candidates(
                    resolved_id,
                    scene_objects=raw_objs,
                    printer=printer,
                    scale_percent=scale_percent,
                )
            else:
                geom_result = evaluate_orientation_candidates(
                    cached_path,
                    printer=printer,
                    mesh_id=resolved_id,
                    scale_percent=scale_percent,
                )
        else:
            geom_result = evaluate_orientation_candidates(
                cached_path,
                printer=printer,
                mesh_id=resolved_id,
                scale_percent=scale_percent,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return evaluate_orientations_with_ai(
        geom_result,
        printer_name=printer.display_name,
        material=material,
    )


@app.post("/api/ai-recommend", response_model=AIRecommendResponse)
def ai_recommend_endpoint(req: AIRecommendRequest) -> AIRecommendResponse:
    """Recomienda soportes, Z-distance, balsa y temperaturas usando Gemini/DeepSeek o heurística."""
    return generate_ai_recommendation(req)


@app.post("/api/ai-support-orient", response_model=AISupportOrientResponse)
def ai_support_orient_endpoint(
    printer_id: PrinterId = Form(...),
    material: MaterialType = Form("pla"),
    nozzle_diameter: float = Form(0.4),
    high_speed_filament: bool = Form(False),
    lithophane_mode: bool = Form(False),
    mesh_id: str | None = Form(None),
    scale_percent: float = Form(100.0),
    rot_x: float = Form(0.0),
    rot_y: float = Form(0.0),
    rot_z: float = Form(0.0),
    current_support_config_json: str | None = Form(None),
    current_slice_metrics_json: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> AISupportOrientResponse:
    """Calcula ángulo óptimo anti-soportes y evalúa vía DeepSeek API contra el corte real."""
    printer = _resolve_printer_or_400(printer_id)
    resolved_id, cached_path = _resolve_cached_stl(file, mesh_id)
    clean_rx, clean_ry, clean_rz = sanitize_euler_rotation(rot_x, rot_y, rot_z)
    try:
        best_euler, eff_scale, metrics, analysis = find_optimal_anti_support_orientation(
            cached_path,
            printer=printer,
            mesh_id=resolved_id,
            scale_percent=scale_percent,
            current_rotation=(clean_rx, clean_ry, clean_rz),
            lithophane_mode=lithophane_mode,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    parsed_sup_cfg = None
    if current_support_config_json:
        try:
            parsed_sup_cfg = json.loads(current_support_config_json)
        except Exception:
            parsed_sup_cfg = None
    parsed_slice_metrics = None
    if current_slice_metrics_json:
        try:
            parsed_slice_metrics = json.loads(current_slice_metrics_json)
        except Exception:
            parsed_slice_metrics = None

    return generate_ai_support_decision(
        printer_id=printer_id,
        material="pla" if lithophane_mode else material,
        nozzle_diameter=nozzle_diameter,
        high_speed_filament=high_speed_filament,
        mesh_id=resolved_id,
        best_euler=best_euler,
        effective_scale=eff_scale,
        metrics=metrics,
        analysis=analysis,
        current_support_config=parsed_sup_cfg,
        current_slice_metrics=parsed_slice_metrics,
        lithophane_mode=lithophane_mode,
    )


_MESH_SLICE_LOCKS: dict[str, asyncio.Lock] = {}


def _get_mesh_slice_lock(mesh_id: str) -> asyncio.Lock:
    lock = _MESH_SLICE_LOCKS.get(mesh_id)
    if lock is None:
        lock = asyncio.Lock()
        _MESH_SLICE_LOCKS[mesh_id] = lock
    return lock


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def _persist_snapshot_sidecar(
    job_id: str,
    target_filename: str | None = None,
    *,
    extra_dir: Path | None = None,
) -> Path | None:
    """Guarda automáticamente `<nombre_del_gcode>.json` junto al .gcode y en el directorio del job."""
    job_dir = TEMP_DIR / job_id
    snap_path = job_dir / "sliced_profile_snapshot.json"
    if not snap_path.is_file():
        return None
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8"))
        if not isinstance(snap, dict):
            return None
    except Exception:
        return None
    out_dir = job_dir / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(target_filename).stem if target_filename else f"slicerhub_{job_id}"
    if target_filename:
        others = snap.setdefault("others", {})
        if isinstance(others, dict):
            others["gcode_filename"] = target_filename
        snap_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    sidecar_path = out_dir / f"{stem}.json"
    sidecar_path.write_text(json.dumps(snap, indent=2, ensure_ascii=False), encoding="utf-8")
    if extra_dir is not None and extra_dir.is_dir():
        try:
            (extra_dir / f"{stem}.json").write_text(
                json.dumps(snap, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
    return sidecar_path


def _execute_slice_job_sync(
    req: SliceRequest,
    printer: PrinterConfig,
    cached_path: Path,
    resolved_id: str,
) -> SliceResponse:
    job_id = uuid.uuid4().hex[:12]
    job_dir = TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    is_3mf = cached_path.suffix.lower() == ".3mf"
    try:
        analysis = analyze_model_file(
            cached_path,
            printer,
            mesh_id=resolved_id,
            scale_percent=req.scale_percent,
            rot_x=req.rot_x,
            rot_y=req.rot_y,
            rot_z=req.rot_z,
            scale_x=req.scale_x,
            scale_y=req.scale_y,
            scale_z=req.scale_z,
            offset_x=req.offset_x,
            offset_y=req.offset_y,
            offset_z=req.offset_z,
            drop_to_bed=req.drop_to_bed,
            instances=req.instances,
        )
    except ValueError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not analysis.fits_in_volume:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(
            status_code=400,
            detail={
                "message": "El modelo excede el volumen de construcción de la impresora.",
                "warnings": analysis.warnings,
            },
        )

    use_multimaterial_3mf = (
        is_3mf
        and printer.profile_id == "creator5_pro"
        and len(analysis.multimaterial_parts) > 1
    )
    use_painted_3mf = (
        is_3mf
        and printer.profile_id == "creator5_pro"
        and not use_multimaterial_3mf
        and analysis.is_multicolor
    )

    if len(req.scene_objects) > 0:
        assembled_3mf_path = assemble_scene_objects_for_slicer(
            resolved_id,
            req.scene_objects,
            job_dir,
            printer,
            part_extruder_map=req.part_extruder_map,
        )
        patched = patch_profiles_for_job(
            req,
            job_dir,
            multimaterial_3mf=(printer.profile_id == "creator5_pro" and len(req.scene_objects) > 1),
            is_multicolor=bool(analysis.is_multicolor),
            model_dimensions_mm=(
                analysis.dimensions_mm.x,
                analysis.dimensions_mm.y,
                analysis.dimensions_mm.z,
            ),
        )
        model_input = assembled_3mf_path
        f_ids = None
    elif use_multimaterial_3mf:
        assembled_3mf_path, _filament_ids = transform_and_export_3mf_parts(
            cached_path,
            job_dir,
            printer,
            scale_percent=req.scale_percent,
            rot_x=req.rot_x,
            rot_y=req.rot_y,
            rot_z=req.rot_z,
            part_extruder_map=req.part_extruder_map,
            scale_x=req.scale_x,
            scale_y=req.scale_y,
            scale_z=req.scale_z,
            offset_x=req.offset_x,
            offset_y=req.offset_y,
            offset_z=req.offset_z,
            drop_to_bed=req.drop_to_bed,
            instances=req.instances,
        )
        patched = patch_profiles_for_job(
            req,
            job_dir,
            multimaterial_3mf=True,
            is_multicolor=bool(analysis.is_multicolor),
            model_dimensions_mm=(
                analysis.dimensions_mm.x,
                analysis.dimensions_mm.y,
                analysis.dimensions_mm.z,
            ),
        )
        model_input: Path | list[Path] = assembled_3mf_path
        f_ids: list[int] | None = None
    elif use_painted_3mf:
        painted_3mf_path = prepare_painted_3mf_for_slicer(
            cached_path,
            job_dir,
            printer,
            scale_percent=req.scale_percent,
            rot_x=req.rot_x,
            rot_y=req.rot_y,
            rot_z=req.rot_z,
            scale_x=req.scale_x,
            scale_y=req.scale_y,
            scale_z=req.scale_z,
            offset_x=req.offset_x,
            offset_y=req.offset_y,
            offset_z=req.offset_z,
            drop_to_bed=req.drop_to_bed,
            instances=req.instances,
            part_extruder_map=req.part_extruder_map,
        )
        patched = patch_profiles_for_job(
            req,
            job_dir,
            multimaterial_3mf=True,
            is_multicolor=bool(analysis.is_multicolor),
            model_dimensions_mm=(
                analysis.dimensions_mm.x,
                analysis.dimensions_mm.y,
                analysis.dimensions_mm.z,
            ),
        )
        model_input = painted_3mf_path
        f_ids = None
    else:
        has_inst_paint = any(
            bool(getattr(inst, "support_paint_map", None))
            for inst in (req.instances or [])
        )
        if has_inst_paint and req.instances:
            model_input = export_instances_with_support_paint_3mf(
                cached_path,
                job_dir,
                printer,
                req.instances,
            )
            patched = patch_profiles_for_job(
                req,
                job_dir,
                is_multicolor=bool(analysis.is_multicolor),
                model_dimensions_mm=(
                    analysis.dimensions_mm.x,
                    analysis.dimensions_mm.y,
                    analysis.dimensions_mm.z,
                ),
            )
            f_ids = None
        else:
            mesh = load_and_transform_mesh(
                cached_path,
                printer=printer,
                scale_percent=req.scale_percent,
                rot_x=req.rot_x,
                rot_y=req.rot_y,
                rot_z=req.rot_z,
                scale_x=req.scale_x,
                scale_y=req.scale_y,
                scale_z=req.scale_z,
                offset_x=req.offset_x,
                offset_y=req.offset_y,
                offset_z=req.offset_z,
                drop_to_bed=req.drop_to_bed,
                instances=req.instances,
            )
            stl_for_slicer = job_dir / "input_prepared.stl"
            exported_stl = mesh.export(file_type="stl")
            stl_bytes = (
                exported_stl
                if isinstance(exported_stl, (bytes, bytearray))
                else str(exported_stl).encode("utf-8")
            )
            _atomic_write_bytes(stl_for_slicer, bytes(stl_bytes))
            patched = patch_profiles_for_job(
                req,
                job_dir,
                is_multicolor=bool(analysis.is_multicolor),
                model_dimensions_mm=(
                    analysis.dimensions_mm.x,
                    analysis.dimensions_mm.y,
                    analysis.dimensions_mm.z,
                ),
            )
            model_input = stl_for_slicer
            f_ids = None

    if req.support_blockers:
        try:
            model_input = inject_support_blockers_into_3mf(
                model_input, job_dir, printer, req.support_blockers
            )
        except Exception as exc:
            logger.warning("No se pudieron inyectar support_blockers en job %s: %s", job_id, exc)

    try:
        result = run_slicer_cli(
            printer, model_input, patched, request=req, filament_ids=f_ids
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    eff_supports_enabled = bool(req.supports)
    eff_support_type: str | None = req.support_type if req.supports else None
    eff_support_z: float | None = req.support_z_distance
    eff_support_xy: float | None = req.support_xy_distance
    try:
        proc_data = json.loads(patched.process_json.read_text(encoding="utf-8"))
        eff_supports_enabled = str(proc_data.get("enable_support", "0")) == "1"
        if eff_supports_enabled:
            eff_support_type = str(proc_data.get("support_type") or req.support_type)
            eff_support_z = round(float(proc_data.get("support_top_z_distance", 0.2)), 2)
            eff_support_xy = round(float(proc_data.get("support_object_xy_distance", 0.5)), 2)
        else:
            eff_support_type = None
            eff_support_z = None
            eff_support_xy = None
    except Exception:
        pass

    pauses_to_apply: list[dict[str, Any]] = [p.model_dump() for p in req.layer_pauses]
    if printer.profile_id == "creator5_pro" and len(analysis.detected_colors) > 4:
        slot_groups: dict[int, list[Any]] = {}
        for col in analysis.detected_colors:
            assigned = req.part_extruder_map.get(col.zone_key, col.suggested_slot)
            slot_groups.setdefault(int(assigned), []).append(col)
        eff_lh = float(req.layer_height_override or 0.20)
        existing_layers = {int(p["layer"]) for p in pauses_to_apply}
        for slot_idx, grp in slot_groups.items():
            if len(grp) < 2:
                continue
            grp_sorted = sorted(grp, key=lambda x: (x.z_min_mm, x.z_max_mm))
            for i in range(len(grp_sorted) - 1):
                prev_c = grp_sorted[i]
                next_c = grp_sorted[i + 1]
                if prev_c.z_max_mm < next_c.z_min_mm:
                    trans_z = round(float(next_c.z_min_mm), 2)
                    trans_layer = max(2, round(trans_z / max(0.08, eff_lh)))
                    if trans_layer not in existing_layers:
                        existing_layers.add(trans_layer)
                        pauses_to_apply.append(
                            {
                                "layer": trans_layer,
                                "note": f"Cambio T{slot_idx}: {prev_c.name} -> {next_c.name}",
                                "z_mm": trans_z,
                                "source": "auto_multicolor",
                                "slot": slot_idx,
                                "outgoing_color": prev_c.name,
                                "incoming_color": next_c.name,
                            }
                        )

    applied_pauses_raw: list[dict[str, Any]] = []
    if pauses_to_apply:
        try:
            _, applied_pauses_raw = apply_layer_pauses_to_file(
                result.gcode_path,
                req.printer_id,
                pauses_to_apply,
            )
        except Exception:
            applied_pauses_raw = []

    sliced_profile_snapshot: dict[str, Any] | None = None
    try:
        slicer_engine_label = getattr(result, "slicer_engine", None) or (
            "Flash Studio" if printer.profile_id == "creator5_pro" else "OrcaSlicer"
        )
        sliced_profile_snapshot = build_sliced_profile_snapshot(
            patched=patched,
            request=req,
            printer_name=printer.display_name,
            slicer_engine=str(slicer_engine_label),
            gcode_filename=result.gcode_path.name,
            applied_pauses=applied_pauses_raw,
        )
        (job_dir / "sliced_profile_snapshot.json").write_text(
            json.dumps(sliced_profile_snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        _persist_snapshot_sidecar(job_id, result.gcode_path.name)
        inject_profile_snapshot_into_gcode(result.gcode_path, sliced_profile_snapshot)
    except Exception as exc:
        logger.warning("No se pudo construir sliced_profile_snapshot para job %s: %s", job_id, exc)
        sliced_profile_snapshot = None

    if printer.profile_id == "creator5_pro":
        try:
            tool_entries: list[dict[str, Any]] = []
            if req.extruders_config:
                per_tool_g = round(result.filament_grams / max(1, len(req.extruders_config)), 2)
                per_tool_m = round(result.filament_meters / max(1, len(req.extruders_config)), 2)
                for slot in req.extruders_config:
                    tool_entries.append(
                        {
                            "tool_id": slot.extruder_index,
                            "material": slot.material.upper(),
                            "color": slot.color_hex,
                            "used_g": per_tool_g,
                            "used_m": per_tool_m,
                        }
                    )
            else:
                tool_entries.append(
                    {
                        "tool_id": req.model_extruder,
                        "material": req.material.upper(),
                        "color": "#38BDF8",
                        "used_g": result.filament_grams,
                        "used_m": result.filament_meters,
                    }
                )
            package_gcode_as_3mf(
                result.gcode_path,
                cached_path,
                job_dir / "output" / "model.gcode.3mf",
                prediction_sec=result.estimated_time_seconds,
                weight_g=result.filament_grams,
                length_m=result.filament_meters,
                nozzle_diameter=req.nozzle_diameter,
                supports_used=eff_supports_enabled,
                tool_entries=tool_entries,
            )
            primary_color = str(tool_entries[0].get("color") or "#38BDF8") if tool_entries else "#38BDF8"
            prepare_flashforge_gcode(
                result.gcode_path,
                cached_path,
                job_dir / "output" / "model.flashforge.gcode",
                primary_color=primary_color,
            )
            policy = _extract_chamber_policy_from_gcode(result.gcode_path)
            if policy is not None:
                _CHAMBER_POLICY_BY_PRINTER[req.printer_id] = policy
                _CHAMBER_POLICY_BY_PRINTER[resolve_profile_id(req.printer_id)] = policy
        except Exception:
            pass

    try:
        save_slice_project(
            project_id=job_id,
            gcode_filename=result.gcode_path.name,
            model_filename=req.model_filename or cached_path.name,
            mesh_id=resolved_id,
            printer_id=req.printer_id,
            material=req.material,
            nozzle_diameter=req.nozzle_diameter,
            quality_preset=req.quality_preset,
            ai_strategy=req.ai_strategy_label,
            transform={
                "scale_percent": req.scale_percent,
                "rot_x": req.rot_x,
                "rot_y": req.rot_y,
                "rot_z": req.rot_z,
                "offset_x": req.offset_x,
                "offset_y": req.offset_y,
                "offset_z": req.offset_z,
            },
            params={
                "nozzle_temp": req.nozzle_temp,
                "bed_temp": req.bed_temp,
                "chamber_temp_target": req.chamber_temp_target,
                "layer_height": req.layer_height_override,
                "outer_wall_speed": req.outer_wall_speed_override,
                "flow_ratio": req.flow_ratio_override,
                "infill_density": req.infill_density_override,
                "fuzzy_skin": req.fuzzy_skin,
                "fuzzy_skin_thickness": req.fuzzy_skin_thickness,
                "fuzzy_skin_point_distance": req.fuzzy_skin_point_distance,
                "supports": eff_supports_enabled,
                "support_type": eff_support_type,
                "support_on_build_plate_only": req.support_on_build_plate_only,
                "support_z_distance": eff_support_z,
                "support_xy_distance": eff_support_xy,
                "adhesion_type": req.adhesion_type,
                "brim_width_mm": req.brim_width_mm,
                "volumetric_guard": patched.volumetric_guard,
                "extruders_config": [s.model_dump() for s in req.extruders_config] if req.extruders_config else None,
                "part_extruder_map": req.part_extruder_map,
                "sliced_profile_snapshot": sliced_profile_snapshot,
            },
            metrics={
                "estimated_time": result.estimated_time,
                "estimated_time_seconds": result.estimated_time_seconds,
                "filament_grams": result.filament_grams,
                "filament_meters": result.filament_meters,
                "support_weight_g": result.support_weight_g,
                "support_percentage": result.support_percentage,
            },
        )
    except Exception:
        pass

    return SliceResponse(
        job_id=job_id,
        gcode_url=f"/api/download/{job_id}",
        estimated_time=result.estimated_time,
        estimated_time_seconds=result.estimated_time_seconds,
        filament_grams=result.filament_grams,
        filament_meters=result.filament_meters,
        support_time_seconds=result.support_time_seconds,
        support_weight_g=result.support_weight_g,
        support_percentage=result.support_percentage,
        supports_enabled=eff_supports_enabled,
        support_type=eff_support_type,
        support_z_distance=eff_support_z,
        support_xy_distance=eff_support_xy,
        mesh_warnings=analysis.warnings,
        dimensions_mm=analysis.dimensions_mm,
        applied_pauses=[LayerPauseItem(**p) for p in applied_pauses_raw],
        sliced_profile_snapshot=sliced_profile_snapshot,
    )


@app.post("/api/slicer/apply-pauses", response_model=ApplyPausesResponse)
def apply_pauses_endpoint(req: ApplyPausesRequest) -> ApplyPausesResponse:
    """Inyecta o actualiza pausas por capa sobre un `.gcode` ya laminado (< 50 ms)."""
    out_dir = TEMP_DIR / req.job_id / "output"
    if not out_dir.exists():
        raise HTTPException(status_code=404, detail="Trabajo de laminado no encontrado.")

    gcode_candidates = [
        p
        for p in sorted(out_dir.glob("*.gcode"))
        if p.name != "model.flashforge.gcode"
    ]
    if not gcode_candidates:
        raise HTTPException(status_code=404, detail="Archivo .gcode no encontrado.")

    gcode_path = gcode_candidates[0]
    updated_text, applied_raw = apply_layer_pauses_to_file(
        gcode_path,
        req.printer_id,
        [p.model_dump() for p in req.pauses],
    )

    ff_gcode = out_dir / "model.flashforge.gcode"
    if ff_gcode.exists():
        try:
            apply_layer_pauses_to_file(
                ff_gcode,
                req.printer_id,
                [p.model_dump() for p in req.pauses],
            )
        except Exception:
            pass

    return ApplyPausesResponse(
        job_id=req.job_id,
        applied_pauses=[LayerPauseItem(**p) for p in applied_raw],
        gcode_text=updated_text,
    )


@app.post("/api/slice", response_model=SliceResponse)
async def slice_endpoint(
    printer_id: PrinterId = Form(...),
    material: MaterialType = Form(...),
    nozzle_temp: int = Form(...),
    nozzle_temp_initial_layer: int | None = Form(None),
    bed_temp: int = Form(...),
    nozzle_diameter: float = Form(0.4),
    high_speed_filament: bool = Form(False),
    lithophane_mode: bool = Form(False),
    supports: bool = Form(False),
    support_type: SupportType = Form("tree(auto)"),
    support_style: str = Form("default"),
    support_on_build_plate_only: bool = Form(True),
    support_z_distance: float | None = Form(None),
    support_xy_distance: float | None = Form(None),
    adhesion_type: AdhesionType = Form("none"),
    brim_width_mm: float = Form(6.0),
    chamber_temp_target: int | None = Form(None),
    layer_height_override: float | None = Form(None),
    outer_wall_speed_override: int | None = Form(None),
    flow_ratio_override: float | None = Form(None),
    infill_density_override: int | None = Form(None),
    fuzzy_skin: bool = Form(False),
    fuzzy_skin_thickness: float = Form(0.25),
    fuzzy_skin_point_distance: float = Form(0.4),
    ai_strategy_label: str | None = Form(None),
    model_filename: str | None = Form(None),
    prime_tower_mode: str = Form("auto"),
    enable_prime_tower: bool | None = Form(None),
    enable_timelapse: bool = Form(False),
    auto_leveling: bool = Form(False),
    quality_preset: QualityPreset = Form("estandar"),
    mesh_id: str | None = Form(None),
    scale_percent: float = Form(100.0),
    scale_x: float | None = Form(None),
    scale_y: float | None = Form(None),
    scale_z: float | None = Form(None),
    rot_x: float = Form(0.0),
    rot_y: float = Form(0.0),
    rot_z: float = Form(0.0),
    offset_x: float = Form(0.0),
    offset_y: float = Form(0.0),
    offset_z: float = Form(0.0),
    drop_to_bed: bool = Form(True),
    instances_json: str | None = Form(None),
    extruders_config_json: str | None = Form(None),
    model_extruder: int = Form(0),
    support_extruder: int = Form(0),
    z_color_ranges_json: str | None = Form(None),
    part_extruder_map_json: str | None = Form(None),
    layer_pauses_json: str | None = Form(None),
    scene_objects_json: str | None = Form(None),
    quality_overrides_json: str | None = Form(None),
    profile_overrides_json: str | None = Form(None),
    support_blockers_json: str | None = Form(None),
    file: UploadFile | None = File(None),
) -> SliceResponse:
    """Lamina `.stl` o `.3mf` multicolor usando caché `mesh_id`, bloqueo por malla y escritura atómica."""
    parsed_extruders: list[ExtruderSlotConfig] | None = None
    if extruders_config_json:
        try:
            raw_slots = json.loads(extruders_config_json)
            parsed_extruders = [ExtruderSlotConfig(**item) for item in raw_slots]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"extruders_config_json inválido: {exc}"
            ) from exc

    parsed_z_ranges: list[ZColorRange] = []
    if z_color_ranges_json:
        try:
            raw_ranges = json.loads(z_color_ranges_json)
            parsed_z_ranges = [ZColorRange(**item) for item in raw_ranges]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"z_color_ranges_json inválido: {exc}"
            ) from exc

    parsed_part_map: dict[str, int] = {}
    if part_extruder_map_json:
        try:
            raw_map = json.loads(part_extruder_map_json)
            if isinstance(raw_map, dict):
                parsed_part_map = {str(k): int(v) for k, v in raw_map.items()}
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"part_extruder_map_json inválido: {exc}"
            ) from exc

    parsed_layer_pauses: list[LayerPauseItem] = []
    if layer_pauses_json:
        try:
            raw_pauses = json.loads(layer_pauses_json)
            if isinstance(raw_pauses, list):
                parsed_layer_pauses = [LayerPauseItem(**item) for item in raw_pauses]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"layer_pauses_json inválido: {exc}"
            ) from exc

    parsed_scene_objects: list[SceneObjectTransform] = []
    if scene_objects_json:
        try:
            raw_objs = json.loads(scene_objects_json)
            if isinstance(raw_objs, list):
                parsed_scene_objects = [SceneObjectTransform(**item) for item in raw_objs]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"scene_objects_json inválido: {exc}"
            ) from exc

    parsed_quality_overrides: list[str] = []
    if quality_overrides_json:
        try:
            raw_qo = json.loads(quality_overrides_json)
            if isinstance(raw_qo, list):
                parsed_quality_overrides = [str(x).strip() for x in raw_qo if str(x).strip()]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"quality_overrides_json inválido: {exc}"
            ) from exc

    parsed_profile_overrides: dict[str, Any] = {}
    if profile_overrides_json:
        try:
            raw_po = json.loads(profile_overrides_json)
            if isinstance(raw_po, dict):
                parsed_profile_overrides = raw_po
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"profile_overrides_json inválido: {exc}"
            ) from exc

    parsed_support_blockers: list[Any] = []
    if support_blockers_json:
        try:
            from app.models.schemas import SupportBlockerItem

            raw_sb = json.loads(support_blockers_json)
            if isinstance(raw_sb, list):
                parsed_support_blockers = [SupportBlockerItem(**item) for item in raw_sb if isinstance(item, dict)]
        except Exception as exc:
            raise HTTPException(
                status_code=400, detail=f"support_blockers_json inválido: {exc}"
            ) from exc

    parsed_instances = _parse_instances_json(instances_json)
    clean_rx, clean_ry, clean_rz = sanitize_euler_rotation(rot_x, rot_y, rot_z)
    eff_material: MaterialType = "pla" if lithophane_mode else material
    eff_supports = False if lithophane_mode else supports
    eff_adhesion: AdhesionType = "brim" if lithophane_mode else adhesion_type
    eff_brim_w = max(8.0, min(10.0, brim_width_mm)) if lithophane_mode else brim_width_mm

    try:
        req = SliceRequest(
            printer_id=printer_id,
            material=eff_material,
            nozzle_temp=nozzle_temp,
            nozzle_temp_initial_layer=nozzle_temp_initial_layer,
            bed_temp=bed_temp,
            nozzle_diameter=nozzle_diameter,
            high_speed_filament=high_speed_filament,
            lithophane_mode=lithophane_mode,
            supports=eff_supports,
            layer_pauses=parsed_layer_pauses,
            scene_objects=parsed_scene_objects,
            support_type=support_type,
            support_style=support_style,
            support_on_build_plate_only=support_on_build_plate_only,
            support_z_distance=support_z_distance,
            support_xy_distance=support_xy_distance,
            adhesion_type=eff_adhesion,
            brim_width_mm=eff_brim_w,
            chamber_temp_target=chamber_temp_target,
            layer_height_override=layer_height_override,
            outer_wall_speed_override=outer_wall_speed_override,
            flow_ratio_override=flow_ratio_override,
            infill_density_override=infill_density_override,
            fuzzy_skin=fuzzy_skin,
            fuzzy_skin_thickness=fuzzy_skin_thickness,
            fuzzy_skin_point_distance=fuzzy_skin_point_distance,
            ai_strategy_label=ai_strategy_label,
            model_filename=model_filename,
            prime_tower_mode=prime_tower_mode if prime_tower_mode in ("auto", "off", "ultra_save") else "auto",  # type: ignore[arg-type]
            enable_prime_tower=enable_prime_tower,
            enable_timelapse=enable_timelapse,
            auto_leveling=auto_leveling,
            quality_preset=quality_preset,
            mesh_id=mesh_id,
            scale_percent=scale_percent,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
            rot_x=clean_rx,
            rot_y=clean_ry,
            rot_z=clean_rz,
            offset_x=offset_x,
            offset_y=offset_y,
            offset_z=offset_z,
            drop_to_bed=drop_to_bed,
            instances=parsed_instances,
            extruders_config=parsed_extruders,
            model_extruder=model_extruder,
            support_extruder=support_extruder,
            z_color_ranges=parsed_z_ranges,
            part_extruder_map=parsed_part_map,
            quality_overrides=parsed_quality_overrides,
            profile_overrides=parsed_profile_overrides,
            support_blockers=parsed_support_blockers,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=f"Parámetros de laminado inválidos: {exc}") from exc

    printer = _resolve_printer_or_400(req.printer_id)
    resolved_id, cached_path = _resolve_cached_stl(file, req.mesh_id)
    async with _get_mesh_slice_lock(resolved_id):
        return await asyncio.to_thread(_execute_slice_job_sync, req, printer, cached_path, resolved_id)


def _sanitize_gcode_filename(raw_name: str | None, fallback_job_id: str) -> str:
    base = Path(str(raw_name or "")).name.strip()
    if base.lower().endswith(".gcode"):
        base = base[:-6]
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-")
    if not base:
        base = f"slicerhub_{fallback_job_id}"
    return f"{base}.gcode"


@app.get("/api/download/{job_id}")
def download_gcode(
    job_id: str,
    filename: str | None = None,
    format: str = "gcode",
) -> FileResponse:
    """Descarga el archivo `.gcode` o `.gcode.3mf` generado para un `job_id` con nombre personalizado."""
    if not job_id.isalnum():
        raise HTTPException(status_code=400, detail="job_id inválido.")
    out_dir = TEMP_DIR / job_id / "output"
    gcodes = sorted(out_dir.glob("*.gcode")) if out_dir.exists() else []
    if not gcodes:
        raise HTTPException(status_code=404, detail="G-code no encontrado para este job_id.")
    safe_name = _sanitize_gcode_filename(filename, job_id)
    _persist_snapshot_sidecar(job_id, safe_name)
    if format.lower() == "flashforge":
        ff_gcode = out_dir / "model.flashforge.gcode"
        if not ff_gcode.is_file():
            prepare_flashforge_gcode(gcodes[0], None, ff_gcode)
        return FileResponse(
            path=ff_gcode,
            media_type="application/octet-stream",
            filename=safe_name,
        )
    if format.lower() == "3mf":
        ff_3mf = out_dir / "model.gcode.3mf"
        if not ff_3mf.is_file():
            package_gcode_as_3mf(gcodes[0], None, ff_3mf)
        safe_3mf_name = (
            safe_name
            if safe_name.lower().endswith(".gcode.3mf")
            else f"{Path(safe_name).stem}.gcode.3mf"
        )
        return FileResponse(
            path=ff_3mf,
            media_type="application/octet-stream",
            filename=safe_3mf_name,
        )
    return FileResponse(
        path=gcodes[0],
        media_type="application/octet-stream",
        filename=safe_name,
    )


_CHAMBER_POLICY_BY_PRINTER: dict[str, tuple[float, str]] = {}


def _extract_chamber_policy_from_gcode(gcode_path: Path) -> tuple[float, str] | None:
    try:
        with gcode_path.open("r", encoding="utf-8", errors="ignore") as fh:
            head = [fh.readline() for _ in range(1500)]
    except OSError:
        return None
    target: float | None = None
    mode: str | None = None
    for ln in head:
        if ln.startswith("; SLICERHUB_CHAMBER_TARGET ="):
            try:
                target = float(ln.split("=", 1)[1].strip())
            except ValueError:
                pass
        elif ln.startswith("; SLICERHUB_CHAMBER_MODE ="):
            mode = ln.split("=", 1)[1].strip()
    if target is not None and mode:
        return (target, mode)
    return None


def _build_printers_config_response() -> PrintersConfigResponse:
    raw = load_printers_config()
    serial_ports, volumes = detect_macos_serial_and_volumes()
    keys_meta = get_masked_ai_keys()
    entries: dict[PrinterId, PrinterNetworkEntry] = {
        pid: PrinterNetworkEntry(**cfg)  # type: ignore[misc]
        for pid, cfg in raw.items()
    }
    return PrintersConfigResponse(
        printers=entries,
        detected_serial_ports=serial_ports,
        detected_volumes=volumes,
        **keys_meta,
    )


@app.get("/api/printers/catalog")
def get_printers_catalog_endpoint(
    q: str = "",
    vendor: str = "",
    multicolor_only: bool = False,
    limit: int = 120,
) -> dict[str, Any]:
    """Busca en el Catálogo Universal de Impresoras OrcaSlicer por marca, modelo o multicolor."""
    return search_orca_catalog(q=q, vendor=vendor, multicolor_only=multicolor_only, limit=limit)


@app.post("/api/printers/catalog/sync")
def sync_printers_catalog_endpoint() -> dict[str, Any]:
    """Sincroniza el catálogo de impresoras desde el repositorio oficial OrcaSlicer/OrcaSlicer."""
    return sync_orca_catalog_from_github()


@app.post("/api/printers/add")
def add_printer_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    """Registra una impresora del catálogo OrcaSlicer en `user_printers.json`."""
    catalog_id = str(payload.get("catalog_id") or "").strip()
    if not catalog_id:
        raise HTTPException(status_code=400, detail="catalog_id es requerido.")
    try:
        record = add_user_printer_from_catalog(
            catalog_id=catalog_id,
            display_name=payload.get("display_name"),
            nozzle_diameter=float(payload.get("nozzle_diameter") or 0.4),
            connection_mode=str(payload.get("connection_mode") or "lan"),
            ip=str(payload.get("ip") or ""),
            port=int(payload["port"]) if payload.get("port") else None,
            protocol=payload.get("protocol"),
            is_multicolor=payload.get("is_multicolor"),
            tool_count=int(payload["tool_count"]) if payload.get("tool_count") else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "printer": record}


@app.patch("/api/printers/{printer_id}")
def patch_printer_endpoint(printer_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Edita IP, boquilla, capacidades o nombre de una impresora del usuario."""
    try:
        record = update_user_printer(printer_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "printer": record}


@app.delete("/api/printers/{printer_id}")
def delete_printer_endpoint(printer_id: str) -> dict[str, Any]:
    """Elimina una impresora personalizada o instancia del usuario."""
    try:
        removed = delete_user_printer(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "deleted": removed}


@app.get("/api/printers/config", response_model=PrintersConfigResponse)
def get_printers_config_endpoint() -> PrintersConfigResponse:
    """Retorna configuración de red/USB/SD, autodetección macOS y estado enmascarado de claves IA."""
    return _build_printers_config_response()


@app.put("/api/printers/config", response_model=PrintersConfigResponse)
def update_printers_config_endpoint(payload: PrintersConfigPayload) -> PrintersConfigResponse:
    """Guarda IPs/puertos/`access_code`/serial/SD y claves opcionales de Gemini/DeepSeek."""
    serialized = {pid: entry.model_dump() for pid, entry in payload.printers.items()}
    save_printers_config(serialized)
    if payload.gemini_api_key or payload.deepseek_api_key:
        save_ai_keys_to_env(
            gemini_api_key=payload.gemini_api_key,
            deepseek_api_key=payload.deepseek_api_key,
        )
    return _build_printers_config_response()


async def _query_single_printer(
    pid: str,
    cfg: dict[str, Any],
    timeout: float = 1.5,
) -> PrinterLiveStatus:
    profile_id = str(cfg.get("profile_id") or "")
    base = PRINTER_REGISTRY.get(profile_id)
    display_name = str(cfg.get("name") or "").strip() or (
        base.display_name if base else pid
    )
    protocol = str(cfg.get("protocol", ""))
    if protocol == "moonraker":
        return await query_moonraker_status(pid, display_name, cfg, timeout=timeout)
    if protocol == "flashforge_lan":
        st = await query_flashforge_status(pid, display_name, cfg, timeout=timeout)
        policy = _CHAMBER_POLICY_BY_PRINTER.get(pid) or _CHAMBER_POLICY_BY_PRINTER.get(profile_id)
        if policy is not None:
            st.chamber_target, st.chamber_mode = policy
        elif st.chamber_temp is not None:
            fname = (st.current_file or "").upper()
            if "ABS" in fname or "ASA" in fname or (st.bed_target or 0) >= 95:
                st.chamber_target, st.chamber_mode = 50.0, "preheat_closed"
            elif "PETG" in fname or (st.nozzle_target or 0) >= 232 or (st.bed_target or 0) >= 70:
                st.chamber_target, st.chamber_mode = 40.0, "recirculation"
            else:
                st.chamber_target, st.chamber_mode = 30.0, "extraction"
        return st
    return await asyncio.to_thread(marlin_manager.query_status, pid, display_name, cfg)


@app.get("/api/printers/status", response_model=list[PrinterLiveStatus])
async def get_printers_status_endpoint() -> list[PrinterLiveStatus]:
    """Consulta en paralelo la telemetría y cámara en vivo de todas las máquinas habilitadas."""
    configs = load_printers_config()
    tasks = [
        _query_single_printer(pid, cfg, timeout=2.2)
        for pid, cfg in configs.items()
        if cfg.get("enabled", True)
    ]
    results = list(await asyncio.gather(*tasks))
    for st in results:
        telemetry_recorder.ingest_status(st)
        local_timelapse_recorder.ingest_status(st, st.camera_url)
    return results


@app.post("/api/printers/test", response_model=PrinterLiveStatus)
async def test_printer_connection_endpoint(entry: PrinterNetworkEntry) -> PrinterLiveStatus:
    """Prueba de conectividad individual bajo demanda desde el modal de configuración."""
    cfg = entry.model_dump()
    pid = str(cfg.get("id") or cfg.get("profile_id") or "test_printer").strip()
    return await _query_single_printer(pid, cfg, timeout=2.2)


def _detect_local_subnet_prefix() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.40.1", 80))
            local_ip = s.getsockname()[0]
            if local_ip and not local_ip.startswith("127."):
                return ".".join(local_ip.split(".")[:3])
    except OSError:
        pass
    return "192.168.40"


@app.post("/api/printers/discover")
async def discover_printers_endpoint() -> dict[str, Any]:
    """Escanea la subred local `/24` para auto-descubrir impresoras Moonraker y FlashForge LAN."""
    prefix = _detect_local_subnet_prefix()
    sem = asyncio.Semaphore(128)

    async def _tcp_open(ip: str, port: int) -> bool:
        async with sem:
            try:
                _r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=0.45)
                w.close()
                await w.wait_closed()
                return True
            except Exception:
                return False

    async def _probe_host(ip: str) -> dict[str, Any] | None:
        has_80, has_7125, has_8898, has_8899 = await asyncio.gather(
            _tcp_open(ip, 80),
            _tcp_open(ip, 7125),
            _tcp_open(ip, 8898),
            _tcp_open(ip, 8899),
        )
        if not (has_80 or has_7125 or has_8898 or has_8899):
            return None

        async with httpx.AsyncClient(timeout=1.2, trust_env=False) as client:
            if has_8898 or has_8899:
                try:
                    r = await client.post(
                        f"http://{ip}:8898/detail",
                        json={"serialNumber": "", "checkCode": ""},
                    )
                    if r.status_code == 200 and ("code" in r.text or "detail" in r.text):
                        return {
                            "ip": ip,
                            "port": 8898 if has_8898 else 8899,
                            "protocol": "flashforge_lan",
                            "suggested_profile": "creator5_pro",
                            "hostname": "FlashForge Creator 5 Pro",
                            "camera_url": f"http://{ip}:8080/?action=stream",
                        }
                except Exception:
                    pass
                if has_8899:
                    return {
                        "ip": ip,
                        "port": 8899,
                        "protocol": "flashforge_lan",
                        "suggested_profile": "creator5_pro",
                        "hostname": "FlashForge LAN (TCP 8899)",
                        "camera_url": f"http://{ip}:8080/?action=stream",
                    }

            for m_port in ([80] if has_80 else []) + ([7125] if has_7125 else []):
                base = f"http://{ip}" if m_port == 80 else f"http://{ip}:{m_port}"
                try:
                    r = await client.get(f"{base}/printer/info")
                    if r.status_code == 200:
                        info = r.json().get("result", {})
                        if isinstance(info, dict) and ("state" in info or "hostname" in info):
                            host = str(info.get("hostname") or "Klipper")
                            low = host.lower()
                            prof = (
                                "flsun_t1_pro"
                                if "t1" in low
                                else "flsun_v400"
                                if "v400" in low
                                else "flsun_sr"
                                if "sr" in low
                                else "flsun_t1_pro"
                            )
                            return {
                                "ip": ip,
                                "port": m_port,
                                "protocol": "moonraker",
                                "suggested_profile": prof,
                                "hostname": host,
                                "camera_url": f"http://{ip}/webcam/?action=stream",
                            }
                except Exception:
                    pass
        return None

    results = await asyncio.gather(*[_probe_host(f"{prefix}.{i}") for i in range(1, 255)])
    discovered = [r for r in results if r is not None]
    return {"subnet": f"{prefix}.0/24", "discovered": discovered}


async def _dispatch_job_to_printer(
    job_id: str,
    printer_id: PrinterId,
    mode: str,
    sd_volume_path: str | None,
    start_immediately: bool,
    enable_timelapse: bool,
    auto_leveling: bool = False,
    custom_filename: str | None = None,
) -> SendPrintResponse:
    """Despacha un G-code laminado exclusivamente a la instancia `printer_id` seleccionada."""
    if not job_id.isalnum():
        raise HTTPException(status_code=400, detail="job_id inválido.")
    out_dir = TEMP_DIR / job_id / "output"
    gcodes = sorted(out_dir.glob("*.gcode")) if out_dir.exists() else []
    if not gcodes:
        raise HTTPException(status_code=404, detail="G-code no encontrado para este job_id.")

    gcode_path = gcodes[0]
    filename = _sanitize_gcode_filename(custom_filename, job_id)
    _persist_snapshot_sidecar(
        job_id,
        filename,
        extra_dir=Path(sd_volume_path) if mode == "sd_volume" and sd_volume_path else None,
    )
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    protocol = str(cfg.get("protocol", ""))

    try:
        if protocol == "moonraker":
            msg = await upload_and_start_moonraker(
                cfg, gcode_path, filename, start_immediately=start_immediately
            )
            return SendPrintResponse(
                status="printing" if start_immediately else "uploaded",
                printer_id=resolved_pid,
                mode="network",
                destination=f"{cfg.get('ip')}:{cfg.get('port')}",
                message=msg,
            )

        if protocol == "flashforge_lan":
            ff_gcode_path = out_dir / "model.flashforge.gcode"
            if not ff_gcode_path.is_file():
                prepare_flashforge_gcode(gcode_path, None, ff_gcode_path)
            policy = _extract_chamber_policy_from_gcode(ff_gcode_path)
            if policy is not None:
                _CHAMBER_POLICY_BY_PRINTER[resolved_pid] = policy

            clean_stem = filename
            lower_name = clean_stem.lower()
            if lower_name.endswith(".gcode.3mf"):
                clean_stem = clean_stem[:-10]
            elif lower_name.endswith(".gcode"):
                clean_stem = clean_stem[:-6]
            elif lower_name.endswith(".3mf"):
                clean_stem = clean_stem[:-4]
            clean_stem = clean_stem.strip(" ._-") or f"nikk_{job_id[:8]}"
            ff_filename = f"{clean_stem}.3mf"
            ff_upload_path = out_dir / ff_filename

            await asyncio.to_thread(
                export_flashforge_gcode_3mf,
                ff_gcode_path,
                ff_upload_path,
                object_name=clean_stem,
                timelapse_type=1 if enable_timelapse else 0,
            )
            msg = await upload_and_start_flashforge(
                cfg,
                ff_upload_path,
                ff_filename,
                start_immediately=start_immediately,
                enable_timelapse=enable_timelapse,
                auto_leveling=auto_leveling,
            )
            if start_immediately:
                local_timelapse_recorder.arm_printer(resolved_pid, bool(enable_timelapse))
            return SendPrintResponse(
                status="printing" if start_immediately else "uploaded",
                printer_id=resolved_pid,
                mode="network",
                destination=str(cfg.get("ip", "")),
                message=msg,
            )

        # Impresoras Marlin USB Serial o Tarjeta SD `/Volumes/`
        if mode == "sd_volume":
            sd_dir = (sd_volume_path or cfg.get("sd_volume_path") or "").strip()
            saved = await asyncio.to_thread(marlin_manager.save_to_sd, gcode_path, sd_dir, filename)
            return SendPrintResponse(
                status="saved",
                printer_id=resolved_pid,
                mode="sd_volume",
                destination=str(saved),
                message=f"Archivo guardado en tarjeta SD: {saved}",
            )

        msg = await asyncio.to_thread(marlin_manager.start_print, cfg, gcode_path, filename)
        return SendPrintResponse(
            status="printing",
            printer_id=resolved_pid,
            mode="usb_serial",
            destination=str(cfg.get("serial_port", "")),
            message=msg,
        )
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.post("/api/print/{job_id}", response_model=SendPrintResponse)
async def send_print_endpoint(job_id: str, req: SendPrintRequest) -> SendPrintResponse:
    """Envía un G-code generado hacia la impresora seleccionada (imprimir o solo subir)."""
    effective_start = req.start_print if req.start_print is not None else req.start_immediately
    return await _dispatch_job_to_printer(
        job_id=job_id,
        printer_id=req.printer_id,
        mode=req.mode,
        sd_volume_path=req.sd_volume_path,
        start_immediately=effective_start,
        enable_timelapse=req.enable_timelapse,
        auto_leveling=req.auto_leveling,
        custom_filename=req.custom_filename,
    )


@app.post("/api/printers/{printer_id}/upload", response_model=SendPrintResponse)
async def upload_to_printer_endpoint(
    printer_id: PrinterId,
    req: UploadToPrinterRequest,
) -> SendPrintResponse:
    """Sube un trabajo laminado a `printer_id` (`start_print=false` solo memoria, `true` imprime)."""
    return await _dispatch_job_to_printer(
        job_id=req.job_id,
        printer_id=printer_id,
        mode=req.mode,
        sd_volume_path=req.sd_volume_path,
        start_immediately=req.start_print,
        enable_timelapse=req.enable_timelapse,
        auto_leveling=req.auto_leveling,
        custom_filename=req.custom_filename,
    )


async def _dispatch_printer_control(printer_id: PrinterId, action: str) -> dict[str, Any]:
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    protocol = str(cfg.get("protocol", ""))
    try:
        if protocol == "moonraker":
            msg = await control_moonraker(cfg, action)
        elif protocol == "flashforge_lan":
            msg = await control_flashforge(cfg, action)
        else:
            if action in ("light_on", "light_off", "light_toggle"):
                raise HTTPException(
                    status_code=400,
                    detail="Control de luz LED no soportado por conexión USB Marlin.",
                )
            msg = await asyncio.to_thread(marlin_manager.control, action)
        return {"status": "ok", "printer_id": resolved_pid, "message": msg}
    except HTTPException:
        raise
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.post("/api/printers/{printer_id}/control")
@app.post("/api/printers/{printer_id}/command")
async def control_printer_endpoint(
    printer_id: PrinterId,
    req: PrinterControlRequest,
) -> dict[str, Any]:
    """Ejecuta `pause`, `resume`, `cancel` o luz LED exclusivamente sobre `printer_id`."""
    return await _dispatch_printer_control(printer_id, req.action)


@app.post("/api/printers/{printer_id}/light")
async def toggle_printer_light_endpoint(
    printer_id: PrinterId,
    req: PrinterLightRequest | None = None,
) -> dict[str, Any]:
    """Enciende, apaga o conmuta la luz LED exclusivamente de `printer_id`."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    target = req.on if req is not None else None
    protocol = str(cfg.get("protocol", ""))
    try:
        if protocol == "moonraker":
            light_on, msg = await set_moonraker_light(cfg, target_on=target)
        elif protocol == "flashforge_lan":
            light_on, msg = await set_flashforge_light(cfg, target_on=target)
        else:
            raise HTTPException(
                status_code=400,
                detail="Control de luz LED disponible solo para impresoras de red.",
            )
        return {
            "status": "ok",
            "printer_id": resolved_pid,
            "light_on": light_on,
            "message": msg,
        }
    except HTTPException:
        raise
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.get("/api/printers/{printer_id}/files", response_model=PrinterFilesResponse)
async def list_printer_files_endpoint(printer_id: PrinterId) -> PrinterFilesResponse:
    """Lista archivos guardados en la memoria interna de `printer_id`."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    protocol = str(cfg.get("protocol", ""))
    try:
        if protocol == "moonraker":
            files = await list_moonraker_files(cfg)
        elif protocol == "flashforge_lan":
            files = await list_flashforge_files(cfg)
        else:
            files = []
        return PrinterFilesResponse(printer_id=resolved_pid, files=files)
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.post("/api/printers/{printer_id}/files/print")
async def print_stored_file_endpoint(
    printer_id: PrinterId,
    req: PrinterFileActionRequest,
) -> dict[str, str]:
    """Inicia la impresión de un archivo guardado en memoria de `printer_id`."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    protocol = str(cfg.get("protocol", ""))
    try:
        if protocol == "moonraker":
            msg = await print_moonraker_file(
                cfg, req.filename, enable_timelapse=req.enable_timelapse
            )
        elif protocol == "flashforge_lan":
            msg = await print_flashforge_file(
                cfg,
                req.filename,
                enable_timelapse=req.enable_timelapse,
                auto_leveling=req.auto_leveling,
            )
            local_timelapse_recorder.arm_printer(resolved_pid, bool(req.enable_timelapse))
        else:
            raise HTTPException(
                status_code=400,
                detail="Impresión remota de memoria no soportada en USB Marlin.",
            )
        return {"status": "ok", "printer_id": resolved_pid, "message": msg}
    except HTTPException:
        raise
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.delete("/api/printers/{printer_id}/files")
async def delete_stored_file_endpoint(
    printer_id: PrinterId,
    filename: str,
) -> dict[str, str]:
    """Elimina un archivo de la memoria interna de `printer_id`."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    protocol = str(cfg.get("protocol", ""))
    try:
        if protocol == "moonraker":
            msg = await delete_moonraker_file(cfg, filename)
        elif protocol == "flashforge_lan":
            msg = await delete_flashforge_file(cfg, filename)
        else:
            raise HTTPException(
                status_code=400,
                detail="Borrado remoto no soportado en USB Marlin.",
            )
        return {"status": "ok", "printer_id": resolved_pid, "message": msg}
    except HTTPException:
        raise
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.delete("/api/printers/{printer_id}/files/all")
async def delete_all_stored_files_endpoint(printer_id: PrinterId) -> dict[str, Any]:
    """Elimina todos los archivos G-code/3MF de la memoria interna de `printer_id`."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    protocol = str(cfg.get("protocol", ""))
    if protocol not in ("moonraker", "flashforge_lan"):
        raise HTTPException(
            status_code=400,
            detail="Borrado remoto masivo no soportado en USB Marlin.",
        )

    try:
        files = (
            await list_moonraker_files(cfg)
            if protocol == "moonraker"
            else await list_flashforge_files(cfg)
        )
        if not files:
            return {
                "status": "ok",
                "printer_id": resolved_pid,
                "deleted_count": 0,
                "failed_count": 0,
                "message": "No había archivos en memoria para eliminar.",
            }

        delete_fn = delete_moonraker_file if protocol == "moonraker" else delete_flashforge_file
        deleted_count = 0
        failed_count = 0
        last_error = ""
        for entry in files:
            try:
                await delete_fn(cfg, entry.filename)
                deleted_count += 1
            except Exception as exc:
                failed_count += 1
                last_error = str(exc) or type(exc).__name__

        if deleted_count == 0 and failed_count > 0:
            raise HTTPException(
                status_code=500,
                detail=f"No se pudo eliminar ningún archivo ({failed_count} error(es)): {last_error}",
            )

        summary = f"Se eliminaron {deleted_count} archivo(s) de la memoria."
        if failed_count > 0:
            summary += f" ({failed_count} omitido(s): {last_error})"

        return {
            "status": "ok",
            "printer_id": resolved_pid,
            "deleted_count": deleted_count,
            "failed_count": failed_count,
            "message": summary,
        }
    except HTTPException:
        raise
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.get("/api/printers/{printer_id}/files/download")
async def download_stored_file_endpoint(
    printer_id: PrinterId,
    filename: str,
) -> Response:
    """Descarga un archivo G-code de la memoria interna de `printer_id` (Moonraker)."""
    try:
        _, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    protocol = str(cfg.get("protocol", ""))
    if protocol != "moonraker":
        raise HTTPException(
            status_code=400,
            detail="La descarga remota de archivos solo está soportada en impresoras Klipper/Moonraker (T1 Pro / V400).",
        )

    try:
        content, download_name = await download_moonraker_file(cfg, filename)
        safe_name = download_name.replace('"', "")
        return Response(
            content=content,
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )
    except HTTPException:
        raise
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.get("/api/printers/{printer_id}/files/thumb")
async def get_stored_file_thumb_endpoint(
    printer_id: PrinterId,
    filename: str,
) -> Response:
    """Devuelve la miniatura PNG de un archivo en memoria de `printer_id`."""
    try:
        _, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    protocol = str(cfg.get("protocol", ""))
    if protocol == "flashforge_lan":
        png_bytes = await get_flashforge_file_thumbnail(cfg, filename)
    elif protocol == "moonraker":
        png_bytes = await get_moonraker_file_thumbnail(cfg, filename)
    else:
        raise HTTPException(status_code=404, detail="Miniatura no disponible para este protocolo.")

    if not png_bytes:
        raise HTTPException(status_code=404, detail="Miniatura no encontrada.")
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/api/printers/{printer_id}/timelapses", response_model=PrinterTimelapsesResponse)
async def list_printer_timelapses_endpoint(
    printer_id: PrinterId,
) -> PrinterTimelapsesResponse:
    """Lista videos timelapse `.mp4` generados en `printer_id`."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    protocol = str(cfg.get("protocol", ""))
    try:
        if protocol == "moonraker":
            videos, msg = await list_moonraker_timelapses(cfg)
            return PrinterTimelapsesResponse(
                printer_id=resolved_pid, timelapses=videos, message=msg
            )
        if protocol == "flashforge_lan":
            return PrinterTimelapsesResponse(
                printer_id=resolved_pid,
                timelapses=[],
                message=(
                    "Creator 5 Pro graba el timelapse en su almacenamiento interno cuando "
                    "'Grabar Timelapse' está activo (descarga desde pantalla/nube FlashForge)."
                ),
            )
        return PrinterTimelapsesResponse(
            printer_id=resolved_pid,
            timelapses=[],
            message="Timelapses no disponibles en conexión USB/SD.",
        )
    except Exception as exc:
        err_detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
        raise HTTPException(status_code=500, detail=err_detail) from exc


@app.post("/api/printers/{printer_id}/ai-telemetry", response_model=AITelemetryDiagnosisResponse)
async def diagnose_printer_telemetry_endpoint(
    printer_id: PrinterId,
) -> AITelemetryDiagnosisResponse:
    """Consulta telemetría en vivo exclusiva de `printer_id` y la diagnostica con DeepSeek IA."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    live_status = await _query_single_printer(resolved_pid, cfg, timeout=2.5)
    telemetry_recorder.ingest_status(live_status)
    local_timelapse_recorder.ingest_status(live_status, live_status.camera_url)
    return await asyncio.to_thread(diagnose_live_telemetry, live_status)


@app.post("/api/export/{job_id}/flashforge-3mf")
async def export_flashforge_3mf_endpoint(
    job_id: str,
    object_name: str | None = Query(default=None),
) -> FileResponse:
    """Exporta un `.gcode.3mf` fiel a Orca-Flashforge usando el módulo independiente."""
    if not job_id.isalnum():
        raise HTTPException(status_code=400, detail="job_id inválido.")
    out_dir = TEMP_DIR / job_id / "output"
    gcodes = sorted(out_dir.glob("*.gcode")) if out_dir.exists() else []
    if not gcodes:
        raise HTTPException(status_code=404, detail="G-code no encontrado para este job_id.")
    src_gcode = out_dir / "model.flashforge.gcode"
    if not src_gcode.is_file():
        src_gcode = gcodes[0]
    mesh_cand = next((TEMP_DIR / job_id).glob("input.*"), None)
    out_3mf = out_dir / f"{(object_name or job_id)}.gcode.3mf"
    await asyncio.to_thread(
        export_flashforge_gcode_3mf,
        src_gcode,
        out_3mf,
        mesh_path=mesh_cand,
        object_name=object_name or job_id,
    )
    return FileResponse(
        path=str(out_3mf),
        media_type="application/vnd.ms-package.3dmanufacturing-3dmodel+xml",
        filename=out_3mf.name,
    )


@app.get("/api/timelapses")
async def list_local_timelapses_endpoint(
    printer_id: str | None = Query(default=None),
) -> dict[str, Any]:
    """Lista sesiones activas y completadas de timelapse local por impresora."""
    return local_timelapse_recorder.list_timelapses(printer_id)


@app.post("/api/timelapses/arm/{printer_id}")
async def arm_local_timelapse_endpoint(
    printer_id: PrinterId,
    armed: bool = Query(default=True),
) -> dict[str, Any]:
    """Activa o desactiva la captura local de timelapse en este PC para una impresora."""
    try:
        resolved_pid, _cfg = get_printer_instance(printer_id)
    except ValueError:
        resolved_pid = printer_id
    return {
        "printer_id": resolved_pid,
        "armed": armed,
        "armed_printers": local_timelapse_recorder.arm_printer(resolved_pid, armed),
    }


@app.get("/api/timelapses/{session_id}/media")
async def get_local_timelapse_media_endpoint(
    session_id: str,
    fmt: str = Query(default="webp"),
) -> FileResponse:
    """Sirve el timelapse local (`webp` para reproducir en app, `avi`/`mp4` para descargar, `thumb` miniatura)."""
    media_path = local_timelapse_recorder.get_media_path(session_id, fmt=fmt)
    if media_path is None:
        raise HTTPException(status_code=404, detail="Archivo de timelapse no encontrado.")
    mime_map = {
        "webp": "image/webp",
        "avi": "video/x-msvideo",
        "mp4": "video/mp4",
        "thumb": "image/jpeg",
    }
    return FileResponse(
        path=str(media_path),
        media_type=mime_map.get(fmt.lower(), "application/octet-stream"),
        filename=f"{session_id}.{fmt.lower() if fmt.lower() != 'thumb' else 'jpg'}",
    )


@app.delete("/api/timelapses/{session_id}")
async def delete_local_timelapse_endpoint(session_id: str) -> dict[str, Any]:
    """Elimina un timelapse local del disco."""
    deleted = local_timelapse_recorder.delete_timelapse(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Timelapse no encontrado.")
    return {"deleted": True, "session_id": session_id}


@app.get(
    "/api/printers/{printer_id}/telemetry-session",
    response_model=PrinterTelemetrySessionResponse,
)
async def get_printer_telemetry_session_endpoint(
    printer_id: PrinterId,
) -> PrinterTelemetrySessionResponse:
    """Devuelve la sesión de grabación continua actual más el último compendio IA."""
    try:
        resolved_pid, _cfg = get_printer_instance(printer_id)
    except ValueError:
        resolved_pid = printer_id
    return telemetry_recorder.get_printer_session(resolved_pid)


@app.post(
    "/api/printers/{printer_id}/telemetry-session/compendium",
    response_model=PostPrintCompendium,
)
async def generate_printer_compendium_endpoint(
    printer_id: PrinterId,
) -> PostPrintCompendium:
    """Genera o regenera el Compendio IA acumulado hasta el instante actual."""
    try:
        resolved_pid, cfg = get_printer_instance(printer_id)
        live_status = await _query_single_printer(resolved_pid, cfg, timeout=2.5)
    except ValueError:
        resolved_pid = printer_id
        live_status = None
    try:
        return await telemetry_recorder.generate_compendium_now(resolved_pid, live_status)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/api/telemetry/learnings",
    response_model=MachineMaterialLearningsResponse,
)
async def get_telemetry_learnings_endpoint(
    printer_id: PrinterId,
    material: str = "pla",
    limit: int = 3,
) -> MachineMaterialLearningsResponse:
    """Devuelve aprendizajes acumulados desde compendios previos para máquina + material."""
    return get_machine_material_learnings(printer_id, material, limit=limit)


@app.post("/api/ai/analyze-model", response_model=AIAnalyzeModelResponse)
async def ai_analyze_model_endpoint(req: AIAnalyzeModelRequest) -> AIAnalyzeModelResponse:
    """Fase 1 de Análisis IA: detecta tipo de modelo y devuelve 4-5 estrategias."""
    return await asyncio.to_thread(analyze_model_for_ai, req)


@app.post("/api/ai/optimize-slice", response_model=AIOptimizeSliceResponse)
async def ai_optimize_slice_endpoint(req: AIOptimizeSliceRequest) -> AIOptimizeSliceResponse:
    """Fase 2 de Análisis IA: calcula ángulo, soportes, capa, velocidad y piel difusa."""
    best_euler: tuple[float, float, float] | None = None
    if req.mesh_id and req.preset_id == "anti_support_angle":
        try:
            cached = _resolve_cached_model_path(req.mesh_id)
            printer = get_printer_config(req.printer_id)
            best_euler, _ = await asyncio.to_thread(
                find_optimal_anti_support_orientation,
                cached,
                printer,
                req.scale_percent,
            )
        except Exception:
            best_euler = None
    return await asyncio.to_thread(optimize_slice_with_ai, req, best_euler)


@app.post("/api/projects/save")
async def save_project_endpoint(req: SaveProjectRequest) -> dict[str, Any]:
    """Crea o actualiza un proyecto en `~/.nikk_slicer/projects/<project_id>/`."""
    saved = save_full_project(
        project_id=req.project_id,
        title=req.title,
        original_filename=req.original_filename,
        printer_id=req.printer_id,
        material=req.material,
        mesh_id=req.mesh_id,
        job_id=req.job_id,
        thumbnail_base64=req.thumbnail_base64,
        state=req.state,
    )
    return {"project": saved}


@app.get("/api/projects/recent")
async def list_recent_projects_endpoint(limit: int = 10) -> dict[str, Any]:
    """Devuelve los proyectos más recientes con miniatura y título corto en español (0 = todos)."""
    eff_limit = 0 if limit <= 0 else min(500, limit)
    return {"projects": list_recent_projects(limit=eff_limit)}


@app.get("/api/projects")
async def list_projects_endpoint() -> dict[str, Any]:
    """Lista los proyectos guardados (priorizando `~/.nikk_slicer/projects/`)."""
    recent = list_recent_projects(limit=30)
    if recent:
        return {"projects": recent}
    return {"projects": list_saved_projects()}


@app.get("/api/projects/{project_id}/thumbnail")
async def get_project_thumbnail_endpoint(project_id: str) -> FileResponse:
    """Sirve la miniatura PNG del proyecto guardado."""
    thumb = get_project_thumbnail_path(project_id)
    if thumb is None:
        raise HTTPException(status_code=404, detail="Miniatura no encontrada.")
    return FileResponse(path=thumb, media_type="image/png", filename="thumbnail.png")


@app.get("/api/projects/{project_id}/model")
async def get_project_model_endpoint(project_id: str) -> FileResponse:
    """Sirve el archivo STL/3MF original guardado en el proyecto."""
    found = get_project_model_path(project_id)
    if found is None:
        raise HTTPException(status_code=404, detail="Modelo del proyecto no encontrado.")
    model_path, orig_name = found
    return FileResponse(path=model_path, media_type="application/octet-stream", filename=orig_name)


@app.get("/api/projects/{project_id}")
async def get_project_endpoint(project_id: str) -> dict[str, Any]:
    """Devuelve el estado completo de un proyecto guardado."""
    full_proj = get_full_project(project_id)
    if full_proj is not None:
        return full_proj
    proj = get_saved_project(project_id)
    if proj is None:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return proj


@app.delete("/api/projects/{project_id}")
async def delete_project_endpoint(project_id: str) -> dict[str, Any]:
    """Elimina un proyecto del historial en `~/.nikk_slicer/projects/`."""
    ok = delete_full_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado.")
    return {"deleted": True, "project_id": project_id}


@app.get("/api/desktop/open-file")
async def desktop_open_local_model_endpoint(path: str) -> FileResponse:
    """Sirve un `.stl` o `.3mf` local abierto desde macOS Finder/Dock hacia el WebView."""
    target = Path(path).expanduser()
    if target.suffix.lower() not in (".stl", ".3mf"):
        raise HTTPException(status_code=400, detail="Solo se admiten archivos .stl o .3mf.")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco.")
    return FileResponse(path=target, media_type="application/octet-stream", filename=target.name)


@app.post("/api/ai/diagnose-defect", response_model=AIDefectDiagnoseResponse)
async def ai_diagnose_defect_endpoint(req: AIDefectDiagnoseRequest) -> AIDefectDiagnoseResponse:
    """Analiza un defecto físico post-impresión sobre los parámetros exactos de un proyecto."""
    proj_data: dict[str, Any] = {}
    if req.project_id:
        loaded = get_saved_project(req.project_id)
        if loaded is not None:
            proj_data = loaded
    if not proj_data and req.project_data:
        proj_data = req.project_data
    if not proj_data:
        raise HTTPException(status_code=404, detail="Proyecto no encontrado para diagnosticar.")
    return await asyncio.to_thread(diagnose_print_defect, req, proj_data)


@app.get("/api/system/environment")
def system_environment_endpoint() -> dict[str, Any]:
    """Devuelve SO, estado de laminadores detectados, configuración IA y servidor MCP."""
    return get_system_environment(mcp_tools_count=19)


@app.post("/api/system/rescan")
def system_rescan_endpoint() -> dict[str, Any]:
    """Vuelve a escanear los laminadores instalados en el equipo."""
    slicers = scan_installed_slicers()
    return {"slicers": slicers, "environment": get_system_environment(mcp_tools_count=19)}


@app.post("/api/system/set-slicer-path")
def system_set_slicer_path_endpoint(payload: dict[str, str]) -> dict[str, Any]:
    """Configura manualmente la ruta ejecutable de un laminador."""
    slicer_id = str(payload.get("slicer_id") or "").strip()
    executable_path = str(payload.get("executable_path") or "").strip()
    if not slicer_id or not executable_path:
        raise HTTPException(status_code=400, detail="slicer_id y executable_path son requeridos.")
    try:
        res = set_slicer_path(slicer_id, executable_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**res, "environment": get_system_environment(mcp_tools_count=19)}


@app.post("/api/system/ai-config")
def system_ai_config_endpoint(payload: dict[str, str]) -> dict[str, Any]:
    """Guarda el proveedor IA (deepseek/gemini) y la API Key del usuario."""
    provider = str(payload.get("provider") or "deepseek").strip()
    api_key = str(payload.get("api_key") or "").strip()
    try:
        cfg = save_ai_config(provider, api_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ai_config": cfg}


@app.post("/api/system/ai-test")
def system_ai_test_endpoint() -> dict[str, Any]:
    """Prueba la conexión con el motor IA activo (DeepSeek o Gemini)."""
    raw, prov = _call_ai_json('Responde exactamente con el JSON: {"status": "ok"}')
    return {
        "connected": raw is not None and prov != "HEURISTICA_LOCAL",
        "provider": prov,
    }


import threading
import time as _time

_LIVE_BRIDGE_LOCK = threading.Lock()
_LIVE_BRIDGE_PATH = TEMP_DIR / "live_ui_bridge.json"


def _read_live_bridge() -> dict[str, Any]:
    if not _LIVE_BRIDGE_PATH.is_file():
        return {"state": None, "commands": []}
    try:
        data = json.loads(_LIVE_BRIDGE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {"state": data.get("state"), "commands": list(data.get("commands") or [])}
    except Exception:
        pass
    return {"state": None, "commands": []}


def _write_live_bridge(data: dict[str, Any]) -> None:
    _LIVE_BRIDGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _LIVE_BRIDGE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


@app.post("/api/live/state")
def update_live_ui_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Sincroniza el estado actual del proyecto/perfil abierto en la UI."""
    with _LIVE_BRIDGE_LOCK:
        bridge = _read_live_bridge()
        bridge["state"] = payload
        _write_live_bridge(bridge)
    return {"ok": True}


@app.get("/api/live/state")
def get_live_ui_state() -> dict[str, Any]:
    """Devuelve el último estado reportado por la ventana abierta de Nikk Slicer."""
    with _LIVE_BRIDGE_LOCK:
        bridge = _read_live_bridge()
    return {"state": bridge.get("state")}


@app.post("/api/live/command")
def enqueue_live_ui_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Encola una modificación en vivo de perfil/re-laminado para la UI abierta."""
    cmd = {
        "id": uuid.uuid4().hex[:10],
        "action": str(payload.get("action") or "update_profile_and_reslice"),
        "params": dict(payload.get("params") or {}),
        "reslice": bool(payload.get("reslice", True)),
        "created_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
    }
    with _LIVE_BRIDGE_LOCK:
        bridge = _read_live_bridge()
        cmds = list(bridge.get("commands") or [])
        cmds.append(cmd)
        bridge["commands"] = cmds[-20:]
        _write_live_bridge(bridge)
    return {"ok": True, "command": cmd}


@app.get("/api/live/commands/poll")
def poll_live_ui_commands() -> dict[str, Any]:
    """Entrega y limpia comandos pendientes para la ventana abierta."""
    with _LIVE_BRIDGE_LOCK:
        bridge = _read_live_bridge()
        cmds = list(bridge.get("commands") or [])
        if cmds:
            bridge["commands"] = []
            _write_live_bridge(bridge)
    return {"commands": cmds}


try:
    from app.mcp_server import get_mcp_asgi_app

    class _MCPPathRewriteMiddleware:
        def __init__(self, asgi_app):
            self.asgi_app = asgi_app

        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http" and scope.get("path") == "/mcp":
                scope = dict(scope, path="/mcp/")
            await self.asgi_app(scope, receive, send)

    app.add_middleware(_MCPPathRewriteMiddleware)
    app.mount("/mcp", get_mcp_asgi_app())
except Exception:
    pass


FRONTEND_DIST_DIR = PROJECT_ROOT / "frontend" / "dist"
if FRONTEND_DIST_DIR.is_dir():
    _assets_dir = FRONTEND_DIST_DIR / "assets"
    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend_spa(full_path: str):
        """Sirve la compilación de producción React/Vite y hace fallback SPA hacia index.html."""
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Ruta API no encontrada.")
        if full_path:
            dist_root = FRONTEND_DIST_DIR.resolve()
            candidate = (FRONTEND_DIST_DIR / full_path).resolve()
            if candidate.is_file() and (candidate == dist_root or dist_root in candidate.parents):
                return FileResponse(candidate)
        index_html = FRONTEND_DIST_DIR / "index.html"
        if index_html.is_file():
            return FileResponse(index_html)
        raise HTTPException(status_code=404, detail="Frontend no compilado.")
