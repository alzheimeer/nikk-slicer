const isViteDev =
  typeof window !== 'undefined' && window.location.port === '5173';
const BACKEND_ORIGIN =
  typeof window !== 'undefined' &&
  !isViteDev &&
  window.location.origin.startsWith('http')
    ? window.location.origin
    : 'http://127.0.0.1:8000';
export const API_BASE_URL = `${BACKEND_ORIGIN}/api`;

export type ProfileId =
  | 'flsun_v400'
  | 'flsun_t1_pro'
  | 'flsun_sr'
  | 'creator5_pro'
  | 'ender3_s1_pro';

export type PrinterId = string;

export type MaterialType = 'pla' | 'petg' | 'abs' | 'tpu';

export type QualityPreset =
  | 'estandar'
  | 'mecanico_resistente'
  | 'alta_velocidad'
  | 'rapidez_extrema';

export type NozzleDiameter = 0.2 | 0.4 | 0.6 | 0.8;
export type SupportType = 'tree(auto)' | 'normal(auto)';
export type AdhesionType = 'none' | 'brim' | 'raft';

export interface ModelInstanceTransform {
  instance_id: string;
  offset_x: number;
  offset_y: number;
  offset_z: number;
  scale_percent: number;
  scale_x?: number | null;
  scale_y?: number | null;
  scale_z?: number | null;
  rot_x: number;
  rot_y: number;
  rot_z: number;
  drop_to_bed: boolean;
}

export interface ModelTransform {
  scalePercent: number;
  scaleX?: number;
  scaleY?: number;
  scaleZ?: number;
  uniformScale?: boolean;
  rotX: number;
  rotY: number;
  rotZ: number;
  offsetX?: number;
  offsetY?: number;
  offsetZ?: number;
  dropToBed?: boolean;
  instances?: ModelInstanceTransform[];
}

export interface PrinterInfo {
  printer_id: PrinterId;
  profile_id: ProfileId;
  display_name: string;
  ip?: string;
  port?: number;
  protocol?: 'moonraker' | 'flashforge_lan' | 'marlin_serial';
  camera_url?: string;
  enabled?: boolean;
  kinematics: string;
  origin: 'center' | 'bottom_left';
  diameter_mm: number | null;
  height_mm: number;
  bed_mm: [number, number, number] | null;
  usable_edge_z_mm: number | null;
  max_volumetric_flow_mm3_s: number;
  extruder_slots: number;
  cli_binary: string;
}

export interface MachineProfileInfo {
  profile_id: ProfileId;
  display_name: string;
  kinematics: string;
  origin: 'center' | 'bottom_left';
  diameter_mm: number | null;
  height_mm: number;
  bed_mm: [number, number, number] | null;
  max_volumetric_flow_mm3_s: number;
  extruder_slots: number;
}

export interface CatalogResponse {
  printers: PrinterInfo[];
  machine_profiles?: MachineProfileInfo[];
  materials: MaterialType[];
  quality_presets: QualityPreset[];
  nozzle_diameters?: NozzleDiameter[];
  default_support_z_distance?: Record<string, number>;
  default_support_xy_distance?: Record<string, number>;
  volumetric_limits_mm3_s: Record<string, Record<string, number>>;
  high_speed_volumetric_limits_mm3_s?: Record<string, Record<string, number>>;
  cli_runtime?: {
    primary_cli_binary?: string;
    primary_cli_engine?: string;
  };
}

export interface DimensionsMM {
  x: number;
  y: number;
  z: number;
}

export interface MultimaterialPartInfo {
  part_id: string;
  name: string;
  extruder: number;
  color_hex: string | null;
  triangle_count: number;
}

export interface MeshAnalysisResponse {
  mesh_id: string;
  file_format?: 'stl' | '3mf';
  fits_in_volume: boolean;
  dimensions_mm: DimensionsMM;
  triangle_count: number;
  is_watertight: boolean;
  overhang_ratio: number;
  suggests_supports: boolean;
  base_contact_area_mm2: number;
  suggests_raft: boolean;
  recommended_scale_percent: number;
  multimaterial_parts?: MultimaterialPartInfo[];
  detected_extruder_count?: number;
  is_multicolor?: boolean;
  extruder_triangle_percentages?: Record<string, number>;
  detected_filament_colors?: string[];
  warnings: string[];
}

export interface AutoOrientResponse {
  mesh_id: string;
  rot_x: number;
  rot_y: number;
  rot_z: number;
  scale_percent: number;
  message: string;
  analysis: MeshAnalysisResponse;
}

export interface AutoArrangeResponse {
  instances: ModelInstanceTransform[];
  fits_in_volume: boolean;
  warnings: string[];
  message: string;
}

export interface LayOnFaceCandidate {
  face_id: number;
  normal: number[];
  center: number[];
  area_mm2: number;
  rot_x: number;
  rot_y: number;
  rot_z: number;
}

export interface LayOnFaceResponse {
  mesh_id: string;
  candidates: LayOnFaceCandidate[];
}

export interface CutMeshResponse {
  mesh_id: string;
  download_url: string;
  keep_mode: 'upper' | 'lower' | 'both';
  cut_z_mm: number;
  parts_count: number;
  message: string;
  analysis: MeshAnalysisResponse;
}

export interface AnalyzeMeshParams {
  printerId: PrinterId;
  file?: File;
  meshId?: string;
  transform?: ModelTransform;
}

export interface ExtruderSlotConfig {
  extruder_index: number;
  material: 'pla' | 'petg' | 'abs' | 'tpu' | 'soporte';
  color_hex: string;
  high_speed?: boolean;
  spool_min?: number;
  spool_max?: number;
  nozzle_temp: number;
  nozzle_temp_initial_layer: number;
  max_volumetric_speed?: number;
  flow_ratio?: number;
  retraction_length?: number;
  retraction_speed?: number;
}

export interface ZColorRange {
  min_z: number;
  max_z: number;
  extruder_index: number;
}

export interface SlicePayload {
  printer_id: PrinterId;
  material: MaterialType;
  nozzle_temp: number;
  nozzle_temp_initial_layer: number;
  bed_temp: number;
  nozzle_diameter: NozzleDiameter;
  high_speed_filament: boolean;
  lithophane_mode?: boolean;
  supports: boolean;
  support_type: SupportType;
  support_on_build_plate_only: boolean;
  support_z_distance: number;
  support_xy_distance?: number;
  adhesion_type: AdhesionType;
  brim_width_mm?: number;
  prime_tower_mode?: 'auto' | 'off' | 'ultra_save';
  enable_prime_tower?: boolean;
  enable_timelapse?: boolean;
  auto_leveling?: boolean;
  quality_preset: QualityPreset;
  mesh_id?: string | null;
  file?: File | null;
  transform?: ModelTransform;
  extruders_config?: ExtruderSlotConfig[];
  model_extruder?: number;
  support_extruder?: number;
  z_color_ranges?: ZColorRange[];
  part_extruder_map?: Record<string, number>;
}

export interface SliceResponse {
  job_id: string;
  gcode_url: string;
  estimated_time: string;
  estimated_time_seconds?: number;
  filament_grams: number;
  filament_meters: number;
  support_time_seconds?: number;
  support_weight_g?: number;
  support_percentage?: number;
  mesh_warnings: string[];
  dimensions_mm: DimensionsMM;
}

export interface AIRecommendPayload {
  printer_id: PrinterId;
  material: MaterialType;
  dimensions_mm: DimensionsMM;
  overhang_ratio: number;
  base_contact_area_mm2: number;
  is_watertight: boolean;
  fits_in_volume: boolean;
  nozzle_diameter: NozzleDiameter;
  high_speed_filament: boolean;
  lithophane_mode?: boolean;
  multimaterial_parts_count?: number;
  detected_extruder_count?: number;
  is_multicolor?: boolean;
  extruder_colors?: string[];
  extruders_config?: ExtruderSlotConfig[];
  extruder_triangle_percentages?: Record<string, number>;
}

export interface AIRecommendResponse {
  supports: boolean;
  support_type: SupportType;
  support_on_build_plate_only: boolean;
  support_z_distance: number;
  support_xy_distance?: number;
  adhesion_type: AdhesionType;
  brim_width_mm?: number;
  adhesion_label?: string;
  prime_tower_enabled?: boolean;
  prime_tower_mode?: 'off' | 'ultra_save';
  prime_tower_reason?: string;
  nozzle_temp_initial_layer: number;
  nozzle_temp: number;
  bed_temp: number;
  quality_preset: QualityPreset;
  reasoning: string;
  provider: 'GEMINI_API' | 'DEEPSEEK_API' | 'HEURISTICA_LOCAL';
  suggest_reorient?: boolean;
  recommended_rot_x?: number | null;
  recommended_rot_y?: number | null;
  recommended_rot_z?: number | null;
}

export interface AISupportOrientResponse {
  mesh_id: string;
  rot_x: number;
  rot_y: number;
  rot_z: number;
  scale_percent: number;
  apply_rotation?: boolean;
  estimated_time_min?: number;
  estimated_support_grams?: number;
  estimated_savings_summary?: string;
  supports_required: boolean;
  badge_status: 'SIN_SOPORTES' | 'SOPORTES_OBLIGATORIOS';
  badge_label: string;
  support_type: SupportType;
  support_on_build_plate_only: boolean;
  support_z_distance: number;
  support_xy_distance?: number;
  adhesion_type: AdhesionType;
  brim_width_mm?: number;
  adhesion_label?: string;
  critical_zone_description: string;
  reasoning: string;
  provider: 'GEMINI_API' | 'DEEPSEEK_API' | 'HEURISTICA_LOCAL';
  analysis: MeshAnalysisResponse;
}

export interface PrinterNetworkEntry {
  id: string;
  name: string;
  profile_id: ProfileId;
  protocol: 'moonraker' | 'flashforge_lan' | 'marlin_serial';
  ip: string;
  fallback_ips?: string[];
  port: number;
  http_port: number;
  access_code: string;
  serial_number: string;
  serial_port: string;
  baudrate: number;
  sd_volume_path: string;
  camera_url: string;
  enabled: boolean;
}

export interface PrintersConfigResponse {
  printers: Record<string, PrinterNetworkEntry>;
  detected_serial_ports: string[];
  detected_volumes: string[];
  has_gemini_key: boolean;
  has_deepseek_key: boolean;
  gemini_key_masked: string;
  deepseek_key_masked: string;
}

export interface PrintersConfigPayload {
  printers: Record<string, PrinterNetworkEntry>;
  gemini_api_key?: string;
  deepseek_api_key?: string;
}

export interface PrinterLiveStatus {
  printer_id: PrinterId;
  profile_id?: ProfileId | null;
  display_name: string;
  protocol: 'moonraker' | 'flashforge_lan' | 'marlin_serial';
  ip?: string;
  port?: number;
  enabled?: boolean;
  online: boolean;
  state: string;
  nozzle_temp: number | null;
  nozzle_target: number | null;
  bed_temp: number | null;
  bed_target: number | null;
  progress_percent: number;
  current_file: string | null;
  eta_seconds: number | null;
  camera_url: string;
  message: string;
  light_on?: boolean;
  current_layer?: number | null;
  total_layers?: number | null;
  print_speed_mms?: number | null;
  speed_factor_percent?: number;
  flow_factor_percent?: number;
  fan_speed_percent?: number;
  elapsed_seconds?: number | null;
  mcu_temp?: number | null;
  host_temp?: number | null;
  chamber_temp?: number | null;
  filament_used_mm?: number;
  filament_used_g?: number;
}

export interface PrinterStoredFile {
  filename: string;
  size_mb: number;
  modified_ts?: number | null;
  estimated_time_sec?: number | null;
  filament_grams?: number | null;
}

export interface PrinterFilesResponse {
  printer_id: string;
  files: PrinterStoredFile[];
}

export interface PrinterTimelapseFile {
  filename: string;
  size_mb: number;
  modified_ts?: number | null;
  download_url: string;
}

export interface PrinterTimelapsesResponse {
  printer_id: string;
  timelapses: PrinterTimelapseFile[];
  message: string;
}

export interface AITelemetryDiagnosisResponse {
  printer_id: string;
  status_badge: 'OPTIMO' | 'ATENCION' | 'CRITICO';
  summary: string;
  recommendations: string[];
  provider: 'DEEPSEEK_API' | 'GEMINI_API' | 'HEURISTICA_LOCAL';
}

export interface TelemetryPhaseStats {
  samples_count: number;
  nozzle_min: number | null;
  nozzle_avg: number | null;
  nozzle_max: number | null;
  bed_min: number | null;
  bed_avg: number | null;
  bed_max: number | null;
  mcu_min: number | null;
  mcu_avg: number | null;
  mcu_max: number | null;
  host_min: number | null;
  host_avg: number | null;
  host_max: number | null;
  speed_min: number | null;
  speed_avg: number | null;
  speed_max: number | null;
  fan_avg: number | null;
}

export interface TelemetrySessionSummary {
  samples_count: number;
  duration_recorded_seconds: number;
  real_elapsed_seconds: number | null;
  estimated_total_seconds: number | null;
  filament_used_g: number;
  overall: TelemetryPhaseStats;
  phase_initial_0_5: TelemetryPhaseStats;
  phase_middle_5_85: TelemetryPhaseStats;
  phase_final_85_100: TelemetryPhaseStats;
  anomalies: string[];
}

export interface PostPrintCompendium {
  compendium_id: string;
  session_id: string;
  printer_id: string;
  display_name: string;
  filename: string;
  detected_material: string;
  rating: 'EXCELENTE' | 'BUENA_CON_MEJORAS' | 'REQUIERE_AJUSTE';
  executive_summary: string;
  improvements: string[];
  provider: 'DEEPSEEK_API' | 'GEMINI_API' | 'HEURISTICA_LOCAL';
  generated_at: string;
  is_partial: boolean;
  stats: TelemetrySessionSummary;
}

export interface TelemetrySessionState {
  session_id: string;
  printer_id: string;
  display_name: string;
  filename: string;
  status: 'recording' | 'completed' | 'cancelled';
  started_at: string;
  ended_at: string | null;
  samples_count: number;
  duration_recorded_seconds: number;
  last_progress_pct: number;
  live_stats: TelemetrySessionSummary;
  compendium: PostPrintCompendium | null;
}

export interface PrinterTelemetrySessionResponse {
  printer_id: string;
  active_session: TelemetrySessionState | null;
  last_compendium: PostPrintCompendium | null;
  history: PostPrintCompendium[];
}

export interface MachineMaterialLearningRun {
  compendium_id: string;
  printer_id: string;
  filename: string;
  rating: string;
  nozzle_avg: number | null;
  bed_avg: number | null;
  speed_avg: number | null;
  generated_at: string;
  improvements: string[];
}

export interface MachineMaterialLearningsResponse {
  printer_id: string;
  profile_id: string;
  material: string;
  runs_count: number;
  avg_nozzle_temp: number | null;
  avg_bed_temp: number | null;
  avg_speed_mms: number | null;
  avg_mcu_max: number | null;
  accumulated_improvements: string[];
  recent_runs: MachineMaterialLearningRun[];
}

export interface SendPrintResponse {
  status: string;
  printer_id: PrinterId;
  mode: string;
  destination: string;
  message: string;
}

async function parseError(response: Response): Promise<string> {
  try {
    const data = await response.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (data?.detail?.message) {
      const extra = Array.isArray(data.detail.warnings)
        ? ` — ${data.detail.warnings.join(' | ')}`
        : '';
      return `${data.detail.message}${extra}`;
    }
    return JSON.stringify(data);
  } catch {
    return `HTTP ${response.status} ${response.statusText}`;
  }
}

export async function fetchCatalog(): Promise<CatalogResponse> {
  const res = await fetch(`${API_BASE_URL}/catalog`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<CatalogResponse>;
}

export async function analyzeMesh({
  printerId,
  file,
  meshId,
  transform,
}: AnalyzeMeshParams): Promise<MeshAnalysisResponse> {
  const form = new FormData();
  form.append('printer_id', printerId);
  if (meshId) {
    form.append('mesh_id', meshId);
  } else if (file) {
    form.append('file', file);
  }
  if (transform) {
    form.append('scale_percent', String(transform.scalePercent));
    if (transform.scaleX !== undefined) form.append('scale_x', String(transform.scaleX));
    if (transform.scaleY !== undefined) form.append('scale_y', String(transform.scaleY));
    if (transform.scaleZ !== undefined) form.append('scale_z', String(transform.scaleZ));
    form.append('rot_x', String(transform.rotX));
    form.append('rot_y', String(transform.rotY));
    form.append('rot_z', String(transform.rotZ));
    form.append('offset_x', String(transform.offsetX ?? 0));
    form.append('offset_y', String(transform.offsetY ?? 0));
    form.append('offset_z', String(transform.offsetZ ?? 0));
    form.append('drop_to_bed', String(transform.dropToBed ?? true));
    if (transform.instances && transform.instances.length > 0) {
      form.append('instances_json', JSON.stringify(transform.instances));
    }
  }

  const res = await fetch(`${API_BASE_URL}/analyze-mesh`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<MeshAnalysisResponse>;
}

export async function autoArrangeModels(payload: {
  printer_id: PrinterId;
  mesh_id: string;
  instances: ModelInstanceTransform[];
  min_distance_mm?: number;
}): Promise<AutoArrangeResponse> {
  const res = await fetch(`${API_BASE_URL}/auto-arrange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AutoArrangeResponse>;
}

export async function fetchLayOnFaceCandidates({
  printerId,
  meshId,
  file,
  transform,
}: {
  printerId: PrinterId;
  meshId?: string | null;
  file?: File | null;
  transform: ModelTransform;
}): Promise<LayOnFaceResponse> {
  const form = new FormData();
  form.append('printer_id', printerId);
  if (meshId) form.append('mesh_id', meshId);
  else if (file) form.append('file', file);
  form.append('scale_percent', String(transform.scalePercent));
  if (transform.scaleX !== undefined) form.append('scale_x', String(transform.scaleX));
  if (transform.scaleY !== undefined) form.append('scale_y', String(transform.scaleY));
  if (transform.scaleZ !== undefined) form.append('scale_z', String(transform.scaleZ));
  form.append('rot_x', String(transform.rotX));
  form.append('rot_y', String(transform.rotY));
  form.append('rot_z', String(transform.rotZ));

  const res = await fetch(`${API_BASE_URL}/lay-on-face`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<LayOnFaceResponse>;
}

export async function cutMeshByPlane({
  printerId,
  meshId,
  file,
  cutZMm,
  tiltXDeg = 0,
  tiltYDeg = 0,
  keepMode,
  transform,
}: {
  printerId: PrinterId;
  meshId?: string | null;
  file?: File | null;
  cutZMm: number;
  tiltXDeg?: number;
  tiltYDeg?: number;
  keepMode: 'upper' | 'lower' | 'both';
  transform: ModelTransform;
}): Promise<CutMeshResponse> {
  const form = new FormData();
  form.append('printer_id', printerId);
  if (meshId) form.append('mesh_id', meshId);
  else if (file) form.append('file', file);
  form.append('cut_z_mm', String(cutZMm));
  form.append('tilt_x_deg', String(tiltXDeg));
  form.append('tilt_y_deg', String(tiltYDeg));
  form.append('keep_mode', keepMode);
  form.append('scale_percent', String(transform.scalePercent));
  if (transform.scaleX !== undefined) form.append('scale_x', String(transform.scaleX));
  if (transform.scaleY !== undefined) form.append('scale_y', String(transform.scaleY));
  if (transform.scaleZ !== undefined) form.append('scale_z', String(transform.scaleZ));
  form.append('rot_x', String(transform.rotX));
  form.append('rot_y', String(transform.rotY));
  form.append('rot_z', String(transform.rotZ));

  const res = await fetch(`${API_BASE_URL}/cut-mesh`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<CutMeshResponse>;
}

export async function fetchCachedMeshFile(
  meshId: string,
  fileName = `cut_${meshId}.stl`,
): Promise<File> {
  const res = await fetch(`${API_BASE_URL}/meshes/${meshId}`);
  if (!res.ok) {
    throw new Error(`No se pudo descargar la malla ${meshId} (${res.status})`);
  }
  const blob = await res.blob();
  return new File([blob], fileName, { type: 'application/octet-stream' });
}

export async function autoOrientMesh({
  printerId,
  meshId,
  file,
  scalePercent = 100,
}: {
  printerId: PrinterId;
  meshId?: string | null;
  file?: File | null;
  scalePercent?: number;
}): Promise<AutoOrientResponse> {
  const form = new FormData();
  form.append('printer_id', printerId);
  form.append('scale_percent', String(scalePercent));
  if (meshId) {
    form.append('mesh_id', meshId);
  } else if (file) {
    form.append('file', file);
  }

  const res = await fetch(`${API_BASE_URL}/auto-orient`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AutoOrientResponse>;
}

export async function fetchAIRecommendation(
  payload: AIRecommendPayload,
): Promise<AIRecommendResponse> {
  const res = await fetch(`${API_BASE_URL}/ai-recommend`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AIRecommendResponse>;
}

export async function requestAISupportOrient({
  printerId,
  material,
  nozzleDiameter,
  highSpeedFilament,
  lithophaneMode,
  meshId,
  file,
  scalePercent = 100,
  rotX = 0,
  rotY = 0,
  rotZ = 0,
  currentSupportConfig,
  currentSliceMetrics,
}: {
  printerId: PrinterId;
  material: MaterialType;
  nozzleDiameter: NozzleDiameter;
  highSpeedFilament: boolean;
  lithophaneMode?: boolean;
  meshId?: string | null;
  file?: File | null;
  scalePercent?: number;
  rotX?: number;
  rotY?: number;
  rotZ?: number;
  currentSupportConfig?: Record<string, unknown>;
  currentSliceMetrics?: Record<string, unknown>;
}): Promise<AISupportOrientResponse> {
  const form = new FormData();
  form.append('printer_id', printerId);
  form.append('material', material);
  form.append('nozzle_diameter', String(nozzleDiameter));
  form.append('high_speed_filament', String(highSpeedFilament));
  if (lithophaneMode !== undefined) {
    form.append('lithophane_mode', String(lithophaneMode));
  }
  form.append('scale_percent', String(scalePercent));
  form.append('rot_x', String(rotX));
  form.append('rot_y', String(rotY));
  form.append('rot_z', String(rotZ));
  if (currentSupportConfig) {
    form.append('current_support_config_json', JSON.stringify(currentSupportConfig));
  }
  if (currentSliceMetrics) {
    form.append('current_slice_metrics_json', JSON.stringify(currentSliceMetrics));
  }
  if (meshId) {
    form.append('mesh_id', meshId);
  } else if (file) {
    form.append('file', file);
  }

  const res = await fetch(`${API_BASE_URL}/ai-support-orient`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AISupportOrientResponse>;
}

export async function sliceModel(payload: SlicePayload): Promise<SliceResponse> {
  const form = new FormData();
  form.append('printer_id', payload.printer_id);
  form.append('material', payload.material);
  form.append('nozzle_temp', String(payload.nozzle_temp));
  form.append(
    'nozzle_temp_initial_layer',
    String(payload.nozzle_temp_initial_layer),
  );
  form.append('bed_temp', String(payload.bed_temp));
  form.append('nozzle_diameter', String(payload.nozzle_diameter));
  form.append('high_speed_filament', String(payload.high_speed_filament));
  if (payload.lithophane_mode !== undefined) {
    form.append('lithophane_mode', String(payload.lithophane_mode));
  }
  form.append('supports', String(payload.supports));
  form.append('support_type', payload.support_type);
  form.append(
    'support_on_build_plate_only',
    String(payload.support_on_build_plate_only),
  );
  form.append('support_z_distance', String(payload.support_z_distance));
  if (payload.support_xy_distance !== undefined) {
    form.append('support_xy_distance', String(payload.support_xy_distance));
  }
  form.append('adhesion_type', payload.adhesion_type);
  if (payload.brim_width_mm !== undefined) {
    form.append('brim_width_mm', String(payload.brim_width_mm));
  }
  if (payload.prime_tower_mode !== undefined) {
    form.append('prime_tower_mode', payload.prime_tower_mode);
  }
  if (payload.enable_prime_tower !== undefined) {
    form.append('enable_prime_tower', String(payload.enable_prime_tower));
  }
  if (payload.enable_timelapse !== undefined) {
    form.append('enable_timelapse', String(payload.enable_timelapse));
  }
  if (payload.auto_leveling !== undefined) {
    form.append('auto_leveling', String(payload.auto_leveling));
  }
  form.append('quality_preset', payload.quality_preset);

  if (payload.mesh_id) {
    form.append('mesh_id', payload.mesh_id);
  } else if (payload.file) {
    form.append('file', payload.file);
  }

  if (payload.transform) {
    form.append('scale_percent', String(payload.transform.scalePercent));
    if (payload.transform.scaleX !== undefined) {
      form.append('scale_x', String(payload.transform.scaleX));
    }
    if (payload.transform.scaleY !== undefined) {
      form.append('scale_y', String(payload.transform.scaleY));
    }
    if (payload.transform.scaleZ !== undefined) {
      form.append('scale_z', String(payload.transform.scaleZ));
    }
    form.append('rot_x', String(payload.transform.rotX));
    form.append('rot_y', String(payload.transform.rotY));
    form.append('rot_z', String(payload.transform.rotZ));
    form.append('offset_x', String(payload.transform.offsetX ?? 0));
    form.append('offset_y', String(payload.transform.offsetY ?? 0));
    form.append('offset_z', String(payload.transform.offsetZ ?? 0));
    form.append('drop_to_bed', String(payload.transform.dropToBed ?? true));
    if (payload.transform.instances && payload.transform.instances.length > 0) {
      form.append('instances_json', JSON.stringify(payload.transform.instances));
    }
  }

  if (payload.extruders_config) {
    form.append('extruders_config_json', JSON.stringify(payload.extruders_config));
  }
  if (payload.model_extruder !== undefined) {
    form.append('model_extruder', String(payload.model_extruder));
  }
  if (payload.support_extruder !== undefined) {
    form.append('support_extruder', String(payload.support_extruder));
  }
  if (payload.z_color_ranges) {
    form.append('z_color_ranges_json', JSON.stringify(payload.z_color_ranges));
  }
  if (payload.part_extruder_map && Object.keys(payload.part_extruder_map).length > 0) {
    form.append('part_extruder_map_json', JSON.stringify(payload.part_extruder_map));
  }

  const res = await fetch(`${API_BASE_URL}/slice`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<SliceResponse>;
}

export function getGcodeUrl(gcodeUrlOrJobId: string, customFilename?: string): string {
  let base: string;
  if (
    gcodeUrlOrJobId.startsWith('http://') ||
    gcodeUrlOrJobId.startsWith('https://')
  ) {
    base = gcodeUrlOrJobId;
  } else if (gcodeUrlOrJobId.startsWith('/')) {
    base = `${BACKEND_ORIGIN}${gcodeUrlOrJobId}`;
  } else {
    base = `${API_BASE_URL}/download/${gcodeUrlOrJobId}`;
  }
  if (customFilename && customFilename.trim()) {
    const sep = base.includes('?') ? '&' : '?';
    return `${base}${sep}filename=${encodeURIComponent(customFilename.trim())}`;
  }
  return base;
}

export async function fetchGcodeText(gcodeUrlOrJobId: string): Promise<string> {
  const res = await fetch(getGcodeUrl(gcodeUrlOrJobId));
  if (!res.ok) {
    throw new Error(`No se pudo descargar el G-code (${res.status})`);
  }
  return res.text();
}

export async function fetchPrintersConfig(): Promise<PrintersConfigResponse> {
  const res = await fetch(`${API_BASE_URL}/printers/config`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PrintersConfigResponse>;
}

export async function updatePrintersConfig(
  payload: PrintersConfigPayload,
): Promise<PrintersConfigResponse> {
  const res = await fetch(`${API_BASE_URL}/printers/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PrintersConfigResponse>;
}

export async function fetchPrintersStatus(): Promise<PrinterLiveStatus[]> {
  const res = await fetch(`${API_BASE_URL}/printers/status`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PrinterLiveStatus[]>;
}

export async function testPrinterConnection(
  entry: PrinterNetworkEntry,
): Promise<PrinterLiveStatus> {
  const res = await fetch(`${API_BASE_URL}/printers/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(entry),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PrinterLiveStatus>;
}

export interface DiscoveredPrinter {
  ip: string;
  port: number;
  protocol: 'moonraker' | 'flashforge_lan';
  suggested_profile: ProfileId;
  hostname: string;
  camera_url: string;
}

export async function discoverNetworkPrinters(): Promise<{
  subnet: string;
  discovered: DiscoveredPrinter[];
}> {
  const res = await fetch(`${API_BASE_URL}/printers/discover`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{ subnet: string; discovered: DiscoveredPrinter[] }>;
}

export async function sendJobToPrinter(
  jobId: string,
  payload: {
    printer_id: PrinterId;
    mode: 'network' | 'usb_serial' | 'sd_volume';
    sd_volume_path?: string;
    start_immediately?: boolean;
    start_print?: boolean;
    enable_timelapse?: boolean;
    auto_leveling?: boolean;
    custom_filename?: string;
  },
): Promise<SendPrintResponse> {
  const res = await fetch(`${API_BASE_URL}/print/${jobId}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<SendPrintResponse>;
}

export async function uploadJobToPrinter(
  printerId: PrinterId,
  payload: {
    job_id: string;
    start_print: boolean;
    mode: 'network' | 'usb_serial' | 'sd_volume';
    sd_volume_path?: string;
    enable_timelapse?: boolean;
    auto_leveling?: boolean;
    custom_filename?: string;
  },
): Promise<SendPrintResponse> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/upload`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<SendPrintResponse>;
}

export async function controlPrinter(
  printerId: PrinterId,
  action: 'pause' | 'resume' | 'cancel' | 'light_on' | 'light_off' | 'light_toggle',
): Promise<{ status: string; printer_id: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action }),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{ status: string; printer_id: string; message: string }>;
}

export async function togglePrinterLight(
  printerId: PrinterId,
  on?: boolean,
): Promise<{ status: string; printer_id: string; light_on: boolean; message: string }> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/light`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(on === undefined ? {} : { on }),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{
    status: string;
    printer_id: string;
    light_on: boolean;
    message: string;
  }>;
}

export async function fetchPrinterFiles(
  printerId: PrinterId,
): Promise<PrinterFilesResponse> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/files`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PrinterFilesResponse>;
}

export async function printStoredFile(
  printerId: PrinterId,
  filename: string,
  enableTimelapse = false,
  autoLeveling = false,
): Promise<{ status: string; printer_id: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/files/print`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      filename,
      enable_timelapse: enableTimelapse,
      auto_leveling: autoLeveling,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{ status: string; printer_id: string; message: string }>;
}

export async function deleteStoredFile(
  printerId: PrinterId,
  filename: string,
): Promise<{ status: string; printer_id: string; message: string }> {
  const res = await fetch(
    `${API_BASE_URL}/printers/${printerId}/files?filename=${encodeURIComponent(filename)}`,
    { method: 'DELETE' },
  );
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{ status: string; printer_id: string; message: string }>;
}

export async function deleteAllStoredFiles(
  printerId: PrinterId,
): Promise<{
  status: string;
  printer_id: string;
  deleted_count: number;
  failed_count: number;
  message: string;
}> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/files/all`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{
    status: string;
    printer_id: string;
    deleted_count: number;
    failed_count: number;
    message: string;
  }>;
}

export async function fetchPrinterTimelapses(
  printerId: PrinterId,
): Promise<PrinterTimelapsesResponse> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/timelapses`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PrinterTimelapsesResponse>;
}

export async function requestAITelemetryDiagnosis(
  printerId: PrinterId,
): Promise<AITelemetryDiagnosisResponse> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/ai-telemetry`, {
    method: 'POST',
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AITelemetryDiagnosisResponse>;
}

export async function fetchPrinterTelemetrySession(
  printerId: PrinterId,
): Promise<PrinterTelemetrySessionResponse> {
  const res = await fetch(`${API_BASE_URL}/printers/${printerId}/telemetry-session`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PrinterTelemetrySessionResponse>;
}

export async function generatePrinterCompendium(
  printerId: PrinterId,
): Promise<PostPrintCompendium> {
  const res = await fetch(
    `${API_BASE_URL}/printers/${printerId}/telemetry-session/compendium`,
    { method: 'POST' },
  );
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<PostPrintCompendium>;
}

export async function fetchTelemetryLearnings(
  printerId: PrinterId,
  material: string,
  limit = 3,
): Promise<MachineMaterialLearningsResponse> {
  const qs = new URLSearchParams({
    printer_id: printerId,
    material,
    limit: String(limit),
  });
  const res = await fetch(`${API_BASE_URL}/telemetry/learnings?${qs.toString()}`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<MachineMaterialLearningsResponse>;
}
