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

export type SupportPaintMap = Record<number, 1 | 2>;
export type SupportPaintMode = 'auto' | 'enforcers_only';

export interface ObjectPrintOverrides {
  enable_support?: 'inherit' | boolean;
  support_type?: 'inherit' | 'tree(auto)' | 'normal(auto)';
  brim_type?: 'inherit' | 'no_brim' | 'outer_only' | 'brim_and_skirt' | 'raft';
  brim_width?: number;
  raft_layers?: number;
}

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
  overrides?: ObjectPrintOverrides;
  support_paint_map?: SupportPaintMap;
  support_paint_mode?: SupportPaintMode;
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
  vendor?: string;
  model_name?: string;
  ip?: string;
  port?: number;
  protocol?: 'moonraker' | 'flashforge_lan' | 'marlin_serial';
  connection_mode?: 'lan' | 'usb_sd';
  camera_url?: string;
  enabled?: boolean;
  is_custom?: boolean;
  kinematics: string;
  origin: 'center' | 'bottom_left';
  bed_shape?: 'circular' | 'rectangular';
  diameter_mm: number | null;
  height_mm: number;
  bed_mm: [number, number, number] | null;
  usable_edge_z_mm: number | null;
  max_volumetric_flow_mm3_s: number;
  extruder_slots: number;
  gcode_flavor?: string;
  is_multicolor?: boolean;
  tool_count?: number;
  has_heated_chamber?: boolean;
  is_high_speed?: boolean;
  nozzle_diameter?: number;
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
  z_min_mm?: number;
  z_max_mm?: number;
  suggested_slot?: number | null;
}

export interface LayerPauseItem {
  layer: number;
  note?: string;
  z_mm?: number | null;
  source?: 'manual' | 'auto_multicolor';
  slot?: number | null;
  outgoing_color?: string | null;
  incoming_color?: string | null;
}

export interface DetectedColorInfo {
  index: number;
  zone_key: string;
  name: string;
  hex_color: string;
  percentage: number;
  z_min_mm: number;
  z_max_mm: number;
  suggested_slot: number;
}

export interface ApplyPausesResponse {
  job_id: string;
  applied_pauses: LayerPauseItem[];
  gcode_text: string;
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
  detected_colors?: DetectedColorInfo[];
  scene_objects?: SceneObjectInfo[];
  warnings: string[];
}

export interface SceneObjectInfo {
  object_id: string;
  name: string;
  extruder: number;
  color_hex: string | null;
  mesh_url: string;
  position: [number, number, number];
  rotation: [number, number, number];
  scale: [number, number, number];
  dimensions_mm: [number, number, number];
}

export interface SceneObjectTransform {
  object_id: string;
  name: string;
  extruder: number;
  color_hex: string | null;
  mesh_url: string;
  offset_x: number;
  offset_y: number;
  offset_z: number;
  rot_x: number;
  rot_y: number;
  rot_z: number;
  scale_percent: number;
  scale_x?: number | null;
  scale_y?: number | null;
  scale_z?: number | null;
  drop_to_bed: boolean;
  dimensions_mm: [number, number, number];
  overrides?: ObjectPrintOverrides;
  support_paint_map?: SupportPaintMap;
  support_paint_mode?: SupportPaintMode;
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
  support_style?: string;
  support_on_build_plate_only: boolean;
  support_z_distance: number;
  support_xy_distance?: number;
  adhesion_type: AdhesionType;
  brim_width_mm?: number;
  chamber_temp_target?: number;
  layer_height_override?: number;
  outer_wall_speed_override?: number;
  flow_ratio_override?: number;
  infill_density_override?: number;
  fuzzy_skin?: boolean;
  fuzzy_skin_thickness?: number;
  fuzzy_skin_point_distance?: number;
  ai_strategy_label?: string;
  model_filename?: string;
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
  layer_pauses?: LayerPauseItem[];
  scene_objects?: SceneObjectTransform[];
  quality_overrides?: string[];
  profile_overrides?: Record<string, unknown>;
  support_blockers?: SupportBlockerItem[];
}

export interface SupportBlockerItem {
  id: string;
  x: number;
  y: number;
  z: number;
  radius: number;
}

export interface SlicedProfileFilament {
  slot: string;
  material: string;
  brand_or_name: string;
  color_hex: string;
  nozzle_temp_initial: number;
  nozzle_temp: number;
  bed_temp_initial: number;
  bed_temp: number;
  fan_min_speed: number;
  fan_max_speed: number;
  overhang_fan_speed: number;
  retraction_length: number;
  retraction_speed: number;
  max_volumetric_flow: number;
  density_g_cm3: number;
  cost_per_kg_cop: number;
}

export interface SlicedProfileSnapshot {
  quality: {
    layer_height: number;
    initial_layer_height: number;
    line_width: number;
    outer_wall_line_width: number;
    inner_wall_line_width?: number;
    top_surface_line_width?: number;
    infill_line_width?: number;
    support_line_width?: number;
    wall_generator: string;
    seam_position: string;
    ironing_type: string;
    top_surface_pattern: string;
  };
  strength: {
    wall_loops: number;
    top_shell_layers: number;
    bottom_shell_layers: number;
    sparse_infill_density: string;
    sparse_infill_pattern: string;
    infill_wall_overlap: string;
  };
  speed: {
    outer_wall_speed: number;
    inner_wall_speed: number;
    initial_layer_speed: number;
    sparse_infill_speed: number;
    top_surface_speed?: number;
    overhang_speed: number;
    overhang_1_4_speed?: number;
    overhang_2_4_speed?: number;
    overhang_3_4_speed?: number;
    overhang_4_4_speed?: number;
    bridge_speed?: number;
    travel_speed: number;
    max_volumetric_speed_qmax: number;
    acceleration_print: number;
  };
  support: {
    enable_support: boolean;
    support_type: string;
    support_style?: string;
    support_threshold_angle: number;
    support_top_z_distance: number;
    support_bottom_z_distance: number;
    support_object_xy_distance: number;
    support_interface_top_layers: number;
    support_interface_bottom_layers?: number;
    support_interface_spacing: number;
    support_interface_pattern: string;
    per_object_overrides?: Array<{
      name: string;
      enable_support?: 'inherit' | boolean;
      support_type?: string;
    }>;
  };
  multimaterial: {
    active_tools: string[];
    tool_mapping: Record<string, number>;
    enable_prime_tower: boolean;
    prime_tower_width: number;
    prime_tower_brim_width?: number;
    flush_volumes: unknown;
    support_interface_filament: number;
    z_color_changes: ZColorRange[];
  };
  others: {
    brim_type: string;
    brim_width: number;
    skirt_loops: number;
    layer_pauses: LayerPauseItem[];
    anti_stringing_active: boolean;
    chamber_temp?: number;
    bed_temp?: number;
    gcode_filename?: string;
    printer_name: string;
    slicer_engine: string;
    sliced_at_timestamp: string;
    per_object_overrides?: Array<{
      name: string;
      brim_type?: string;
      brim_width?: number;
      raft_layers?: number;
    }>;
  };
  filaments: SlicedProfileFilament[];
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
  supports_enabled?: boolean;
  support_type?: string | null;
  support_z_distance?: number | null;
  support_xy_distance?: number | null;
  mesh_warnings: string[];
  dimensions_mm: DimensionsMM;
  applied_pauses?: LayerPauseItem[];
  sliced_profile_snapshot?: SlicedProfileSnapshot | null;
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
  support_style?: string;
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
  support_style?: string;
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
  chamber_target?: number | null;
  chamber_mode?: string | null;
  filament_used_mm?: number;
  filament_used_g?: number;
  error_code?: string | null;
  error_message?: string | null;
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

async function fetchWithTimeout(
  url: string,
  init: RequestInit = {},
  timeoutMs = 15000,
): Promise<Response> {
  const controller = new AbortController();
  const externalSignal = init.signal;
  const onExternalAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal) {
    if (externalSignal.aborted) {
      controller.abort(externalSignal.reason);
    } else {
      externalSignal.addEventListener('abort', onExternalAbort, { once: true });
    }
  }
  const timer = window.setTimeout(() => {
    controller.abort(new Error(`Tiempo de espera agotado (${Math.round(timeoutMs / 1000)}s).`));
  }, timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      if (externalSignal?.aborted) {
        throw new Error('Operación cancelada por el usuario.');
      }
      throw new Error(`Tiempo de espera agotado (${Math.round(timeoutMs / 1000)}s).`);
    }
    throw err;
  } finally {
    window.clearTimeout(timer);
    if (externalSignal) {
      externalSignal.removeEventListener('abort', onExternalAbort);
    }
  }
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

export interface OrientationRotation {
  rx: number;
  ry: number;
  rz: number;
}

export interface OrientationOption {
  id: string;
  title: string;
  badge: string;
  rotation: OrientationRotation;
  z_height_mm: number;
  overhang_ratio_pct: number;
  contact_area_mm2: number;
  estimated_time_delta_pct: string;
  explanation: string;
  stability_warning?: string | null;
  fits_bed: boolean;
  is_recommended: boolean;
  quaternion?: number[] | null;
  per_object_rotations?: Record<string, OrientationRotation>;
}

export interface AIOrientationsResponse {
  mesh_id: string;
  model_name: string;
  is_multicolor: boolean;
  multicolor_parts_count: number;
  hero_face_detected?: boolean;
  hero_face_normal?: number[] | null;
  ai_provider: 'GEMINI_API' | 'DEEPSEEK_API' | 'HEURISTICA_LOCAL';
  recommended_id: string;
  target_object_id?: string | null;
  flat_base_preserved_ids?: string[];
  options: OrientationOption[];
}

export async function requestAIOrientations({
  printerId,
  material,
  meshId,
  file,
  scalePercent = 100,
  objectId,
  sceneObjects,
}: {
  printerId: PrinterId;
  material: MaterialType;
  meshId?: string | null;
  file?: File | null;
  scalePercent?: number;
  objectId?: string | null;
  sceneObjects?: SceneObjectTransform[];
}): Promise<AIOrientationsResponse> {
  const form = new FormData();
  form.append('printer_id', printerId);
  form.append('material', material);
  form.append('scale_percent', String(scalePercent));
  if (objectId) {
    form.append('object_id', objectId);
  }
  if (sceneObjects && sceneObjects.length > 1) {
    form.append(
      'scene_objects_json',
      JSON.stringify(
        sceneObjects.map((o) => ({
          object_id: o.object_id,
          name: o.name,
          scale_percent: o.scale_percent,
          rot_x: o.rot_x,
          rot_y: o.rot_y,
          rot_z: o.rot_z,
        })),
      ),
    );
  }
  if (meshId) {
    form.append('mesh_id', meshId);
  } else if (file) {
    form.append('file', file);
  }

  const res = await fetch(`${API_BASE_URL}/ai/orientations`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AIOrientationsResponse>;
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

export interface AIPresetOption {
  id: string;
  label: string;
  description: string;
  badge?: string | null;
}

export interface AISubOption {
  id: string;
  label: string;
  description: string;
  preset_id: string;
  layer_height: number;
  calibrated_speed_mms: number;
  calibrated_temp_c: number;
  estimated_time_str: string;
  estimated_time_seconds: number;
  quality_overrides?: string[];
}

export interface AILayerResolutionGroup {
  layer_height: number;
  title: string;
  subtitle: string;
  calibrated_speed_mms: number;
  calibrated_temp_c: number;
  estimated_time_str: string;
  estimated_time_seconds: number;
  is_recommended: boolean;
  options: AISubOption[];
}

export interface AIAnalyzeModelResponse {
  detected_type_summary: string;
  short_spanish_title?: string;
  model_category:
    | 'lithophane_flat'
    | 'character_organic'
    | 'mechanical_functional'
    | 'large_enclosure';
  filter_note: string;
  contextual_options: AISubOption[];
  recommended_presets: AIPresetOption[];
  layer_resolutions: AILayerResolutionGroup[];
  all_layer_resolutions: AILayerResolutionGroup[];
  provider: 'GEMINI_API' | 'DEEPSEEK_API' | 'HEURISTICA_LOCAL';
}

export interface AIOptimizeSliceResponse {
  strategy_label: string;
  explanation: string;
  apply_rotation: boolean;
  rot_x: number;
  rot_y: number;
  rot_z: number;
  supports_required: boolean;
  support_type: SupportType;
  support_style?: string;
  support_on_build_plate_only: boolean;
  support_z_distance: number;
  support_xy_distance: number;
  adhesion_type: AdhesionType;
  brim_width_mm: number;
  layer_height: number;
  outer_wall_speed?: number | null;
  flow_ratio?: number | null;
  nozzle_temp?: number | null;
  infill_density?: number | null;
  fuzzy_skin: boolean;
  fuzzy_skin_thickness: number;
  fuzzy_skin_point_distance: number;
  provider: 'GEMINI_API' | 'DEEPSEEK_API' | 'HEURISTICA_LOCAL';
}

export interface SavedProjectRecord {
  project_id: string;
  created_at: string;
  gcode_filename: string;
  model_filename: string;
  mesh_id?: string | null;
  printer_id: PrinterId;
  material: MaterialType;
  nozzle_diameter: number;
  quality_preset: QualityPreset;
  ai_strategy?: string;
  transform: {
    scale_percent?: number;
    rot_x?: number;
    rot_y?: number;
    rot_z?: number;
  };
  params: Record<string, unknown>;
  metrics: {
    estimated_time?: string;
    estimated_time_seconds?: number;
    filament_grams?: number;
    filament_meters?: number;
    support_weight_g?: number;
    support_percentage?: number;
  };
}

export interface AIDefectDiagnoseResponse {
  root_cause: string;
  explanation: string;
  corrected_params: Record<string, unknown>;
  provider: 'GEMINI_API' | 'DEEPSEEK_API' | 'HEURISTICA_LOCAL';
}

export async function requestAIAnalyzeModel(
  payload: Record<string, unknown>,
): Promise<AIAnalyzeModelResponse> {
  const res = await fetch(`${API_BASE_URL}/ai/analyze-model`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AIAnalyzeModelResponse>;
}

export async function requestAIOptimizeSlice(
  payload: Record<string, unknown>,
): Promise<AIOptimizeSliceResponse> {
  const res = await fetch(`${API_BASE_URL}/ai/optimize-slice`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AIOptimizeSliceResponse>;
}

export async function fetchSavedProjects(): Promise<SavedProjectRecord[]> {
  const res = await fetch(`${API_BASE_URL}/projects`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  const data = (await res.json()) as { projects?: SavedProjectRecord[] };
  return Array.isArray(data.projects) ? data.projects : [];
}

export function getSavedProjectDownloadUrl(projectId: string): string {
  return `${API_BASE_URL}/projects/${encodeURIComponent(projectId)}`;
}

export interface FullProjectSummary {
  project_id: string;
  title: string;
  original_filename: string;
  created_at: string;
  updated_at: string;
  printer_id: PrinterId | string;
  material: MaterialType | string;
  has_thumbnail: boolean;
  thumbnail_url: string | null;
  slice_metrics?: {
    estimated_time?: string;
    filament_grams?: number;
    filament_meters?: number;
    total_cost_cop?: number;
  };
}

export interface FullProjectRecord extends FullProjectSummary {
  state: Record<string, unknown>;
  gcode_text?: string | null;
  model_url?: string | null;
}

export async function saveFullProject(payload: {
  project_id?: string | null;
  title: string;
  original_filename: string;
  printer_id: PrinterId;
  material: MaterialType;
  mesh_id?: string | null;
  job_id?: string | null;
  thumbnail_base64?: string | null;
  state: Record<string, unknown>;
}): Promise<FullProjectSummary> {
  const res = await fetch(`${API_BASE_URL}/projects/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  const data = (await res.json()) as { project: FullProjectSummary };
  return data.project;
}

export async function fetchRecentProjects(limit = 5): Promise<FullProjectSummary[]> {
  const res = await fetch(`${API_BASE_URL}/projects/recent?limit=${limit}`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  const data = (await res.json()) as { projects?: FullProjectSummary[] };
  return Array.isArray(data.projects) ? data.projects : [];
}

export async function fetchFullProject(projectId: string): Promise<FullProjectRecord> {
  const res = await fetch(`${API_BASE_URL}/projects/${encodeURIComponent(projectId)}`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<FullProjectRecord>;
}

export async function deleteFullProject(projectId: string): Promise<void> {
  const res = await fetch(`${API_BASE_URL}/projects/${encodeURIComponent(projectId)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
}

export function getProjectModelFileUrl(projectId: string): string {
  return `${API_BASE_URL}/projects/${encodeURIComponent(projectId)}/model`;
}

export function getProjectThumbnailUrl(projectId: string): string {
  return `${API_BASE_URL}/projects/${encodeURIComponent(projectId)}/thumbnail`;
}

export async function requestAIDefectDiagnose(payload: {
  project_id?: string;
  project_data?: Record<string, unknown>;
  defect_description: string;
}): Promise<AIDefectDiagnoseResponse> {
  const res = await fetch(`${API_BASE_URL}/ai/diagnose-defect`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<AIDefectDiagnoseResponse>;
}

export async function sliceModel(
  payload: SlicePayload,
  signal?: AbortSignal,
): Promise<SliceResponse> {
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
  if (payload.support_style) {
    form.append('support_style', payload.support_style);
  }
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
  if (payload.chamber_temp_target !== undefined) {
    form.append('chamber_temp_target', String(payload.chamber_temp_target));
  }
  if (payload.layer_height_override !== undefined) {
    form.append('layer_height_override', String(payload.layer_height_override));
  }
  if (payload.outer_wall_speed_override !== undefined) {
    form.append('outer_wall_speed_override', String(payload.outer_wall_speed_override));
  }
  if (payload.flow_ratio_override !== undefined) {
    form.append('flow_ratio_override', String(payload.flow_ratio_override));
  }
  if (payload.infill_density_override !== undefined) {
    form.append('infill_density_override', String(payload.infill_density_override));
  }
  if (payload.fuzzy_skin !== undefined) {
    form.append('fuzzy_skin', String(payload.fuzzy_skin));
  }
  if (payload.fuzzy_skin_thickness !== undefined) {
    form.append('fuzzy_skin_thickness', String(payload.fuzzy_skin_thickness));
  }
  if (payload.fuzzy_skin_point_distance !== undefined) {
    form.append('fuzzy_skin_point_distance', String(payload.fuzzy_skin_point_distance));
  }
  if (payload.ai_strategy_label) {
    form.append('ai_strategy_label', payload.ai_strategy_label);
  }
  if (payload.model_filename) {
    form.append('model_filename', payload.model_filename);
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
  if (payload.layer_pauses && payload.layer_pauses.length > 0) {
    form.append('layer_pauses_json', JSON.stringify(payload.layer_pauses));
  }
  if (payload.scene_objects && payload.scene_objects.length > 0) {
    form.append('scene_objects_json', JSON.stringify(payload.scene_objects));
  }
  if (payload.quality_overrides && payload.quality_overrides.length > 0) {
    form.append('quality_overrides_json', JSON.stringify(payload.quality_overrides));
  }
  if (payload.profile_overrides && Object.keys(payload.profile_overrides).length > 0) {
    form.append('profile_overrides_json', JSON.stringify(payload.profile_overrides));
  }
  if (payload.support_blockers && payload.support_blockers.length > 0) {
    form.append('support_blockers_json', JSON.stringify(payload.support_blockers));
  }

  const res = await fetchWithTimeout(
    `${API_BASE_URL}/slice`,
    {
      method: 'POST',
      body: form,
      signal,
    },
    360000,
  );
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<SliceResponse>;
}

export async function splitMeshObjects({
  printerId,
  meshId,
  file,
}: {
  printerId: PrinterId;
  meshId?: string | null;
  file?: File | null;
}): Promise<{ mesh_id: string; scene_objects: SceneObjectInfo[] }> {
  const form = new FormData();
  form.append('printer_id', printerId);
  if (meshId) {
    form.append('mesh_id', meshId);
  } else if (file) {
    form.append('file', file);
  }
  const res = await fetch(`${API_BASE_URL}/models/split-objects`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{ mesh_id: string; scene_objects: SceneObjectInfo[] }>;
}

export async function applyLayerPauses({
  jobId,
  printerId,
  pauses,
}: {
  jobId: string;
  printerId: PrinterId;
  pauses: LayerPauseItem[];
}): Promise<ApplyPausesResponse> {
  const res = await fetch(`${API_BASE_URL}/slicer/apply-pauses`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      job_id: jobId,
      printer_id: printerId,
      pauses,
    }),
  });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<ApplyPausesResponse>;
}

export interface DetectedSlicerInfo {
  id: 'orcaslicer' | 'orca_flashforge' | 'flsun_slicer';
  name: string;
  required: boolean;
  description: string;
  detected: boolean;
  executable_path: string | null;
  profiles_path: string | null;
  download_url: string;
}

export interface SystemEnvironmentResponse {
  os: string;
  platform: string;
  user_data_dir: string;
  slicers: DetectedSlicerInfo[];
  has_primary_slicer: boolean;
  missing_required: string[];
  ai_config: {
    provider: 'deepseek' | 'gemini';
    has_api_key: boolean;
    masked_key: string;
  };
  mcp: {
    http_url: string;
    stdio_command: string;
    tools_count: number;
  };
}

export async function fetchSystemEnvironment(): Promise<SystemEnvironmentResponse> {
  const res = await fetch(`${API_BASE_URL}/system/environment`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<SystemEnvironmentResponse>;
}

export async function rescanSystemSlicers(): Promise<{
  slicers: DetectedSlicerInfo[];
  environment: SystemEnvironmentResponse;
}> {
  const res = await fetch(`${API_BASE_URL}/system/rescan`, { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{
    slicers: DetectedSlicerInfo[];
    environment: SystemEnvironmentResponse;
  }>;
}

export async function setManualSlicerPath(
  slicerId: string,
  executablePath: string,
): Promise<{ environment: SystemEnvironmentResponse }> {
  const res = await fetch(`${API_BASE_URL}/system/set-slicer-path`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slicer_id: slicerId, executable_path: executablePath }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ environment: SystemEnvironmentResponse }>;
}

export async function saveSystemAIConfig(
  provider: 'deepseek' | 'gemini',
  apiKey: string,
): Promise<{ ai_config: SystemEnvironmentResponse['ai_config'] }> {
  const res = await fetch(`${API_BASE_URL}/system/ai-config`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, api_key: apiKey }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ ai_config: SystemEnvironmentResponse['ai_config'] }>;
}

export async function testSystemAIConnection(): Promise<{
  connected: boolean;
  provider: string;
}> {
  const res = await fetch(`${API_BASE_URL}/system/ai-test`, { method: 'POST' });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ connected: boolean; provider: string }>;
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
  const res = await fetchWithTimeout(`${API_BASE_URL}/printers/status`, {}, 12000);
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
  const res = await fetchWithTimeout(
    `${API_BASE_URL}/printers/${printerId}/command`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action }),
    },
    15000,
  );
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

export function getPrinterStoredFileDownloadUrl(
  printerId: PrinterId,
  filename: string,
): string {
  return `${API_BASE_URL}/printers/${printerId}/files/download?filename=${encodeURIComponent(filename)}`;
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

export interface ErrorJournalEntry {
  timestamp: string;
  source: string;
  printer_id?: string;
  message: string;
  detail?: string;
  context?: Record<string, unknown>;
}

export interface ErrorJournalResponse {
  log_path: string;
  count: number;
  entries: ErrorJournalEntry[];
}

export async function fetchErrorJournal(limit = 60): Promise<ErrorJournalResponse> {
  const res = await fetch(`${API_BASE_URL}/logs/errors?limit=${limit}`);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<ErrorJournalResponse>;
}

export async function clearErrorJournal(): Promise<{ status: string; message: string }> {
  const res = await fetch(`${API_BASE_URL}/logs/errors`, { method: 'DELETE' });
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json() as Promise<{ status: string; message: string }>;
}

export async function fetchUserPrefs(): Promise<Record<string, unknown>> {
  const res = await fetchWithTimeout(`${API_BASE_URL}/prefs`, {}, 6000);
  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  const data = (await res.json()) as { prefs?: Record<string, unknown> };
  return data.prefs ?? {};
}

export async function saveUserPrefs(payload: Record<string, unknown>): Promise<void> {
  await fetchWithTimeout(
    `${API_BASE_URL}/prefs`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    6000,
  );
}

export async function clearLastSession(): Promise<void> {
  await fetchWithTimeout(`${API_BASE_URL}/prefs/last-session`, { method: 'DELETE' }, 6000);
}

export interface OrcaCatalogCapabilities {
  is_multicolor: boolean;
  tool_count: number;
  has_heated_chamber: boolean;
  is_high_speed: boolean;
}

export interface OrcaCatalogPrinter {
  catalog_id: string;
  vendor: string;
  vendor_key: string;
  model_name: string;
  nozzle_diameters: number[];
  profile_sub_path: string;
  bed_shape: 'rectangular' | 'circular';
  bed_width_mm: number;
  bed_depth_mm: number;
  bed_diameter_mm: number | null;
  max_height_mm: number;
  kinematics: string;
  gcode_flavor: string;
  max_speed_mm_s: number;
  max_accel_mm_s2: number;
  estimated_q_max: number;
  capabilities: OrcaCatalogCapabilities;
}

export interface OrcaCatalogSearchResponse {
  printers: OrcaCatalogPrinter[];
  total: number;
  catalog_total: number;
  vendors: string[];
}

export interface AddPrinterPayload {
  catalog_id: string;
  display_name?: string;
  nozzle_diameter?: number;
  connection_mode?: 'lan' | 'usb_sd';
  ip?: string;
  port?: number;
  protocol?: 'moonraker' | 'flashforge_lan' | 'marlin_serial';
  is_multicolor?: boolean;
  tool_count?: number;
}

export async function fetchPrinterCatalog(params: {
  q?: string;
  vendor?: string;
  multicolor_only?: boolean;
  limit?: number;
}): Promise<OrcaCatalogSearchResponse> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.vendor) qs.set('vendor', params.vendor);
  if (params.multicolor_only) qs.set('multicolor_only', 'true');
  if (params.limit) qs.set('limit', String(params.limit));
  const res = await fetchWithTimeout(`${API_BASE_URL}/printers/catalog?${qs.toString()}`, {}, 10000);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<OrcaCatalogSearchResponse>;
}

export async function syncPrinterCatalog(): Promise<{ synced_count: number; vendors: number }> {
  const res = await fetchWithTimeout(`${API_BASE_URL}/printers/catalog/sync`, { method: 'POST' }, 45000);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ synced_count: number; vendors: number }>;
}

export async function addCustomPrinter(payload: AddPrinterPayload): Promise<{ ok: boolean; printer: { id: string } & Record<string, unknown> }> {
  const res = await fetchWithTimeout(
    `${API_BASE_URL}/printers/add`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    10000,
  );
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ ok: boolean; printer: { id: string } & Record<string, unknown> }>;
}

export async function deleteUserPrinter(printerId: string): Promise<void> {
  const res = await fetchWithTimeout(
    `${API_BASE_URL}/printers/${encodeURIComponent(printerId)}`,
    { method: 'DELETE' },
    8000,
  );
  if (!res.ok) throw new Error(await parseError(res));
}

export async function exportSelection(payload: {
  mesh_id: string;
  printer_id: PrinterId;
  format: 'stl' | '3mf' | 'obj';
  apply_transforms: boolean;
  center_on_bed: boolean;
  export_all_plate?: boolean;
  scene_objects?: SceneObjectTransform[];
  instances?: ModelInstanceTransform[];
  part_extruder_map?: Record<string, number>;
  filename_base?: string;
}): Promise<{ blob: Blob; filename: string }> {
  const res = await fetchWithTimeout(
    `${API_BASE_URL}/export-selection`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
    60000,
  );
  if (!res.ok) throw new Error(await parseError(res));
  const cd = res.headers.get('content-disposition') || '';
  const m = cd.match(/filename="?([^"]+)"?/i);
  const ext = payload.format;
  const filename = m ? m[1] : `${payload.filename_base || 'export'}.${ext}`;
  const blob = await res.blob();
  return { blob, filename };
}
