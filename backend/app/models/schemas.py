"""Esquemas Pydantic para análisis, auto-orientación, IA, laminado y Fase 3 (Hardware)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ProfileId = Literal[
    "flsun_v400",
    "flsun_t1_pro",
    "flsun_sr",
    "creator5_pro",
    "ender3_s1_pro",
]
PrinterId = str
MaterialType = Literal["pla", "petg", "abs", "tpu"]
QualityPreset = Literal[
    "estandar",
    "mecanico_resistente",
    "alta_velocidad",
    "rapidez_extrema",
]
SupportType = Literal["tree(auto)", "normal(auto)"]
AdhesionType = Literal["none", "brim", "raft"]


class DimensionsMM(BaseModel):
    """Dimensiones envolventes del modelo en milímetros."""

    x: float
    y: float
    z: float


class MultimaterialPartInfo(BaseModel):
    """Parte o sub-malla detectada dentro de un archivo `.3mf` multicolor."""

    part_id: str
    name: str
    extruder: int = Field(default=1, ge=1, le=4)
    color_hex: str | None = None
    triangle_count: int = 0
    paint_percentage: float | None = None


class MeshAnalysisResponse(BaseModel):
    """Resultado del análisis geométrico del STL/3MF con Trimesh."""

    mesh_id: str
    file_format: Literal["stl", "3mf"] = "stl"
    fits_in_volume: bool
    dimensions_mm: DimensionsMM
    triangle_count: int
    is_watertight: bool
    overhang_ratio: float
    suggests_supports: bool
    base_contact_area_mm2: float = 0.0
    suggests_raft: bool = False
    recommended_scale_percent: float = 100.0
    multimaterial_parts: list[MultimaterialPartInfo] = Field(default_factory=list)
    detected_extruder_count: int = 1
    is_multicolor: bool = False
    extruder_triangle_percentages: dict[str, float] = Field(default_factory=dict)
    detected_filament_colors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AutoOrientResponse(BaseModel):
    """Resultado de auto-orientación óptima mediante Oriented Bounding Box."""

    mesh_id: str
    rot_x: float
    rot_y: float
    rot_z: float
    scale_percent: float = 100.0
    message: str
    analysis: MeshAnalysisResponse


class ModelInstanceTransform(BaseModel):
    """Transformación CAD de una instancia individual en el plato."""

    instance_id: str = "inst_1"
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_z: float = 0.0
    scale_percent: float = Field(default=100.0, gt=0.1, le=2000.0)
    scale_x: float | None = Field(default=None, gt=0.1, le=2000.0)
    scale_y: float | None = Field(default=None, gt=0.1, le=2000.0)
    scale_z: float | None = Field(default=None, gt=0.1, le=2000.0)
    rot_x: float = 0.0
    rot_y: float = 0.0
    rot_z: float = 0.0
    drop_to_bed: bool = True


class AutoArrangeRequest(BaseModel):
    """Petición de empaquetado 2D multi-instancia sin colisiones en cama."""

    printer_id: PrinterId
    mesh_id: str
    instances: list[ModelInstanceTransform]
    min_distance_mm: float = Field(default=6.0, ge=1.0, le=50.0)


class AutoArrangeResponse(BaseModel):
    """Resultado de empaquetado automático con posiciones desplazadas en el plato."""

    instances: list[ModelInstanceTransform]
    fits_in_volume: bool
    warnings: list[str] = Field(default_factory=list)
    message: str


class LayOnFaceCandidate(BaseModel):
    """Faceta candidata del casco convexo para apoyar plana sobre Z = 0."""

    face_id: int
    normal: list[float]
    center: list[float]
    area_mm2: float
    rot_x: float
    rot_y: float
    rot_z: float


class LayOnFaceResponse(BaseModel):
    """Lista ordenada de caras planas principales del casco convexo."""

    mesh_id: str
    candidates: list[LayOnFaceCandidate] = Field(default_factory=list)


class CutMeshResponse(BaseModel):
    """Resultado de seccionar el modelo mediante un plano geométrico cerrado."""

    mesh_id: str
    download_url: str
    keep_mode: Literal["upper", "lower", "both"]
    cut_z_mm: float
    parts_count: int
    message: str
    analysis: MeshAnalysisResponse


class ExtruderSlotConfig(BaseModel):
    """Configuración individual de un cabezal T0..T3 para multicabezal (Creator 5 Pro)."""

    extruder_index: int = Field(ge=0, le=3)
    material: Literal["pla", "petg", "abs", "tpu", "soporte"] = "pla"
    color_hex: str = "#22d3ee"
    high_speed: bool = False
    spool_min: int | None = Field(default=None, ge=150, le=320)
    spool_max: int | None = Field(default=None, ge=150, le=320)
    nozzle_temp: int = Field(default=215, ge=160, le=320)
    nozzle_temp_initial_layer: int = Field(default=220, ge=160, le=320)
    max_volumetric_speed: float | None = Field(default=None, ge=1.0, le=60.0)
    flow_ratio: float | None = Field(default=None, ge=0.5, le=1.5)
    retraction_length: float | None = Field(default=None, ge=0.0, le=10.0)
    retraction_speed: float | None = Field(default=None, ge=5.0, le=120.0)


class ZColorRange(BaseModel):
    """Franja de altura Z asignada a un cabezal específico T0..T3."""

    min_z: float = Field(ge=0.0)
    max_z: float = Field(gt=0.0)
    extruder_index: int = Field(ge=0, le=3)


class SliceRequest(BaseModel):
    """Parámetros de entrada para laminar un STL."""

    printer_id: PrinterId
    material: MaterialType
    nozzle_temp: int = Field(ge=160, le=320)
    nozzle_temp_initial_layer: int | None = Field(default=None, ge=160, le=320)
    bed_temp: int = Field(ge=0, le=125)
    nozzle_diameter: float = Field(default=0.4, ge=0.2, le=0.8)
    high_speed_filament: bool = False
    lithophane_mode: bool = False
    supports: bool = False
    support_type: SupportType = "tree(auto)"
    support_on_build_plate_only: bool = True
    support_z_distance: float | None = Field(default=None, ge=0.05, le=0.5)
    support_xy_distance: float | None = Field(default=None, ge=0.1, le=2.0)
    adhesion_type: AdhesionType = "none"
    brim_width_mm: float = Field(default=6.0, ge=0.0, le=20.0)
    chamber_temp_target: int | None = Field(default=None, ge=25, le=55)
    prime_tower_mode: Literal["auto", "off", "ultra_save"] = "auto"
    enable_prime_tower: bool | None = None
    enable_timelapse: bool = False
    auto_leveling: bool = False
    quality_preset: QualityPreset = "estandar"
    mesh_id: str | None = None
    scale_percent: float = Field(default=100.0, gt=0.1, le=2000.0)
    scale_x: float | None = Field(default=None, gt=0.1, le=2000.0)
    scale_y: float | None = Field(default=None, gt=0.1, le=2000.0)
    scale_z: float | None = Field(default=None, gt=0.1, le=2000.0)
    rot_x: float = 0.0
    rot_y: float = 0.0
    rot_z: float = 0.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_z: float = 0.0
    drop_to_bed: bool = True
    instances: list[ModelInstanceTransform] = Field(default_factory=list)
    extruders_config: list[ExtruderSlotConfig] | None = None
    model_extruder: int = Field(default=0, ge=0, le=3)
    support_extruder: int = Field(default=0, ge=0, le=3)
    z_color_ranges: list[ZColorRange] = Field(default_factory=list)
    part_extruder_map: dict[str, int] = Field(default_factory=dict)


class SliceResponse(BaseModel):
    """Resultado completo del laminado CLI y análisis geométrico."""

    job_id: str
    gcode_url: str
    estimated_time: str
    estimated_time_seconds: int = 0
    filament_grams: float
    filament_meters: float
    support_time_seconds: int = 0
    support_weight_g: float = 0.0
    support_percentage: float = 0.0
    supports_enabled: bool = False
    support_type: str | None = None
    support_z_distance: float | None = None
    support_xy_distance: float | None = None
    mesh_warnings: list[str] = Field(default_factory=list)
    dimensions_mm: DimensionsMM


class AIRecommendRequest(BaseModel):
    """Entrada del copiloto IA basada en métricas geométricas reales de Trimesh."""

    printer_id: PrinterId
    material: MaterialType
    dimensions_mm: DimensionsMM
    overhang_ratio: float = Field(ge=0.0, le=1.0)
    base_contact_area_mm2: float = Field(default=0.0, ge=0.0)
    is_watertight: bool = True
    fits_in_volume: bool = True
    nozzle_diameter: float = Field(default=0.4, ge=0.2, le=0.8)
    high_speed_filament: bool = False
    lithophane_mode: bool = False
    multimaterial_parts_count: int = Field(default=0, ge=0)
    detected_extruder_count: int = Field(default=1, ge=1, le=4)
    is_multicolor: bool = False
    extruder_colors: list[str] = Field(default_factory=list)
    extruders_config: list[ExtruderSlotConfig] = Field(default_factory=list)
    extruder_triangle_percentages: dict[str, float] = Field(default_factory=dict)


class AIRecommendResponse(BaseModel):
    """Recomendación estructurada lista para aplicar en el Wizard."""

    supports: bool
    support_type: SupportType
    support_on_build_plate_only: bool
    support_z_distance: float
    support_xy_distance: float = 0.50
    adhesion_type: AdhesionType
    brim_width_mm: float = 6.0
    adhesion_label: str = ""
    prime_tower_enabled: bool = False
    prime_tower_mode: Literal["off", "ultra_save"] = "off"
    prime_tower_reason: str = ""
    nozzle_temp_initial_layer: int
    nozzle_temp: int
    bed_temp: int
    quality_preset: QualityPreset
    reasoning: str
    provider: Literal["GEMINI_API", "DEEPSEEK_API", "HEURISTICA_LOCAL"]
    suggest_reorient: bool = False
    recommended_rot_x: float | None = None
    recommended_rot_y: float | None = None
    recommended_rot_z: float | None = None


class AISupportOrientResponse(BaseModel):
    """Orientación anti-soportes + veredicto IA (DeepSeek API) para imprimir sin o con soportes."""

    mesh_id: str
    rot_x: float
    rot_y: float
    rot_z: float
    scale_percent: float
    apply_rotation: bool = True
    estimated_time_min: float = 0.0
    estimated_support_grams: float = 0.0
    estimated_savings_summary: str = ""
    supports_required: bool
    badge_status: Literal["SIN_SOPORTES", "SOPORTES_OBLIGATORIOS"]
    badge_label: str
    support_type: SupportType
    support_on_build_plate_only: bool
    support_z_distance: float
    support_xy_distance: float = 0.50
    adhesion_type: AdhesionType
    brim_width_mm: float = 6.0
    adhesion_label: str = ""
    critical_zone_description: str
    reasoning: str
    provider: Literal["GEMINI_API", "DEEPSEEK_API", "HEURISTICA_LOCAL"]
    analysis: MeshAnalysisResponse


class PrinterNetworkEntry(BaseModel):
    """Parámetros de conexión e identidad de una instancia física de impresora."""

    id: str = ""
    name: str = ""
    profile_id: ProfileId | None = None
    protocol: Literal["moonraker", "flashforge_lan", "marlin_serial"] = "moonraker"
    ip: str = ""
    fallback_ips: list[str] = Field(default_factory=list)
    port: int = 80
    http_port: int = 8080
    access_code: str = ""
    serial_number: str = ""
    serial_port: str = ""
    baudrate: int = 115200
    sd_volume_path: str = ""
    camera_url: str = ""
    enabled: bool = True


class PrintersConfigPayload(BaseModel):
    """Carga útil para actualizar granja de impresoras, puertos USB/SD y claves IA."""

    printers: dict[str, PrinterNetworkEntry]
    gemini_api_key: str | None = None
    deepseek_api_key: str | None = None


class PrintersConfigResponse(BaseModel):
    """Configuración persistida de red/hardware más autodetección macOS y estado de claves."""

    printers: dict[str, PrinterNetworkEntry]
    detected_serial_ports: list[str] = Field(default_factory=list)
    detected_volumes: list[str] = Field(default_factory=list)
    has_gemini_key: bool = False
    has_deepseek_key: bool = False
    gemini_key_masked: str = ""
    deepseek_key_masked: str = ""


class PrinterLiveStatus(BaseModel):
    """Telemetría unificada en tiempo real por máquina para el Dashboard de Granja."""

    printer_id: str
    profile_id: ProfileId | None = None
    display_name: str
    protocol: Literal["moonraker", "flashforge_lan", "marlin_serial"]
    ip: str = ""
    fallback_ips: list[str] = Field(default_factory=list)
    port: int = 80
    enabled: bool = True
    online: bool
    state: str
    nozzle_temp: float | None = None
    nozzle_target: float | None = None
    bed_temp: float | None = None
    bed_target: float | None = None
    progress_percent: float = 0.0
    current_file: str | None = None
    eta_seconds: int | None = None
    camera_url: str = ""
    message: str = ""
    light_on: bool = False
    current_layer: int | None = None
    total_layers: int | None = None
    print_speed_mms: float | None = None
    speed_factor_percent: float = 100.0
    flow_factor_percent: float = 100.0
    fan_speed_percent: float = 0.0
    elapsed_seconds: int | None = None
    mcu_temp: float | None = None
    host_temp: float | None = None
    chamber_temp: float | None = None
    chamber_target: float | None = None
    chamber_mode: str | None = None
    filament_used_mm: float = 0.0
    filament_used_g: float = 0.0


class SendPrintRequest(BaseModel):
    """Solicitud para enviar un G-code laminado a impresora de red, USB Serial o SD."""

    printer_id: PrinterId
    mode: Literal["network", "usb_serial", "sd_volume"] = "network"
    sd_volume_path: str | None = None
    start_immediately: bool = True
    start_print: bool | None = None
    enable_timelapse: bool = False
    auto_leveling: bool = False
    custom_filename: str | None = None


class SendPrintResponse(BaseModel):
    """Resultado de transmisión o guardado de G-code hacia hardware real."""

    status: str
    printer_id: PrinterId
    mode: str
    destination: str
    message: str


class UploadToPrinterRequest(BaseModel):
    """Solicitud para subir un G-code laminado directamente a una impresora específica."""

    job_id: str
    start_print: bool = False
    mode: Literal["network", "usb_serial", "sd_volume"] = "network"
    sd_volume_path: str | None = None
    enable_timelapse: bool = False
    auto_leveling: bool = False
    custom_filename: str | None = None


class PrinterStoredFile(BaseModel):
    """Archivo G-code o 3MF almacenado en la memoria interna de la impresora."""

    filename: str
    size_mb: float = 0.0
    modified_ts: float | None = None
    estimated_time_sec: int | None = None
    filament_grams: float | None = None


class PrinterFilesResponse(BaseModel):
    """Lista de archivos guardados en una impresora específica."""

    printer_id: str
    files: list[PrinterStoredFile] = Field(default_factory=list)


class PrinterFileActionRequest(BaseModel):
    """Acción sobre un archivo almacenado en la impresora."""

    filename: str
    enable_timelapse: bool = False
    auto_leveling: bool = False


class PrinterLightRequest(BaseModel):
    """Petición explícita para encender, apagar o conmutar la luz LED de la impresora."""

    on: bool | None = None


class PrinterTimelapseFile(BaseModel):
    """Video timelapse `.mp4` disponible en la impresora."""

    filename: str
    size_mb: float = 0.0
    modified_ts: float | None = None
    download_url: str


class PrinterTimelapsesResponse(BaseModel):
    """Lista de timelapses `.mp4` disponibles para descargar o reproducir."""

    printer_id: str
    timelapses: list[PrinterTimelapseFile] = Field(default_factory=list)
    message: str = ""


class AITelemetryDiagnosisResponse(BaseModel):
    """Diagnóstico en vivo generado por DeepSeek IA a partir de telemetría real."""

    printer_id: str
    status_badge: Literal["OPTIMO", "ATENCION", "CRITICO"]
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    provider: Literal["DEEPSEEK_API", "GEMINI_API", "HEURISTICA_LOCAL"]


class TelemetrySample(BaseModel):
    """Muestra puntual de telemetría capturada durante una impresión."""

    timestamp: float
    iso_time: str
    progress_pct: float = 0.0
    layer_current: int | None = None
    layer_total: int | None = None
    nozzle_temp: float | None = None
    nozzle_target: float | None = None
    bed_temp: float | None = None
    bed_target: float | None = None
    mcu_temp: float | None = None
    host_temp: float | None = None
    chamber_temp: float | None = None
    speed_mms: float | None = None
    speed_factor: float = 100.0
    flow_factor: float = 100.0
    fan_pct: float = 0.0
    filament_used_g: float = 0.0
    elapsed_seconds: int | None = None


class TelemetryPhaseStats(BaseModel):
    """Estadísticas min/avg/max de telemetría para una fase o toda la corrida."""

    samples_count: int = 0
    nozzle_min: float | None = None
    nozzle_avg: float | None = None
    nozzle_max: float | None = None
    bed_min: float | None = None
    bed_avg: float | None = None
    bed_max: float | None = None
    mcu_min: float | None = None
    mcu_avg: float | None = None
    mcu_max: float | None = None
    host_min: float | None = None
    host_avg: float | None = None
    host_max: float | None = None
    speed_min: float | None = None
    speed_avg: float | None = None
    speed_max: float | None = None
    fan_avg: float | None = None


class TelemetrySessionSummary(BaseModel):
    """Estadísticas consolidadas por fases de toda una sesión de impresión."""

    samples_count: int = 0
    duration_recorded_seconds: int = 0
    real_elapsed_seconds: int | None = None
    estimated_total_seconds: int | None = None
    filament_used_g: float = 0.0
    overall: TelemetryPhaseStats = Field(default_factory=TelemetryPhaseStats)
    phase_initial_0_5: TelemetryPhaseStats = Field(default_factory=TelemetryPhaseStats)
    phase_middle_5_85: TelemetryPhaseStats = Field(default_factory=TelemetryPhaseStats)
    phase_final_85_100: TelemetryPhaseStats = Field(default_factory=TelemetryPhaseStats)
    anomalies: list[str] = Field(default_factory=list)


class PostPrintCompendium(BaseModel):
    """Compendio final o acumulado de mejoras generado por DeepSeek API."""

    compendium_id: str
    session_id: str
    printer_id: str
    display_name: str
    filename: str
    detected_material: str = "PLA"
    rating: Literal["EXCELENTE", "BUENA_CON_MEJORAS", "REQUIERE_AJUSTE"]
    executive_summary: str
    improvements: list[str] = Field(default_factory=list)
    provider: Literal["DEEPSEEK_API", "GEMINI_API", "HEURISTICA_LOCAL"] = "HEURISTICA_LOCAL"
    generated_at: str
    is_partial: bool = False
    stats: TelemetrySessionSummary = Field(default_factory=TelemetrySessionSummary)


class TelemetrySessionState(BaseModel):
    """Estado de una sesión de grabación continua de telemetría."""

    session_id: str
    printer_id: str
    display_name: str
    filename: str
    status: Literal["recording", "completed", "cancelled"] = "recording"
    started_at: str
    ended_at: str | None = None
    samples_count: int = 0
    duration_recorded_seconds: int = 0
    last_progress_pct: float = 0.0
    live_stats: TelemetrySessionSummary = Field(default_factory=TelemetrySessionSummary)
    compendium: PostPrintCompendium | None = None


class PrinterTelemetrySessionResponse(BaseModel):
    """Respuesta combinada de sesión activa, último compendio final e historial."""

    printer_id: str
    active_session: TelemetrySessionState | None = None
    last_compendium: PostPrintCompendium | None = None
    history: list[PostPrintCompendium] = Field(default_factory=list)


class MachineMaterialLearningRun(BaseModel):
    """Resumen de una corrida previa usada para aprendizaje del laminador."""

    compendium_id: str
    printer_id: str
    filename: str
    rating: str
    nozzle_avg: float | None = None
    bed_avg: float | None = None
    speed_avg: float | None = None
    generated_at: str
    improvements: list[str] = Field(default_factory=list)


class MachineMaterialLearningsResponse(BaseModel):
    """Aprendizajes acumulados por impresora (y alias) + material desde compendios reales."""

    printer_id: str
    profile_id: str
    material: str
    runs_count: int = 0
    avg_nozzle_temp: float | None = None
    avg_bed_temp: float | None = None
    avg_speed_mms: float | None = None
    avg_mcu_max: float | None = None
    accumulated_improvements: list[str] = Field(default_factory=list)
    recent_runs: list[MachineMaterialLearningRun] = Field(default_factory=list)


class PrinterControlRequest(BaseModel):
    """Comando de control en vivo sobre la impresora."""

    action: Literal["pause", "resume", "cancel", "light_on", "light_off", "light_toggle"]
