"""Servidor FastAPI principal de SlicerHub."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

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
    diagnose_live_telemetry,
    generate_ai_recommendation,
    generate_ai_support_decision,
)
from app.core.json_patcher import patch_profiles_for_job
from app.core.print_telemetry_recorder import (
    get_machine_material_learnings,
    telemetry_recorder,
    telemetry_recorder_worker,
)
from app.core.mesh_analyzer import (
    analyze_model_file,
    auto_arrange_instances,
    auto_orient_mesh,
    compute_lay_on_face_candidates,
    cut_mesh_by_plane,
    find_optimal_anti_support_orientation,
    load_and_transform_mesh,
    prepare_painted_3mf_for_slicer,
    sanitize_euler_rotation,
    transform_and_export_3mf_parts,
)
from app.core.slicer_router import run_slicer_cli
from app.models.schemas import (
    AIRecommendRequest,
    AIRecommendResponse,
    AISupportOrientResponse,
    AITelemetryDiagnosisResponse,
    AdhesionType,
    AutoArrangeRequest,
    AutoArrangeResponse,
    AutoOrientResponse,
    CutMeshResponse,
    ExtruderSlotConfig,
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
    return list(await asyncio.gather(*tasks))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    telemetry_recorder.load_persisted_state()
    worker_task = asyncio.create_task(
        telemetry_recorder_worker(_poll_enabled_for_recorder, interval_sec=10.0)
    )
    try:
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


@app.get("/api/health")
def health_endpoint() -> dict[str, str]:
    """Comprobación rápida de disponibilidad para el lanzador de escritorio."""
    return {"status": "ok", "app": "Nikk Slicer", "version": "1.3.0"}


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
        printers.append(
            {
                "printer_id": inst_id,
                "profile_id": profile_id,
                "display_name": inst_cfg.get("name") or base.display_name,
                "ip": inst_cfg.get("ip", ""),
                "port": inst_cfg.get("port", 7125),
                "protocol": inst_cfg.get("protocol", "moonraker"),
                "camera_url": inst_cfg.get("camera_url", ""),
                "enabled": bool(inst_cfg.get("enabled", True)),
                "kinematics": base.kinematics,
                "origin": base.origin,
                "diameter_mm": base.diameter_mm,
                "height_mm": base.height_mm,
                "bed_mm": list(base.bed_mm) if base.bed_mm else None,
                "usable_edge_z_mm": base.usable_edge_z_mm,
                "max_volumetric_flow_mm3_s": base.max_volumetric_flow_mm3_s,
                "extruder_slots": base.extruder_slots,
                "cli_binary": str(base.cli_binary),
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

    if use_multimaterial_3mf:
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
        patched = patch_profiles_for_job(req, job_dir, multimaterial_3mf=True)
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
        )
        patched = patch_profiles_for_job(req, job_dir, multimaterial_3mf=True)
        model_input = painted_3mf_path
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
        patched = patch_profiles_for_job(req, job_dir)
        model_input = stl_for_slicer
        f_ids = None

    try:
        result = run_slicer_cli(
            printer, model_input, patched, request=req, filament_ids=f_ids
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
        mesh_warnings=analysis.warnings,
        dimensions_mm=analysis.dimensions_mm,
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
    support_on_build_plate_only: bool = Form(True),
    support_z_distance: float | None = Form(None),
    support_xy_distance: float | None = Form(None),
    adhesion_type: AdhesionType = Form("none"),
    brim_width_mm: float = Form(6.0),
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
            support_type=support_type,
            support_on_build_plate_only=support_on_build_plate_only,
            support_z_distance=support_z_distance,
            support_xy_distance=support_xy_distance,
            adhesion_type=eff_adhesion,
            brim_width_mm=eff_brim_w,
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
def download_gcode(job_id: str, filename: str | None = None) -> FileResponse:
    """Descarga el archivo `.gcode` generado para un `job_id` con nombre personalizado."""
    if not job_id.isalnum():
        raise HTTPException(status_code=400, detail="job_id inválido.")
    out_dir = TEMP_DIR / job_id / "output"
    gcodes = sorted(out_dir.glob("*.gcode")) if out_dir.exists() else []
    if not gcodes:
        raise HTTPException(status_code=404, detail="G-code no encontrado para este job_id.")
    safe_name = _sanitize_gcode_filename(filename, job_id)
    return FileResponse(
        path=gcodes[0],
        media_type="text/plain; charset=utf-8",
        filename=safe_name,
    )


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
        return await query_flashforge_status(pid, display_name, cfg, timeout=timeout)
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
            msg = await upload_and_start_flashforge(
                cfg,
                gcode_path,
                filename,
                start_immediately=start_immediately,
                enable_timelapse=enable_timelapse,
                auto_leveling=auto_leveling,
            )
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
    return await asyncio.to_thread(diagnose_live_telemetry, live_status)


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
