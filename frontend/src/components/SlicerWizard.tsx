import { useEffect, useMemo, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { GlobalProcessingOverlay, type ProcessingOverlayMode } from './GlobalProcessingOverlay';
import { ProfileInspectorDrawer } from './ProfileInspectorDrawer';
import {
  PRINTER_WATTS,
  QuoteCalculatorModal,
  loadWorkshopPreset,
  type WorkshopPreset,
} from './QuoteCalculatorModal';
import { useI18n } from '../i18n/I18nContext';
import {
  AlertTriangle,
  Calculator,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  Download,
  ExternalLink,
  FileUp,
  Flame,
  Gauge,
  HardDrive,
  Layers,
  Loader2,
  Palette,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Ruler,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Thermometer,
  Trash2,
  Upload,
  Usb,
  Video,
  X,
  Zap,
} from 'lucide-react';
import {
  API_BASE_URL,
  fetchTelemetryLearnings,
  getGcodeUrl,
  requestAIDefectDiagnose,
  type AIAnalyzeModelResponse,
  type AIDefectDiagnoseResponse,
  type AISupportOrientResponse,
  type AdhesionType,
  type ExtruderSlotConfig,
  type FullProjectSummary,
  type LayerPauseItem,
  type MachineMaterialLearningsResponse,
  type MaterialType,
  type MeshAnalysisResponse,
  type ModelInstanceTransform,
  type NozzleDiameter,
  type ObjectPrintOverrides,
  type PrinterId,
  type PrinterInfo,
  type ProfileId,
  type SavedProjectRecord,
  type QualityPreset,
  type SceneObjectTransform,
  type SliceResponse,
  type SlicedProfileSnapshot,
  type SupportType,
  type ZColorRange,
} from '../services/api';

interface MaterialDefaults {
  label: string;
  nozzleInitial: number;
  nozzle: number;
  bed: number;
  recMin: number;
  recMax: number;
  nozzleMin: number;
  nozzleMax: number;
  bedMin: number;
  bedMax: number;
  defaultSupportZ: number;
  defaultSupportXY: number;
  hint: string;
}

export const MATERIAL_DEFAULTS: Record<MaterialType, MaterialDefaults> = {
  pla: {
    label: 'PLA',
    nozzleInitial: 220,
    nozzle: 210,
    bed: 60,
    recMin: 190,
    recMax: 225,
    nozzleMin: 185,
    nozzleMax: 245,
    bedMin: 35,
    bedMax: 75,
    defaultSupportZ: 0.20,
    defaultSupportXY: 0.50,
    hint: 'Carrete 190–225 °C · Ventilación 100%, Z = 0.20 mm · XY = 0.50 mm.',
  },
  petg: {
    label: 'PETG',
    nozzleInitial: 250,
    nozzle: 242,
    bed: 80,
    recMin: 230,
    recMax: 255,
    nozzleMin: 225,
    nozzleMax: 265,
    bedMin: 65,
    bedMax: 90,
    defaultSupportZ: 0.30,
    defaultSupportXY: 0.60,
    hint: 'Carrete 230–255 °C · Z = 0.30 mm · XY = 0.60 mm (1.5× boquilla) anti-soldadura.',
  },
  abs: {
    label: 'ABS',
    nozzleInitial: 260,
    nozzle: 255,
    bed: 100,
    recMin: 240,
    recMax: 270,
    nozzleMin: 235,
    nozzleMax: 285,
    bedMin: 90,
    bedMax: 115,
    defaultSupportZ: 0.24,
    defaultSupportXY: 0.55,
    hint: 'Carrete 240–270 °C · Cámara cerrada recomendada, Z = 0.24 mm · XY = 0.55 mm.',
  },
  tpu: {
    label: 'TPU 95A',
    nozzleInitial: 228,
    nozzle: 222,
    bed: 50,
    recMin: 210,
    recMax: 235,
    nozzleMin: 205,
    nozzleMax: 245,
    bedMin: 30,
    bedMax: 65,
    defaultSupportZ: 0.28,
    defaultSupportXY: 0.60,
    hint: 'Carrete 210–235 °C · Caudal controlado, Z = 0.28 mm · XY = 0.60 mm.',
  },
};

export function computeDefaultSupportXY(
  material: MaterialType,
  nozzleDiameter: NozzleDiameter,
): number {
  const base = MATERIAL_DEFAULTS[material].defaultSupportXY;
  return Math.round(Math.max(0.25, base * (nozzleDiameter / 0.4)) * 100) / 100;
}

export function computeAutoTemperatures(
  printerOrProfileId: ProfileId | PrinterId,
  material: MaterialType,
  spoolMin: number,
  spoolMax: number,
  highSpeed: boolean,
  nozzleDiameter: NozzleDiameter,
): { nozzleInitial: number; nozzleNormal: number; bed: number } {
  const meta = MATERIAL_DEFAULTS[material];
  const lo = Math.min(spoolMin, spoolMax - 5);
  const hi = Math.max(spoolMax, lo + 5);
  const span = hi - lo;

  const isHighFlow =
    printerOrProfileId === 'flsun_t1_pro' ||
    printerOrProfileId.startsWith('flsun_t1_pro_') ||
    printerOrProfileId === 'flsun_v400' ||
    printerOrProfileId.startsWith('flsun_v400_');
  const isConservative =
    printerOrProfileId === 'ender3_s1_pro' ||
    printerOrProfileId.startsWith('ender3_s1_pro_') ||
    printerOrProfileId === 'flsun_sr' ||
    printerOrProfileId.startsWith('flsun_sr_');

  let ratioPrint = 0.65;
  let ratioInit = 0.85;
  if (isHighFlow || highSpeed) {
    ratioPrint = 0.8;
    ratioInit = 0.97;
  } else if (isConservative) {
    ratioPrint = 0.55;
    ratioInit = 0.75;
  }

  const nozzleDelta =
    nozzleDiameter >= 0.6 ? 3 : nozzleDiameter <= 0.2 ? -3 : 0;
  const nozzleNormal = Math.max(
    lo,
    Math.min(hi, Math.round(lo + span * ratioPrint) + nozzleDelta),
  );
  const nozzleInitial = Math.max(
    nozzleNormal,
    Math.min(hi, Math.round(lo + span * ratioInit) + nozzleDelta),
  );
  return {
    nozzleInitial,
    nozzleNormal,
    bed: meta.bed,
  };
}

export const SLOT_FALLBACK_FLOW_STD: Record<ExtruderSlotConfig['material'], number> = {
  pla: 32,
  petg: 18,
  abs: 24,
  tpu: 10,
  soporte: 24,
};

export const SLOT_FALLBACK_FLOW_HS: Record<ExtruderSlotConfig['material'], number> = {
  pla: 38,
  petg: 24,
  abs: 30,
  tpu: 13,
  soporte: 30,
};

export function getSlotSpoolDefaults(mat: ExtruderSlotConfig['material']): {
  min: number;
  max: number;
} {
  if (mat === 'soporte') return { min: 190, max: 220 };
  const m = MATERIAL_DEFAULTS[mat];
  return { min: m.recMin, max: m.recMax };
}

export function getSlotVolumetricSpeed(
  mat: ExtruderSlotConfig['material'],
  highSpeed: boolean,
  volumetricLimits: Record<string, Record<string, number>>,
  highSpeedVolumetricLimits: Record<string, Record<string, number>>,
  profileId: ProfileId,
): number {
  const effMat: MaterialType = mat === 'soporte' ? 'pla' : mat;
  const masterKey = `${effMat}_master`;
  const table = highSpeed ? highSpeedVolumetricLimits : volumetricLimits;
  const fromCatalog = table[masterKey]?.[profileId];
  if (typeof fromCatalog === 'number' && fromCatalog > 0) {
    return fromCatalog;
  }
  return highSpeed ? SLOT_FALLBACK_FLOW_HS[mat] : SLOT_FALLBACK_FLOW_STD[mat];
}

export function computeSlotThermalConfig(
  slot: ExtruderSlotConfig,
  profileId: ProfileId,
  nozzleDiameter: NozzleDiameter,
  volumetricLimits: Record<string, Record<string, number>>,
  highSpeedVolumetricLimits: Record<string, Record<string, number>>,
): {
  spoolMin: number;
  spoolMax: number;
  nozzleInitial: number;
  nozzleNormal: number;
  maxVolFlow: number;
} {
  const defs = getSlotSpoolDefaults(slot.material);
  const spoolMin = typeof slot.spool_min === 'number' ? slot.spool_min : defs.min;
  const spoolMax = typeof slot.spool_max === 'number' ? slot.spool_max : defs.max;
  const effMat: MaterialType = slot.material === 'soporte' ? 'pla' : slot.material;
  const temps = computeAutoTemperatures(
    profileId,
    effMat,
    spoolMin,
    spoolMax,
    Boolean(slot.high_speed),
    nozzleDiameter,
  );
  const maxVolFlow = getSlotVolumetricSpeed(
    slot.material,
    Boolean(slot.high_speed),
    volumetricLimits,
    highSpeedVolumetricLimits,
    profileId,
  );
  return {
    spoolMin,
    spoolMax,
    nozzleInitial: temps.nozzleInitial,
    nozzleNormal: temps.nozzleNormal,
    maxVolFlow,
  };
}

export function negotiateMultiMaterialBedTemp(
  materials: ExtruderSlotConfig['material'][],
): number {
  const body = new Set(materials.filter((m) => m !== 'soporte'));
  if (body.size === 0) return 60;
  if (body.size === 1) {
    const only = Array.from(body)[0] as MaterialType;
    return MATERIAL_DEFAULTS[only].bed;
  }
  if (body.has('abs')) {
    return body.has('pla') || body.has('tpu') ? 90 : 95;
  }
  if (body.has('petg') && (body.has('pla') || body.has('tpu'))) return 65;
  if (body.has('pla') && body.has('tpu')) return 58;
  return 65;
}

export interface ChamberConfigSummary {
  targetTemp: number;
  maxSafeTemp: number;
  mode: 'extraction' | 'recirculation' | 'preheat_closed';
  modeLabel: string;
}

export function getOptimalChamberConfig(
  activeMaterials: string[],
): ChamberConfigSummary {
  const norm = new Set(
    activeMaterials
      .map((m) => m.trim().toLowerCase())
      .filter((m) => m && m !== 'soporte'),
  );
  if (norm.has('pla') || norm.has('tpu')) {
    return {
      targetTemp: 30,
      maxSafeTemp: 35,
      mode: 'extraction',
      modeLabel: norm.has('tpu') ? 'Extracción PLA/TPU' : 'Extracción PLA',
    };
  }
  if (norm.has('abs') || norm.has('asa')) {
    return {
      targetTemp: 50,
      maxSafeTemp: 55,
      mode: 'preheat_closed',
      modeLabel: norm.has('asa') ? 'Precalentamiento ABS/ASA' : 'Precalentamiento ABS',
    };
  }
  return {
    targetTemp: 40,
    maxSafeTemp: 45,
    mode: 'recirculation',
    modeLabel: 'Recirculación PETG',
  };
}

export function computeHeterogeneousSummary(
  slots: ExtruderSlotConfig[],
  nozzleDiameter: NozzleDiameter,
  volumetricLimits: Record<string, Record<string, number>>,
  highSpeedVolumetricLimits: Record<string, Record<string, number>>,
  profileId: ProfileId,
): {
  negotiatedBedTemp: number;
  minFlow: number;
  bottleneckSlotIdx: number;
  maxLinearSpeed: number;
  hasIncompatibleBodyMix: boolean;
  incompatibleNote: string | null;
} {
  const negotiatedBedTemp = negotiateMultiMaterialBedTemp(
    slots.map((s) => s.material),
  );
  let minFlow = Infinity;
  let bottleneckSlotIdx = 0;
  for (const s of slots) {
    const flow =
      typeof s.max_volumetric_speed === 'number' && s.max_volumetric_speed > 0
        ? s.max_volumetric_speed
        : getSlotVolumetricSpeed(
            s.material,
            Boolean(s.high_speed),
            volumetricLimits,
            highSpeedVolumetricLimits,
            profileId,
          );
    if (flow < minFlow) {
      minFlow = flow;
      bottleneckSlotIdx = s.extruder_index;
    }
  }
  if (!Number.isFinite(minFlow)) minFlow = 18;
  const crossSection = (nozzleDiameter * 1.1) * (nozzleDiameter * 0.5);
  let maxLinearSpeed = Math.round(minFlow / Math.max(0.02, crossSection));
  if (slots.some((s) => s.material === 'tpu')) {
    maxLinearSpeed = Math.min(maxLinearSpeed, 80);
  }
  maxLinearSpeed = Math.max(25, maxLinearSpeed);

  const bodyMats = new Set(
    slots.filter((s) => s.material !== 'soporte').map((s) => s.material),
  );
  let hasIncompatibleBodyMix = false;
  let incompatibleNote: string | null = null;
  if (bodyMats.has('pla') && (bodyMats.has('petg') || bodyMats.has('abs'))) {
    hasIncompatibleBodyMix = true;
    incompatibleNote =
      'Compatibilidad: PLA y PETG/ABS no se sueldan bien entre capas en el cuerpo de la pieza (úsalos solo si uno actúa como soporte separable).';
  }
  return {
    negotiatedBedTemp,
    minFlow,
    bottleneckSlotIdx,
    maxLinearSpeed,
    hasIncompatibleBodyMix,
    incompatibleNote,
  };
}

const NOZZLE_OPTIONS: NozzleDiameter[] = [0.2, 0.4, 0.6, 0.8];

function formatFileSize(bytes: number): string {
  if (bytes >= 1024 * 1024) {
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }
  return `${(bytes / 1024).toFixed(1)} KB`;
}

function parseEstimatedHours(estimatedTime: string): number {
  let hours = 0;
  const d = /(\d+(?:\.\d+)?)\s*d/i.exec(estimatedTime);
  const h = /(\d+(?:\.\d+)?)\s*h/i.exec(estimatedTime);
  const m = /(\d+(?:\.\d+)?)\s*m/i.exec(estimatedTime);
  const s = /(\d+(?:\.\d+)?)\s*s/i.exec(estimatedTime);
  if (d) hours += parseFloat(d[1]) * 24;
  if (h) hours += parseFloat(h[1]);
  if (m) hours += parseFloat(m[1]) / 60;
  if (s) hours += parseFloat(s[1]) / 3600;
  return hours;
}

function formatPesos(amount: number): string {
  const safe = Number.isFinite(amount) ? Math.max(0, Math.round(amount)) : 0;
  return `$${safe.toLocaleString('en-US')}`;
}

interface CostSettings {
  spoolWeightGrams: number;
  spoolCostPesos: number;
  energyCostPerHour: number;
}

const DEFAULT_COSTS: CostSettings = {
  spoolWeightGrams: 1000,
  spoolCostPesos: 100000,
  energyCostPerHour: 2000,
};

function loadSavedCosts(): CostSettings {
  try {
    const raw = window.localStorage.getItem('slicerhub_costs_v1');
    if (!raw) return DEFAULT_COSTS;
    const parsed = JSON.parse(raw) as Partial<CostSettings>;
    return {
      spoolWeightGrams:
        typeof parsed.spoolWeightGrams === 'number' && parsed.spoolWeightGrams > 0
          ? parsed.spoolWeightGrams
          : DEFAULT_COSTS.spoolWeightGrams,
      spoolCostPesos:
        typeof parsed.spoolCostPesos === 'number' && parsed.spoolCostPesos >= 0
          ? parsed.spoolCostPesos
          : DEFAULT_COSTS.spoolCostPesos,
      energyCostPerHour:
        typeof parsed.energyCostPerHour === 'number' && parsed.energyCostPerHour >= 0
          ? parsed.energyCostPerHour
          : DEFAULT_COSTS.energyCostPerHour,
    };
  } catch {
    return DEFAULT_COSTS;
  }
}

interface SlicerWizardProps {
  printers: PrinterInfo[];
  volumetricLimits: Record<string, Record<string, number>>;
  highSpeedVolumetricLimits: Record<string, Record<string, number>>;
  selectedPrinterId: PrinterId;
  onSelectPrinter: (id: PrinterId) => void;
  onOpenAddPrinter?: () => void;
  onDeletePrinter?: (id: PrinterId) => void;
  stlFile: File | null;
  onSelectStl: (file: File) => void;
  analysis: MeshAnalysisResponse | null;
  isAnalyzing: boolean;
  material: MaterialType;
  onChangeMaterial: (m: MaterialType) => void;
  nozzleDiameter: NozzleDiameter;
  onChangeNozzleDiameter: (d: NozzleDiameter) => void;
  highSpeedFilament: boolean;
  onToggleHighSpeedFilament: (v: boolean) => void;
  lithophaneMode: boolean;
  onToggleLithophaneMode: (v: boolean) => void;
  spoolMinTemp: number;
  onChangeSpoolMinTemp: (t: number) => void;
  spoolMaxTemp: number;
  onChangeSpoolMaxTemp: (t: number) => void;
  nozzleTempInitial: number;
  onChangeNozzleTempInitial: (t: number) => void;
  nozzleTemp: number;
  onChangeNozzleTemp: (t: number) => void;
  bedTemp: number;
  onChangeBedTemp: (t: number) => void;
  supports: boolean;
  onToggleSupports: (v: boolean) => void;
  supportType: SupportType;
  onChangeSupportType: (t: SupportType) => void;
  supportStyle?: string;
  onChangeSupportStyle?: (s: string) => void;
  supportOnBuildPlateOnly: boolean;
  onChangeSupportOnBuildPlateOnly: (v: boolean) => void;
  supportZDistance: number;
  onChangeSupportZDistance: (z: number) => void;
  supportXyDistance: number;
  onChangeSupportXyDistance: (xy: number) => void;
  adhesionType: AdhesionType;
  onChangeAdhesionType: (a: AdhesionType) => void;
  brimWidthMm: number;
  onChangeBrimWidthMm: (w: number) => void;
  adhesionLabel: string | null;
  primeTowerEnabled: boolean;
  onTogglePrimeTower: (enabled: boolean) => void;
  primeTowerReason: string | null;
  primeTowerBrimWidthMm?: number | null;
  onChangePrimeTowerBrimWidthMm?: (w: number | null) => void;
  qualityPreset: QualityPreset;
  onChangePreset: (p: QualityPreset) => void;
  specializedProfileId:
    | 'none'
    | 'detalle_fino'
    | 'detalle_optimo'
    | 'piel_difusa'
    | 'rapido_funcional'
    | 'litofania_hd'
    | 'litofania_ultra'
    | 'litofania_vertical';
  onSelectDynamicProfile: (
    id:
      | QualityPreset
      | 'detalle_fino'
      | 'detalle_optimo'
      | 'piel_difusa'
      | 'rapido_funcional'
      | 'litofania_hd'
      | 'litofania_ultra'
      | 'litofania_vertical',
    speedHintMmS?: number,
    layerHeightHintMm?: number,
  ) => void;
  isOptimizingAI: boolean;
  aiReasoning: string | null;
  aiProvider: string | null;
  onAISupportOrient: () => void;
  isOptimizingSupportAI: boolean;
  aiSupportStatus: AISupportOrientResponse | null;
  onAnalyzeModelAI: () => void;
  isAnalyzingAI: boolean;
  aiAnalysisResult: AIAnalyzeModelResponse | null;
  aiQualityOverrides?: string[];
  onToggleAiQualityOverride?: (id: string) => void;
  onClearAiQualityOverrides?: () => void;
  onOptimizeSliceWithAI: (presetId: string, userNotes?: string, targetLayerHeight?: number) => void;
  isOptimizingSliceAI: boolean;
  aiOptimizeComparison: {
    strategyLabel: string;
    explanation: string;
    before: { time: string; grams: number; supportGrams: number; rot: string };
    after: {
      time: string;
      grams: number;
      supportGrams: number;
      rot: string;
      layerHeight: number;
      fuzzySkin: boolean;
    };
  } | null;
  canRollbackInitialSlice: boolean;
  onRollbackToInitialSlice: () => void;
  onRollbackToUnsliced: () => void;
  savedProjects: SavedProjectRecord[];
  isLoadingProjects: boolean;
  onRefreshSavedProjects: () => void;
  onLoadSavedProject: (proj: SavedProjectRecord) => void;
  onApplyDefectCorrection: (proj: SavedProjectRecord, corrected: Record<string, unknown>) => void;
  onSlice: () => void;
  onCancelSlice?: () => void;
  isSlicing: boolean;
  sliceResult: SliceResponse | null;
  slicedProfileSnapshot?: SlicedProfileSnapshot | null;
  infillDensityOverride?: number | null;
  onChangeInfillDensityOverride?: (val: number | null) => void;
  profileDrawerOpen?: boolean;
  onSetProfileDrawerOpen?: (open: boolean) => void;
  onApplyProfileAndReslice?: (overrides: Record<string, unknown>) => Promise<void> | void;
  errorMsg: string | null;
  detectedVolumes: string[];
  configuredSdVolume: string;
  enableTimelapse: boolean;
  onToggleEnableTimelapse: (enabled: boolean) => void;
  autoLeveling: boolean;
  onToggleAutoLeveling: (enabled: boolean) => void;
  onSendToPrinter: (
    mode: 'network' | 'usb_serial' | 'sd_volume',
    sdPath?: string,
    startPrint?: boolean,
    overrideAutoLeveling?: boolean,
    customFilename?: string,
  ) => void;
  uploadActionMode: 'upload_only' | 'upload_and_print' | null;
  sendPrintMsg: string | null;
  extrudersConfig: ExtruderSlotConfig[];
  onChangeExtrudersConfig: (next: ExtruderSlotConfig[]) => void;
  modelExtruder: number;
  onChangeModelExtruder: (idx: number) => void;
  supportExtruder: number;
  onChangeSupportExtruder: (idx: number) => void;
  zColorRanges: ZColorRange[];
  onChangeZColorRanges: (next: ZColorRange[]) => void;
  partExtruderMap: Record<string, number>;
  onChangePartExtruderMap: (next: Record<string, number>) => void;
  chamberTempTarget: number | null;
  onChangeChamberTempTarget: (next: number | null) => void;
  layerPauses: LayerPauseItem[];
  onAddLayerPause: (layer: number, zMm: number | null, note: string) => void;
  onRemoveLayerPause: (layer: number) => void;
  recentProjects?: FullProjectSummary[];
  onLoadFullProject?: (projectId: string) => void;
  onOpenProjectNewWindow?: (projectId: string) => void;
  onDeleteFullProject?: (projectId: string) => void;
  externalProjectsOpen?: boolean;
  onChangeExternalProjectsOpen?: (open: boolean) => void;
  sceneObjects?: SceneObjectTransform[];
  selectedObjectIds?: string[];
  onSelectObjects?: (ids: string[]) => void;
  onChangeSceneObjects?: (next: SceneObjectTransform[]) => void;
  instances?: ModelInstanceTransform[];
  onChangeInstances?: (next: ModelInstanceTransform[]) => void;
}

const COLOR_PRESETS: Array<{ name: string; hex: string }> = [
  { name: 'Negro', hex: '#1E1E1E' },
  { name: 'Blanco', hex: '#F8FAFC' },
  { name: 'Gris', hex: '#94A3B8' },
  { name: 'Rojo', hex: '#EF4444' },
  { name: 'Naranja', hex: '#F97316' },
  { name: 'Amarillo', hex: '#EAB308' },
  { name: 'Verde', hex: '#22C55E' },
  { name: 'Cian', hex: '#06B6D4' },
  { name: 'Azul', hex: '#3B82F6' },
  { name: 'Morado', hex: '#A855F7' },
  { name: 'Café', hex: '#92400E' },
  { name: 'Piel', hex: '#FDBA74' },
];

const LITHOPHANE_OUTER_SPEEDS: Record<ProfileId, { std: number; hs: number }> = {
  flsun_t1_pro: { std: 65, hs: 75 },
  flsun_v400: { std: 55, hs: 65 },
  flsun_sr: { std: 42, hs: 50 },
  creator5_pro: { std: 60, hs: 70 },
  ender3_s1_pro: { std: 32, hs: 38 },
};

export function SlicerWizard({
  printers,
  volumetricLimits,
  highSpeedVolumetricLimits,
  selectedPrinterId,
  onSelectPrinter,
  onOpenAddPrinter,
  onDeletePrinter,
  stlFile,
  onSelectStl,
  analysis,
  isAnalyzing,
  material,
  onChangeMaterial,
  nozzleDiameter,
  onChangeNozzleDiameter,
  highSpeedFilament,
  onToggleHighSpeedFilament,
  lithophaneMode,
  onToggleLithophaneMode,
  spoolMinTemp,
  onChangeSpoolMinTemp,
  spoolMaxTemp,
  onChangeSpoolMaxTemp,
  nozzleTempInitial,
  onChangeNozzleTempInitial,
  nozzleTemp,
  onChangeNozzleTemp,
  bedTemp,
  onChangeBedTemp,
  supports,
  onToggleSupports,
  supportType,
  onChangeSupportType,
  supportStyle = 'default',
  onChangeSupportStyle,
  supportOnBuildPlateOnly,
  onChangeSupportOnBuildPlateOnly,
  supportZDistance,
  onChangeSupportZDistance,
  supportXyDistance,
  onChangeSupportXyDistance,
  adhesionType,
  onChangeAdhesionType,
  brimWidthMm,
  onChangeBrimWidthMm,
  adhesionLabel,
  primeTowerEnabled,
  onTogglePrimeTower,
  primeTowerReason,
  primeTowerBrimWidthMm = null,
  onChangePrimeTowerBrimWidthMm,
  qualityPreset,
  onChangePreset: _onChangePreset,
  specializedProfileId,
  onSelectDynamicProfile,
  isOptimizingAI,
  aiReasoning,
  aiProvider,
  aiSupportStatus,
  onAnalyzeModelAI,
  isAnalyzingAI,
  aiAnalysisResult,
  aiQualityOverrides = [],
  onToggleAiQualityOverride,
  onClearAiQualityOverrides,
  onOptimizeSliceWithAI,
  isOptimizingSliceAI,
  aiOptimizeComparison,
  canRollbackInitialSlice,
  onRollbackToInitialSlice,
  onRollbackToUnsliced,
  savedProjects,
  isLoadingProjects,
  onRefreshSavedProjects,
  onLoadSavedProject,
  onApplyDefectCorrection,
  onSlice,
  onCancelSlice,
  isSlicing,
  sliceResult,
  slicedProfileSnapshot,
  infillDensityOverride = null,
  onChangeInfillDensityOverride,
  profileDrawerOpen: controlledProfileOpen,
  onSetProfileDrawerOpen,
  onApplyProfileAndReslice,
  errorMsg,
  detectedVolumes,
  configuredSdVolume,
  enableTimelapse,
  onToggleEnableTimelapse,
  autoLeveling,
  onToggleAutoLeveling,
  onSendToPrinter,
  uploadActionMode,
  sendPrintMsg,
  extrudersConfig,
  onChangeExtrudersConfig,
  modelExtruder,
  onChangeModelExtruder,
  supportExtruder,
  onChangeSupportExtruder,
  zColorRanges,
  onChangeZColorRanges,
  partExtruderMap,
  onChangePartExtruderMap,
  chamberTempTarget,
  onChangeChamberTempTarget,
  layerPauses,
  onAddLayerPause,
  onRemoveLayerPause,
  recentProjects = [],
  onLoadFullProject,
  onOpenProjectNewWindow,
  onDeleteFullProject,
  externalProjectsOpen = false,
  onChangeExternalProjectsOpen,
  sceneObjects = [],
  selectedObjectIds = [],
  onSelectObjects,
  onChangeSceneObjects,
  instances = [],
  onChangeInstances,
}: SlicerWizardProps) {
  const { t } = useI18n();
  const [supportScope, setSupportScope] = useState<'global' | 'per_part'>('global');
  const [adhesionScope, setAdhesionScope] = useState<'global' | 'per_part'>('global');
  const [isDragging, setIsDragging] = useState(false);
  const [pauseLayerInput, setPauseLayerInput] = useState('10');
  const [pauseNoteInput, setPauseNoteInput] = useState('');
  const [showManualTemps, setShowManualTemps] = useState(false);
  const [costs] = useState<CostSettings>(loadSavedCosts);
  const [enderMode, setEnderMode] = useState<'sd_volume' | 'usb_serial'>('sd_volume');
  const [selectedSdPath, setSelectedSdPath] = useState<string>('');
  const [pendingOutputAction, setPendingOutputAction] = useState<
    'download' | 'upload_only' | 'upload_and_print' | null
  >(null);
  const [downloadFormat, setDownloadFormat] = useState<'gcode.3mf' | 'gcode'>('gcode.3mf');
  const [customBaseName, setCustomBaseName] = useState<string>('');
  const [learnings, setLearnings] = useState<MachineMaterialLearningsResponse | null>(null);
  const [learningsOpen, setLearningsOpen] = useState(false);
  const [draftSpoolRanges, setDraftSpoolRanges] = useState<
    Record<number, { min: string; max: string }>
  >({});
  const [aiUserNotes, setAiUserNotes] = useState('');
  const [projectsModalOpen, setProjectsModalOpen] = useState(false);
  const [projectsModalTab, setProjectsModalTab] = useState<'saved' | 'diagnostics'>('saved');
  const [visibleRecentLimit, setVisibleRecentLimit] = useState(10);

  useEffect(() => {
    if (projectsModalOpen) {
      setVisibleRecentLimit(10);
    }
  }, [projectsModalOpen]);

  useEffect(() => {
    if (externalProjectsOpen) {
      setProjectsModalTab('saved');
      setProjectsModalOpen(true);
      onRefreshSavedProjects();
    }
  }, [externalProjectsOpen]);
  const [quoteModalOpen, setQuoteModalOpen] = useState(false);
  const [internalProfileDrawerOpen, setInternalProfileDrawerOpen] = useState(false);
  const profileDrawerOpen = controlledProfileOpen ?? internalProfileDrawerOpen;
  const setProfileDrawerOpen = (next: boolean) => {
    setInternalProfileDrawerOpen(next);
    onSetProfileDrawerOpen?.(next);
  };
  const effectiveProfileSnapshot = sliceResult?.sliced_profile_snapshot ?? slicedProfileSnapshot ?? null;
  const [defectTargetProj, setDefectTargetProj] = useState<SavedProjectRecord | null>(null);
  const [defectText, setDefectText] = useState('');
  const [isDiagnosingDefect, setIsDiagnosingDefect] = useState(false);
  const [defectResult, setDefectResult] = useState<AIDefectDiagnoseResponse | null>(null);
  const [isAiPresetsExpanded, setIsAiPresetsExpanded] = useState(true);
  const [expandedLayerHeight, setExpandedLayerHeight] = useState<number | null>(null);
  const [showAllResolutions, setShowAllResolutions] = useState(false);
  const [sliderLayerHeight, setSliderLayerHeight] = useState<number>(0.20);
  const [isStep4Expanded, setIsStep4Expanded] = useState(true);
  const [instantOverlayMode, setInstantOverlayMode] = useState<ProcessingOverlayMode | null>(null);
  const [lastOverlayMode, setLastOverlayMode] = useState<ProcessingOverlayMode>('slicing');
  const aiResultRef = useRef<HTMLDivElement | null>(null);

  const rawOverlayMode: ProcessingOverlayMode | null =
    isOptimizingSliceAI
      ? 'ai_optimize'
      : isAnalyzingAI || isDiagnosingDefect
        ? 'ai_analyze'
        : isSlicing
          ? 'slicing'
          : uploadActionMode === 'upload_only'
            ? 'upload_only'
            : uploadActionMode === 'upload_and_print'
              ? 'upload_and_print'
              : instantOverlayMode;
  const overlayActive = rawOverlayMode !== null;

  useEffect(() => {
    if (rawOverlayMode) {
      setLastOverlayMode(rawOverlayMode);
    }
  }, [rawOverlayMode]);

  useEffect(() => {
    if (!instantOverlayMode) return;
    const raf = window.requestAnimationFrame(() => {
      setInstantOverlayMode(null);
    });
    return () => window.cancelAnimationFrame(raf);
  }, [instantOverlayMode, isSlicing, isAnalyzingAI, isOptimizingSliceAI, isDiagnosingDefect]);

  useEffect(() => {
    if (lithophaneMode && sliderLayerHeight > 0.12) {
      setSliderLayerHeight(0.12);
    }
  }, [lithophaneMode, sliderLayerHeight]);

  useEffect(() => {
    if (aiAnalysisResult && !aiOptimizeComparison) {
      setIsAiPresetsExpanded(true);
      setShowAllResolutions(false);
      const firstRec = aiAnalysisResult.layer_resolutions?.find((g) => g.is_recommended);
      setExpandedLayerHeight(
        firstRec ? firstRec.layer_height : (aiAnalysisResult.layer_resolutions?.[0]?.layer_height ?? null),
      );
    }
  }, [aiAnalysisResult, aiOptimizeComparison]);

  useEffect(() => {
    if (aiOptimizeComparison) {
      setIsAiPresetsExpanded(false);
      window.setTimeout(() => {
        aiResultRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }, 60);
    }
  }, [aiOptimizeComparison]);

  useEffect(() => {
    setDraftSpoolRanges({});
  }, [extrudersConfig]);

  useEffect(() => {
    let cancelled = false;
    const effMat = lithophaneMode ? 'pla' : material;
    fetchTelemetryLearnings(selectedPrinterId, effMat, 3)
      .then((res) => {
        if (!cancelled) {
          setLearnings(res);
          setLearningsOpen(false);
        }
      })
      .catch(() => {
        if (!cancelled) setLearnings(null);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPrinterId, material, lithophaneMode]);

  useEffect(() => {
    try {
      window.localStorage.setItem('slicerhub_costs_v1', JSON.stringify(costs));
    } catch {
      // Ignorar errores de cuota de almacenamiento local
    }
  }, [costs]);

  const effectiveSdPath =
    selectedSdPath || configuredSdVolume || detectedVolumes[0] || '';

  const sliderMin = Math.min(spoolMinTemp, spoolMaxTemp - 5);
  const sliderMax = Math.max(spoolMaxTemp, sliderMin + 5);
  const clampedInitialTemp = Math.min(sliderMax, Math.max(sliderMin, nozzleTempInitial));
  const clampedNormalTemp = Math.min(sliderMax, Math.max(sliderMin, nozzleTemp));

  const [workshopPreset, setWorkshopPreset] = useState<WorkshopPreset>(() => loadWorkshopPreset());

  useEffect(() => {
    const onPresetUpdated = () => setWorkshopPreset(loadWorkshopPreset());
    window.addEventListener('nikk:quote-preset-updated', onPresetUpdated);
    return () => window.removeEventListener('nikk:quote-preset-updated', onPresetUpdated);
  }, []);

  const selectedPrinter = printers.find((p) => p.printer_id === selectedPrinterId);
  const selectedProfileId: ProfileId =
    selectedPrinter?.profile_id ?? (selectedPrinterId as ProfileId);
  const isMulticolorPrinter = Boolean(
    selectedPrinter?.is_multicolor ||
      (selectedPrinter?.extruder_slots ?? 1) > 1 ||
      selectedProfileId === 'creator5_pro',
  );

  const estHours = sliceResult
    ? sliceResult.estimated_time_seconds && sliceResult.estimated_time_seconds > 0
      ? sliceResult.estimated_time_seconds / 3600
      : parseEstimatedHours(sliceResult.estimated_time)
    : 0;
  const activePrinterWatts = PRINTER_WATTS[selectedProfileId]?.watts ?? 150;
  const materialCost = sliceResult
    ? (sliceResult.filament_grams / 1000) * workshopPreset.filamentPricePerKg
    : 0;
  const energyCost = sliceResult
    ? (activePrinterWatts / 1000) * estHours * workshopPreset.energyRateKwh
    : 0;
  const totalCost = materialCost + energyCost;

  const matMeta = MATERIAL_DEFAULTS[material];
  const matKey = `${material}_master`;

  useEffect(() => {
    if (!sliceResult) {
      setPendingOutputAction(null);
      return;
    }
    const rawModel = (stlFile?.name || 'modelo')
      .replace(/\.(stl|3mf|gcode)$/i, '')
      .replace(/[^A-Za-z0-9_-]+/g, '_')
      .replace(/^_+|_+$/g, '');
    const shortMach =
      selectedProfileId === 'flsun_t1_pro'
        ? 'T1Pro'
        : selectedProfileId === 'flsun_v400'
          ? 'V400'
          : selectedProfileId === 'creator5_pro'
            ? 'C5Pro'
            : selectedProfileId === 'flsun_sr'
              ? 'SR'
              : 'Ender3S1';
    setCustomBaseName(`${rawModel || 'modelo'}_${material.toUpperCase()}_${shortMach}`);
  }, [sliceResult?.job_id, stlFile?.name, material, selectedProfileId]);
  const standardLimit =
    volumetricLimits[matKey]?.[selectedProfileId] ??
    selectedPrinter?.max_volumetric_flow_mm3_s ??
    15;
  const hsLimit =
    highSpeedVolumetricLimits[matKey]?.[selectedProfileId] ??
    Math.round(standardLimit * 1.25);
  const activeFlowLimit = highSpeedFilament ? hsLimit : standardLimit;
  const effSupportMatKey: MaterialType =
    selectedProfileId === 'creator5_pro' &&
    extrudersConfig[supportExtruder]?.material &&
    extrudersConfig[supportExtruder].material !== 'soporte' &&
    extrudersConfig[supportExtruder].material in MATERIAL_DEFAULTS
      ? (extrudersConfig[supportExtruder].material as MaterialType)
      : material;
  const recommendedSupportZ =
    selectedProfileId === 'creator5_pro' &&
    extrudersConfig[supportExtruder]?.material === 'soporte'
      ? 0.15
      : MATERIAL_DEFAULTS[effSupportMatKey].defaultSupportZ;
  const recommendedSupportXY = computeDefaultSupportXY(effSupportMatKey, nozzleDiameter);

  const sliderScaleInfo = useMemo(() => {
    const h = Number(sliderLayerHeight.toFixed(2));
    if (h <= 0.08) return { title: 'Ultra Detalle', sub: 'Miniaturas / Rostros · Tiempo alto' };
    if (h <= 0.12) return { title: 'Alta Calidad', sub: 'Figuras / Curvas suaves' };
    if (h <= 0.16) return { title: 'Detalle Óptimo', sub: 'Piezas visibles con buen acabado' };
    if (h <= 0.20) return { title: 'Estándar Equilibrado', sub: 'Uso general' };
    if (h <= 0.24) return { title: 'Rápido Funcional', sub: 'Ahorro de tiempo con buena cohesión' };
    return { title: 'Extra Rápido Blindado', sub: 'Piezas grandes · Seguro anti-delaminación' };
  }, [sliderLayerHeight]);

  const dynamicPresets = useMemo(() => {
    const shortMachine =
      selectedProfileId === 'flsun_t1_pro'
        ? 'T1 Pro'
        : selectedProfileId === 'flsun_v400'
          ? 'V400'
          : selectedProfileId === 'creator5_pro'
            ? 'Creator 5 Pro'
            : selectedProfileId === 'flsun_sr'
              ? 'Super Racer'
              : 'Ender 3 S1 Pro';

    let matTag = `${matMeta.label}${highSpeedFilament ? ' HS' : ''}`;
    let effFlowLimit = activeFlowLimit;
    let effTemp = clampedNormalTemp;

    if (selectedProfileId === 'creator5_pro' && extrudersConfig.length > 0) {
      const bodySlots = extrudersConfig.filter((s) => s.material !== 'soporte');
      const evalSlots = bodySlots.length > 0 ? bodySlots : extrudersConfig;
      const distinctMats = Array.from(
        new Set(evalSlots.map((s) => s.material.toUpperCase())),
      );
      const anyHs = evalSlots.some((s) => Boolean(s.high_speed));
      matTag = `${distinctMats.join('+') || matMeta.label}${anyHs ? ' HS' : ''}`;
      const slotFlows = extrudersConfig.map(
        (s) => s.max_volumetric_speed ?? activeFlowLimit,
      );
      if (slotFlows.length > 0) {
        effFlowLimit = Math.max(4, Math.min(...slotFlows));
      }
      effTemp = extrudersConfig[modelExtruder]?.nozzle_temp ?? clampedNormalTemp;
    }

    const machineCapMmS =
      selectedProfileId === 'flsun_t1_pro'
        ? 550
        : selectedProfileId === 'flsun_v400'
          ? 400
          : selectedProfileId === 'creator5_pro'
            ? 350
            : selectedProfileId === 'flsun_sr'
              ? 160
              : 120;
    const h = Number(sliderLayerHeight.toFixed(2));
    const lineW = h >= 0.24 && nozzleDiameter <= 0.45 ? 0.48 : nozzleDiameter * 1.05;
    const effQ = h >= 0.24 ? effFlowLimit * 0.90 : effFlowLimit;
    const calcSpeed = (lh: number, factor: number) => {
      const flowSpeed = Math.round((effQ / (lh * lineW)) * factor);
      return Math.max(35, Math.min(machineCapMmS, flowSpeed));
    };

    const lithoSpeed = Math.max(38, Math.min(60, calcSpeed(h, 0.32)));

    if (lithophaneMode) {
      return [
        {
          id: (h <= 0.08 ? 'litofania_ultra' : 'litofania_hd') as 'litofania_ultra' | 'litofania_hd',
          label: `${shortMachine} · PLA · Litofanía HD (${h.toFixed(2)} mm)`,
          desc: `${lithoSpeed} mm/s · ${effTemp}°C · 100% Rectilíneo · 5 paredes · Baja aceleración`,
          speedMmS: lithoSpeed,
          layerHeight: h,
          shielded: false,
        },
        {
          id: 'litofania_vertical' as const,
          label: `${shortMachine} · PLA · Litofanía Vertical Estable (${h.toFixed(2)} mm)`,
          desc: `${lithoSpeed} mm/s · ${effTemp}°C · 100% Rectilíneo · Brim 10 mm · Sin soportes`,
          speedMmS: lithoSpeed,
          layerHeight: h,
          shielded: false,
        },
      ];
    }

    const stdSpeed = calcSpeed(h, 0.88);
    const mechSpeed = calcSpeed(h, 0.72);
    const fuzzySpeed = calcSpeed(h, 0.76);
    const mechTemp = Math.min(300, effTemp + 5);
    const thickTemp = h >= 0.24 ? Math.min(300, effTemp + 6) : effTemp;
    const isThick = h >= 0.24;

    const cards: Array<{
      id: QualityPreset | 'piel_difusa' | 'litofania_hd';
      label: string;
      desc: string;
      speedMmS: number;
      layerHeight: number;
      shielded: boolean;
    }> = [
      {
        id: 'estandar',
        label: `${shortMachine} · ${matTag} · Estándar (${h.toFixed(2)} mm)`,
        desc: isThick
          ? `${stdSpeed} mm/s · ${thickTemp}°C (+6°C) · Ancho 0.48 mm · Q_max protegido · Gyroid 12%`
          : `${stdSpeed} mm/s · ${effTemp}°C · Z=${supportZDistance.toFixed(2)} · XY=${supportXyDistance.toFixed(2)}mm · Gyroid 12%`,
        speedMmS: stdSpeed,
        layerHeight: h,
        shielded: isThick,
      },
      {
        id: 'mecanico_resistente',
        label: `${shortMachine} · ${matTag} · Mecánico / Estructural (${h.toFixed(2)} mm)`,
        desc: `${mechSpeed} mm/s · ${mechTemp}°C (+5°C) · 4 paredes · Gyroid 25%`,
        speedMmS: mechSpeed,
        layerHeight: h,
        shielded: isThick,
      },
      {
        id: 'piel_difusa',
        label: `${shortMachine} · ${matTag} · Piel Difusa / Textura (${h.toFixed(2)} mm)`,
        desc: `${fuzzySpeed} mm/s · ${thickTemp}°C · Fuzzy Skin 0.15/0.40 mm · Gyroid 12%`,
        speedMmS: fuzzySpeed,
        layerHeight: h,
        shielded: isThick,
      },
    ];

    if (h <= 0.12) {
      cards.push({
        id: 'litofania_hd',
        label: `${shortMachine} · ${matTag} · Litofanía HD (${h.toFixed(2)} mm)`,
        desc: `${lithoSpeed} mm/s · ${effTemp}°C · 100% Rectilíneo · Anti-ringing`,
        speedMmS: lithoSpeed,
        layerHeight: h,
        shielded: false,
      });
    }

    return cards;
  }, [
    lithophaneMode,
    sliderLayerHeight,
    selectedProfileId,
    matMeta.label,
    highSpeedFilament,
    nozzleDiameter,
    activeFlowLimit,
    clampedNormalTemp,
    supportZDistance,
    supportXyDistance,
    extrudersConfig,
    modelExtruder,
  ]);

  const triggerFileDownload = async (rawUrl: string, suggestedFilename: string) => {
    const pyApi = (
      window as unknown as {
        pywebview?: {
          api?: {
            save_file?: (
              url: string,
              suggestedName: string,
            ) => Promise<{ saved?: boolean; cancelled?: boolean; path?: string }>;
          };
        };
      }
    ).pywebview?.api;

    if (pyApi?.save_file) {
      await pyApi.save_file(rawUrl, suggestedFilename);
      return;
    }

    const resp = await fetch(rawUrl);
    if (!resp.ok) throw new Error('No se pudo descargar el archivo.');
    const blob = await resp.blob();
    const objUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = objUrl;
    a.download = suggestedFilename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    window.setTimeout(() => URL.revokeObjectURL(objUrl), 5000);
  };

  const handleDrop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (
      dropped &&
      (dropped.name.toLowerCase().endsWith('.stl') ||
        dropped.name.toLowerCase().endsWith('.3mf'))
    ) {
      onSelectStl(dropped);
    }
  };

  const modelFileInputRef = useRef<HTMLInputElement | null>(null);
  const lastModelFileHandleRef = useRef<{ getFile: () => Promise<File> } | null>(null);

  const handlePickModelFile = async () => {
    const win = window as unknown as {
      showOpenFilePicker?: (opts?: Record<string, unknown>) => Promise<Array<{ getFile: () => Promise<File> }>>;
    };
    if (typeof win.showOpenFilePicker === 'function') {
      try {
        const [handle] = await win.showOpenFilePicker({
          id: 'nikk-slicer-model-import',
          multiple: false,
          startIn: lastModelFileHandleRef.current ?? 'downloads',
          types: [
            {
              description: 'Modelos 3D (.stl, .3mf)',
              accept: {
                'application/octet-stream': ['.stl', '.3mf'],
              },
            },
          ],
        });
        if (handle) {
          lastModelFileHandleRef.current = handle;
          const picked = await handle.getFile();
          onSelectStl(picked);
        }
        return;
      } catch (err) {
        if ((err as { name?: string })?.name === 'AbortError') return;
      }
    }
    modelFileInputRef.current?.click();
  };

  const handleFileInput = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (picked) onSelectStl(picked);
    e.target.value = '';
  };

  const isUsbOrSdPrinter =
    selectedPrinter?.protocol === 'marlin_serial' ||
    selectedProfileId === 'ender3_s1_pro' ||
    selectedProfileId === 'flsun_sr';

  const canSlice =
    Boolean(stlFile) &&
    !isAnalyzing &&
    !isSlicing &&
    (analysis ? analysis.fits_in_volume : true);

  return (
    <div className="flex h-full max-h-[calc(100vh-80px)] min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-950/60">
      {/* Área scrollable unificada con Pasos 1, 2, 3 y 4 */}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 pr-2">
        {/* PASO 1: Selector de impresora */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/75 p-3.5">
          <div className="mb-2.5 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500/20 text-[11px] font-bold text-cyan-300">
                1
              </span>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-200">
                Impresora
              </h2>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-slate-400">
                {printers.length} máquinas
              </span>
              {onOpenAddPrinter && (
                <button
                  type="button"
                  onClick={onOpenAddPrinter}
                  className="inline-flex items-center gap-1 rounded-lg border border-cyan-500/45 bg-cyan-500/15 px-2 py-1 text-[11px] font-semibold text-cyan-200 transition hover:bg-cyan-500/25"
                >
                  <Plus className="h-3 w-3" />
                  <span>Agregar Impresora</span>
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 gap-1.5">
            {printers.map((p) => {
              const active = p.printer_id === selectedPrinterId;
              const isDelta = p.kinematics === 'delta' || p.bed_shape === 'circular';
              const volLabel = isDelta
                ? `Ø${p.diameter_mm}×${p.height_mm} mm`
                : `${p.bed_mm?.join('×')} mm`;
              const kinLabel = isDelta
                ? `Delta ${p.gcode_flavor ? p.gcode_flavor.toUpperCase() : 'Klipper'}`
                : p.kinematics === 'corexy_toolchanger_4x' || p.kinematics === 'corexy'
                  ? `CoreXY${p.is_multicolor ? ` ${p.tool_count ?? p.extruder_slots}C` : ''}`
                  : `Cartesiana ${p.gcode_flavor ? p.gcode_flavor.toUpperCase() : 'Marlin 2'}`;

              return (
                <div
                  key={p.printer_id}
                  className={`flex items-center justify-between rounded-xl border px-3 py-2 transition ${
                    active
                      ? 'border-cyan-500/70 bg-cyan-500/10 shadow-sm shadow-cyan-500/10'
                      : 'border-slate-800 bg-slate-950/60 hover:border-slate-700'
                  }`}
                >
                  <button
                    type="button"
                    data-printer-id={p.printer_id}
                    onClick={() => onSelectPrinter(p.printer_id)}
                    className="min-w-0 flex-1 cursor-pointer pr-2 text-left"
                  >
                    <div className="flex items-center gap-2">
                      <Cpu
                        className={`h-3.5 w-3.5 shrink-0 ${active ? 'text-cyan-400' : 'text-slate-500'}`}
                      />
                      <span className="truncate text-xs font-semibold text-slate-100">
                        {p.display_name}
                        {p.ip ? (
                          <span className="ml-1.5 font-mono text-[11px] font-normal text-emerald-300">
                            · {p.ip}
                          </span>
                        ) : null}
                      </span>
                    </div>
                    <p className="mt-0.5 pl-5 text-[11px] text-slate-400">
                      {kinLabel} · {volLabel}
                    </p>
                  </button>
                  <div className="flex shrink-0 items-center gap-1.5">
                    {p.is_multicolor && (
                      <span className="rounded-md border border-purple-500/40 bg-purple-500/15 px-1.5 py-0.5 font-mono text-[10px] text-purple-200">
                        {p.tool_count ?? p.extruder_slots}C
                      </span>
                    )}
                    <span className="rounded-md bg-slate-800/90 px-2 py-0.5 font-mono text-[11px] text-cyan-300">
                      {p.max_volumetric_flow_mm3_s} mm³/s
                    </span>
                    {p.is_custom && onDeletePrinter && printers.length > 1 && (
                      <button
                        type="button"
                        onClick={() => onDeletePrinter(p.printer_id)}
                        title="Eliminar impresora personalizada"
                        className="rounded p-1 text-slate-500 transition hover:bg-rose-500/15 hover:text-rose-300"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>

        {/* PASO 2: Carga STL y Análisis Trimesh */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/75 p-3.5">
          <div className="mb-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500/20 text-[11px] font-bold text-cyan-300">
                2
              </span>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-200">
                Modelo 3D (.STL / .3MF)
              </h2>
            </div>
            <div className="flex items-center gap-1">
              {analysis?.file_format === '3mf' && (
                <span className="rounded bg-purple-500/20 px-1.5 py-0.5 font-mono text-[10px] text-purple-200">
                  3MF ({analysis.multimaterial_parts?.length ?? 1} partes)
                </span>
              )}
              {analysis?.mesh_id && (
                <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300">
                  caché: {analysis.mesh_id}
                </span>
              )}
              {(stlFile || analysis?.mesh_id) && (
                <button
                  type="button"
                  disabled={isAnalyzing}
                  onClick={() => {
                    if (lastModelFileHandleRef.current) {
                      void lastModelFileHandleRef.current
                        .getFile()
                        .then((freshFile) => onSelectStl(freshFile))
                        .catch(() => {
                          if (stlFile) onSelectStl(stlFile);
                          else void handlePickModelFile();
                        });
                    } else if (stlFile) {
                      onSelectStl(stlFile);
                    } else {
                      void handlePickModelFile();
                    }
                  }}
                  title="Recargar y re-analizar el modelo actual (si el archivo cambió en disco, vuelve a seleccionarlo)"
                  className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/10 px-1.5 py-0.5 text-[10px] font-medium text-cyan-200 transition hover:bg-cyan-500/20 disabled:opacity-40"
                >
                  <RefreshCw className={`h-3 w-3 ${isAnalyzing ? 'animate-spin' : ''}`} />
                  Recargar
                </button>
              )}
            </div>
          </div>

          <div
            role="button"
            tabIndex={0}
            onClick={() => void handlePickModelFile()}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                void handlePickModelFile();
              }
            }}
            onDragOver={(e) => {
              e.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            className={`flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-3 py-3 text-center transition ${
              isDragging
                ? 'border-cyan-400 bg-cyan-500/10'
                : 'border-slate-700 bg-slate-950/50 hover:border-slate-500'
            }`}
          >
            <FileUp className="mb-1.5 h-5 w-5 text-cyan-400" />
            <span className="max-w-full truncate text-xs font-medium text-slate-200">
              {stlFile ? stlFile.name : 'Arrastra tu .stl o .3mf multicolor aquí'}
            </span>
            <span className="mt-0.5 text-[11px] text-slate-400">
              {stlFile
                ? `${formatFileSize(stlFile.size)} · Análisis Trimesh`
                : 'Validación instantánea y extracción de partes multicolor'}
            </span>
          </div>
          <input
            ref={modelFileInputRef}
            type="file"
            accept=".stl,.3mf"
            onChange={handleFileInput}
            className="hidden"
          />

          {isAnalyzing && (
            <div className="mt-2.5 flex items-center gap-2 text-xs text-cyan-300">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              Analizando geometría y envolvente...
            </div>
          )}

          {analysis && !isAnalyzing && (
            <div className="mt-2.5 space-y-2">
              <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-slate-800 bg-slate-950/70 p-2 text-center">
                <div>
                  <p className="text-[10px] uppercase text-slate-500">Eje X</p>
                  <p className="font-mono text-xs font-semibold text-slate-100">
                    {analysis.dimensions_mm.x} mm
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase text-slate-500">Eje Y</p>
                  <p className="font-mono text-xs font-semibold text-slate-100">
                    {analysis.dimensions_mm.y} mm
                  </p>
                </div>
                <div>
                  <p className="text-[10px] uppercase text-slate-500">Altura Z</p>
                  <p className="font-mono text-xs font-semibold text-slate-100">
                    {analysis.dimensions_mm.z} mm
                  </p>
                </div>
              </div>

              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span className="flex items-center gap-1">
                  <Ruler className="h-3 w-3 text-slate-500" />
                  Base {analysis.base_contact_area_mm2.toFixed(0)} mm² ·{' '}
                  {analysis.triangle_count.toLocaleString()} tri.
                </span>
                <span
                  className={
                    analysis.fits_in_volume ? 'text-emerald-400' : 'text-rose-400'
                  }
                >
                  {analysis.fits_in_volume ? 'Cabe en cama' : 'Excede volumen'}
                </span>
              </div>

              {analysis.warnings.length > 0 && (
                <div className="max-h-24 space-y-1 overflow-y-auto pr-0.5">
                  {analysis.warnings.map((w, idx) => (
                    <div
                      key={idx}
                      className={`flex items-start gap-1.5 rounded-lg border px-2 py-1 text-[11px] leading-snug ${
                        analysis.fits_in_volume
                          ? 'border-amber-500/40 bg-amber-500/10 text-amber-200'
                          : 'border-rose-500/50 bg-rose-500/15 text-rose-200'
                      }`}
                    >
                      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                      <span>{w}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>

        {/* PASO 3: Material, Boquilla, Temperaturas, Soportes, Balsa e IA */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/75 p-3.5">
          <div className="mb-2.5 flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500/20 text-[11px] font-bold text-cyan-300">
                3
              </span>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-200">
                Material y Parámetros
              </h2>
            </div>
            <span className="flex items-center gap-1 text-[11px] text-cyan-300">
              <Gauge className="h-3.5 w-3.5" />
              Máx {activeFlowLimit} mm³/s
            </span>
          </div>

          {/* Banner automático de auditoría DeepSeek (solo activo cuando hay modelo cargado) */}
          {analysis && isOptimizingAI && (
            <div className="mb-2.5 flex items-center gap-2 rounded-xl border border-violet-500/35 bg-violet-500/10 px-3 py-2 text-[11px] text-violet-200">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-300" />
              <span>Auditando modelo y parámetros con DeepSeek...</span>
            </div>
          )}

          {analysis && !isOptimizingAI && aiReasoning && (
            <div className="mb-2.5 rounded-lg border border-violet-500/35 bg-violet-950/40 px-2.5 py-1.5 text-[11px] text-violet-200">
              <div className="mb-0.5 flex items-center justify-between text-[10px] font-semibold uppercase text-violet-300">
                <span>Recomendación aplicada</span>
                <span className="rounded bg-violet-500/25 px-1.5 py-0.5 font-mono">
                  {aiProvider}
                </span>
              </div>
              <p className="leading-snug text-violet-100">{aiReasoning}</p>
            </div>
          )}

          {/* Boquilla + Filamento Alta Velocidad */}
          <div className="mb-2.5 grid grid-cols-1 gap-2 rounded-xl border border-slate-800 bg-slate-950/60 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[11px] font-medium text-slate-300">
                Boquilla
              </span>
              <div className="grid grid-cols-4 gap-1">
                {NOZZLE_OPTIONS.map((diam) => {
                  const active = nozzleDiameter === diam;
                  return (
                    <button
                      key={diam}
                      type="button"
                      onClick={() => onChangeNozzleDiameter(diam)}
                      className={`rounded-md border px-2 py-0.5 font-mono text-[11px] font-semibold transition ${
                        active
                          ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                          : 'border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {diam}
                    </button>
                  );
                })}
              </div>
            </div>

            {selectedProfileId !== 'creator5_pro' && (
              <div className="flex items-center justify-between border-t border-slate-800/80 pt-2">
                <div>
                  <div className="flex items-center gap-1 text-xs font-medium text-slate-200">
                    <Zap className="h-3.5 w-3.5 text-amber-400" />
                    <span>Filamento Alta Velocidad (HS)</span>
                  </div>
                  <p className="text-[10px] text-slate-400">
                    Eleva caudal máximo a {hsLimit} mm³/s
                  </p>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={highSpeedFilament}
                  onClick={() => onToggleHighSpeedFilament(!highSpeedFilament)}
                  className={`relative h-5 w-10 rounded-full transition ${
                    highSpeedFilament ? 'bg-amber-500' : 'bg-slate-700'
                  }`}
                >
                  <span
                    className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                      highSpeedFilament ? 'translate-x-5' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>
            )}
          </div>

          {/* Interruptor dedicado: Modo Litofanía (Alta Definición a Contraluz) */}
          <div
            className={`mb-2.5 rounded-xl border p-2.5 transition ${
              lithophaneMode
                ? 'border-cyan-400/60 bg-gradient-to-br from-cyan-950/60 via-slate-950/80 to-amber-950/30 shadow-sm shadow-cyan-500/10'
                : 'border-slate-800 bg-slate-950/60'
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-1.5 text-xs font-semibold text-slate-100">
                  <Sun
                    className={`h-3.5 w-3.5 shrink-0 ${
                      lithophaneMode ? 'text-amber-300' : 'text-slate-400'
                    }`}
                  />
                  <span>Modo Litofanía (Alta Definición a Contraluz)</span>
                </div>
                <p className="mt-0.5 text-[10px] text-slate-400">
                  {lithophaneMode
                    ? 'Solo PLA / PLA HS · Costura atrás · Anti-ringing activo'
                    : 'Configura capa fina, 99% rectilíneo, pared lenta y brim sin soportes'}
                </p>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={lithophaneMode}
                aria-label="Modo Litofanía (Alta Definición a Contraluz)"
                onClick={() => onToggleLithophaneMode(!lithophaneMode)}
                className={`relative h-5 w-10 shrink-0 rounded-full transition ${
                  lithophaneMode ? 'bg-cyan-500' : 'bg-slate-700'
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                    lithophaneMode ? 'translate-x-5' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
            {lithophaneMode && (
              <div className="mt-2 rounded-lg border border-cyan-500/30 bg-slate-950/80 px-2.5 py-1.5 text-[10px] font-medium text-cyan-200">
                {(() => {
                  const sp =
                    LITHOPHANE_OUTER_SPEEDS[selectedProfileId] ??
                    LITHOPHANE_OUTER_SPEEDS.flsun_t1_pro;
                  const outerSpeed = highSpeedFilament ? sp.hs : sp.std;
                  const layerLabel = nozzleDiameter <= 0.2 ? '0.10' : '0.12';
                  const brimLabel = Math.max(8, Math.min(10, Math.round(brimWidthMm || 8)));
                  return `Litofanía · Capa ${layerLabel} mm · Relleno 99% Rectilíneo · Pared Ext. ${outerSpeed} mm/s · Brim ${brimLabel} mm · Sin Soportes`;
                })()}
              </div>
            )}
          </div>

          {/* Selector Material (oculto en Creator 5 Pro salvo en Modo Litofanía, donde solo se muestra PLA) */}
          {(selectedProfileId !== 'creator5_pro' || lithophaneMode) && (
            <>
              <div className={`grid gap-1.5 ${lithophaneMode ? 'grid-cols-1' : 'grid-cols-4'}`}>
                {(Object.keys(MATERIAL_DEFAULTS) as MaterialType[])
                  .filter((mat) => !lithophaneMode || mat === 'pla')
                  .map((mat) => {
                  const active = material === mat;
                  return (
                    <button
                      key={mat}
                      type="button"
                      onClick={() => onChangeMaterial(mat)}
                      className={`rounded-lg border py-1.5 text-xs font-semibold transition ${
                        active
                          ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                          : 'border-slate-800 bg-slate-950/60 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {lithophaneMode ? 'PLA (Recomendado para Litofanía a contraluz)' : MATERIAL_DEFAULTS[mat].label}
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-[11px] text-slate-400">{matMeta.hint}</p>
            </>
          )}

          {learnings && learnings.runs_count > 0 && (
            <div className="mt-2 rounded-lg border border-emerald-500/30 bg-emerald-950/25 px-2.5 py-1.5 text-[10px]">
              <button
                type="button"
                onClick={() => setLearningsOpen((v) => !v)}
                className="flex w-full items-center justify-between gap-2 text-left font-semibold text-emerald-300"
              >
                <span className="flex items-center gap-1.5">
                  <Sparkles className="h-3 w-3 text-emerald-400" />
                  Aprendizaje real: {learnings.runs_count}{' '}
                  {learnings.runs_count === 1 ? 'corrida' : 'corridas'} {learnings.material} en esta máquina
                </span>
                {learningsOpen ? (
                  <ChevronUp className="h-3.5 w-3.5 shrink-0" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                )}
              </button>
              {learningsOpen && (
                <div className="mt-1.5 space-y-1 border-t border-emerald-500/20 pt-1.5 text-slate-300">
                  <div className="flex flex-wrap gap-2 font-mono text-[9px] text-emerald-200">
                    {learnings.avg_nozzle_temp !== null && (
                      <span>Boquilla prom: {learnings.avg_nozzle_temp}°C</span>
                    )}
                    {learnings.avg_bed_temp !== null && (
                      <span>Cama prom: {learnings.avg_bed_temp}°C</span>
                    )}
                    {learnings.avg_speed_mms !== null && (
                      <span>Vel. prom: {learnings.avg_speed_mms} mm/s</span>
                    )}
                  </div>
                  {learnings.accumulated_improvements.length > 0 && (
                    <ul className="list-disc space-y-0.5 pl-4 text-[10px] text-slate-200">
                      {learnings.accumulated_improvements.map((imp, idx) => (
                        <li key={idx}>{imp}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Temperaturas Calculadas Automáticamente + Ajuste Manual colapsable (solo monocabezal) */}
          {selectedProfileId !== 'creator5_pro' && (
          <div className="mt-2.5 space-y-2 rounded-xl border border-slate-800 bg-slate-950/50 p-2.5">
            <div className="flex items-center justify-between gap-2 text-[10px] text-slate-400">
              <span>Rango carrete {matMeta.label} (°C)</span>
              <div className="flex items-center gap-1.5">
                <input
                  type="number"
                  min={150}
                  max={310}
                  value={spoolMinTemp}
                  onChange={(e) => onChangeSpoolMinTemp(Number(e.target.value) || 160)}
                  aria-label="Temp. Mín Carrete"
                  className="w-14 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-center font-mono text-[11px] text-orange-200 focus:border-orange-400 focus:outline-none"
                />
                <span className="text-slate-500">a</span>
                <input
                  type="number"
                  min={170}
                  max={320}
                  value={spoolMaxTemp}
                  onChange={(e) => onChangeSpoolMaxTemp(Number(e.target.value) || 260)}
                  aria-label="Temp. Máx Carrete"
                  className="w-14 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-center font-mono text-[11px] text-orange-200 focus:border-orange-400 focus:outline-none"
                />
              </div>
            </div>

            <div className="flex items-center justify-between gap-2 rounded-lg border border-orange-500/30 bg-orange-500/10 px-2.5 py-1.5">
              <div className="flex items-center gap-1.5 font-mono text-[11px] text-orange-100">
                <Flame className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                <span>
                  1.ª Capa: <strong>{clampedInitialTemp}°C</strong> · Impresión:{' '}
                  <strong>{clampedNormalTemp}°C</strong> · Cama: <strong>{bedTemp}°C</strong>
                </span>
              </div>
              <button
                type="button"
                onClick={() => setShowManualTemps((v) => !v)}
                className="flex shrink-0 items-center gap-1 rounded-md border border-slate-700 bg-slate-900/90 px-2 py-0.5 text-[10px] font-medium text-slate-300 hover:border-cyan-500/50 hover:text-white"
              >
                <SlidersHorizontal className="h-3 w-3 text-cyan-400" />
                <span>Ajuste manual</span>
                {showManualTemps ? (
                  <ChevronUp className="h-3 w-3" />
                ) : (
                  <ChevronDown className="h-3 w-3" />
                )}
              </button>
            </div>

            {showManualTemps && (
              <div className="space-y-2 border-t border-slate-800/80 pt-2">
                <div>
                  <div className="mb-0.5 flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 text-slate-300">
                      <Flame className="h-3.5 w-3.5 text-amber-400" />
                      Boquilla 1.ª Capa
                    </span>
                    <span className="font-mono font-semibold text-amber-300">
                      {clampedInitialTemp} °C
                    </span>
                  </div>
                  <input
                    type="range"
                    min={sliderMin}
                    max={sliderMax}
                    value={clampedInitialTemp}
                    onChange={(e) => onChangeNozzleTempInitial(Number(e.target.value))}
                    className="w-full cursor-pointer accent-amber-500"
                  />
                </div>

                <div>
                  <div className="mb-0.5 flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 text-slate-300">
                      <Flame className="h-3.5 w-3.5 text-orange-400" />
                      Boquilla Impresión
                    </span>
                    <span className="font-mono font-semibold text-orange-300">
                      {clampedNormalTemp} °C
                    </span>
                  </div>
                  <input
                    type="range"
                    min={sliderMin}
                    max={sliderMax}
                    value={clampedNormalTemp}
                    onChange={(e) => onChangeNozzleTemp(Number(e.target.value))}
                    className="w-full cursor-pointer accent-orange-500"
                  />
                </div>

                <div>
                  <div className="mb-0.5 flex items-center justify-between text-xs">
                    <span className="flex items-center gap-1.5 text-slate-300">
                      <Thermometer className="h-3.5 w-3.5 text-cyan-400" />
                      Cama Caliente
                    </span>
                    <span className="font-mono font-semibold text-cyan-300">
                      {bedTemp} °C
                    </span>
                  </div>
                  <input
                    type="range"
                    min={matMeta.bedMin}
                    max={matMeta.bedMax}
                    value={bedTemp}
                    onChange={(e) => onChangeBedTemp(Number(e.target.value))}
                    className="w-full cursor-pointer accent-cyan-500"
                  />
                </div>
              </div>
            )}
          </div>
          )}

          {/* Control Avanzado de Soportes + Botón "Soporte con IA" */}
          <div className="mt-2.5 space-y-2 rounded-xl border border-slate-800 bg-slate-950/60 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="flex items-center gap-1.5 text-xs font-medium text-slate-200">
                  <span>Soportes</span>
                  {analysis?.suggests_supports && (
                    <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-300">
                      Sugerido
                    </span>
                  )}
                </div>
                <p className="text-[10px] text-slate-400">
                  {supports
                    ? `${supportType === 'tree(auto)' ? 'Árbol' : 'Normal'} · Z=${supportZDistance.toFixed(2)} · XY=${supportXyDistance.toFixed(2)} mm`
                    : `Desactivados (Puentes 0.92 + Z=${matMeta.defaultSupportZ.toFixed(2)} · XY=${recommendedSupportXY.toFixed(2)} mm)`}
                </p>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="inline-flex rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-[10px]">
                  <button
                    type="button"
                    onClick={() => setSupportScope('global')}
                    className={`rounded-md px-2 py-0.5 font-medium transition ${
                      supportScope === 'global'
                        ? 'bg-cyan-500/20 text-cyan-200'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {t.step3.scopeGlobal}
                  </button>
                  <button
                    type="button"
                    onClick={() => setSupportScope('per_part')}
                    className={`rounded-md px-2 py-0.5 font-medium transition ${
                      supportScope === 'per_part'
                        ? 'bg-cyan-500/20 text-cyan-200'
                        : 'text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {t.step3.scopePerPart}
                  </button>
                </div>
                {supportScope === 'global' && (
                  <button
                    type="button"
                    role="switch"
                    aria-checked={supports}
                    onClick={() => onToggleSupports(!supports)}
                    className={`relative h-6 w-11 rounded-full transition ${
                      supports ? 'bg-cyan-500' : 'bg-slate-700'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white transition-transform ${
                        supports ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                )}
              </div>
            </div>

            {supportScope === 'per_part' && (
              <div className="space-y-1.5 border-t border-slate-800/80 pt-2">
                <p className="text-[10px] text-slate-400">{t.step3.perPartSupportsHint}</p>
                {sceneObjects.length === 0 && instances.length === 0 ? (
                  <p className="rounded-lg border border-slate-800 bg-slate-900/60 px-2 py-1.5 text-[10px] text-slate-400">
                    {t.step3.noPartsForOverride}
                  </p>
                ) : (
                  <div className="max-h-44 space-y-1.5 overflow-y-auto pr-0.5">
                    {(sceneObjects.length > 0
                      ? sceneObjects.map((obj, idx) => ({
                          key: obj.object_id,
                          name: obj.name || `Pieza ${idx + 1}`,
                          isSelected: selectedObjectIds.includes(obj.object_id),
                          overrides: obj.overrides ?? {},
                          onSelect: () => onSelectObjects?.([obj.object_id]),
                          onUpdate: (patch: Partial<ObjectPrintOverrides>) => {
                            if (!onChangeSceneObjects) return;
                            onChangeSceneObjects(
                              sceneObjects.map((o) =>
                                o.object_id === obj.object_id
                                  ? { ...o, overrides: { ...(o.overrides ?? {}), ...patch } }
                                  : o,
                              ),
                            );
                          },
                        }))
                      : instances.map((inst, idx) => ({
                          key: inst.instance_id,
                          name: `Pieza #${idx + 1}`,
                          isSelected: false,
                          overrides: inst.overrides ?? {},
                          onSelect: undefined,
                          onUpdate: (patch: Partial<ObjectPrintOverrides>) => {
                            if (!onChangeInstances) return;
                            onChangeInstances(
                              instances.map((it) =>
                                it.instance_id === inst.instance_id
                                  ? { ...it, overrides: { ...(it.overrides ?? {}), ...patch } }
                                  : it,
                              ),
                            );
                          },
                        }))
                    ).map((row) => {
                      const activeMode =
                        row.overrides.enable_support === false
                          ? 'none'
                          : row.overrides.support_type === 'tree(auto)'
                            ? 'tree'
                            : row.overrides.support_type === 'normal(auto)'
                              ? 'normal'
                              : row.overrides.enable_support === true
                                ? 'tree'
                                : 'inherit';
                      return (
                        <div
                          key={row.key}
                          onClick={row.onSelect}
                          className={`space-y-1 rounded-lg border p-1.5 transition ${
                            row.isSelected
                              ? 'border-cyan-500/60 bg-cyan-500/10'
                              : 'border-slate-800 bg-slate-900/70'
                          } ${row.onSelect ? 'cursor-pointer' : ''}`}
                        >
                          <div className="flex items-center justify-between gap-1 text-[11px]">
                            <span className="truncate font-medium text-slate-200">{row.name}</span>
                          </div>
                          <div
                            className="grid grid-cols-4 gap-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {(
                              [
                                ['inherit', t.step3.overrideInherit],
                                ['tree', t.step3.overrideTree],
                                ['normal', t.step3.overrideNormal],
                                ['none', t.step3.overrideNoSupport],
                              ] as const
                            ).map(([mode, label]) => (
                              <button
                                key={mode}
                                type="button"
                                onClick={() => {
                                  if (mode === 'inherit') {
                                    row.onUpdate({
                                      enable_support: 'inherit',
                                      support_type: 'inherit',
                                    });
                                  } else if (mode === 'none') {
                                    row.onUpdate({
                                      enable_support: false,
                                      support_type: 'inherit',
                                    });
                                  } else if (mode === 'tree') {
                                    row.onUpdate({
                                      enable_support: true,
                                      support_type: 'tree(auto)',
                                    });
                                  } else {
                                    row.onUpdate({
                                      enable_support: true,
                                      support_type: 'normal(auto)',
                                    });
                                  }
                                }}
                                className={`rounded border py-0.5 text-[10px] font-medium transition ${
                                  activeMode === mode
                                    ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                                    : 'border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200'
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            )}

            {aiSupportStatus && (
              <div
                className={`rounded-lg border px-2.5 py-2 text-[11px] ${
                  !aiSupportStatus.supports_required
                    ? 'border-emerald-500/45 bg-emerald-500/10 text-emerald-100'
                    : 'border-amber-500/50 bg-amber-500/15 text-amber-100'
                }`}
              >
                <div className="mb-1 flex items-center justify-between gap-1.5">
                  <span
                    className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                      !aiSupportStatus.supports_required
                        ? 'bg-emerald-500/25 text-emerald-200'
                        : 'bg-amber-500/25 text-amber-200'
                    }`}
                  >
                    {!aiSupportStatus.supports_required ? (
                      <ShieldCheck className="h-3 w-3" />
                    ) : (
                      <AlertTriangle className="h-3 w-3" />
                    )}
                    {aiSupportStatus.badge_label}
                  </span>
                  <span className="rounded bg-slate-900/90 px-1.5 py-0.5 font-mono text-[9px] text-cyan-300">
                    {aiSupportStatus.provider}
                  </span>
                </div>
                <p className="text-[10px] font-medium text-slate-200">
                  {aiSupportStatus.critical_zone_description}
                </p>
                {aiSupportStatus.estimated_savings_summary && (
                  <p className="mt-1 rounded bg-slate-950/70 px-2 py-1 text-[10px] font-semibold text-cyan-200">
                    {aiSupportStatus.estimated_savings_summary}
                  </p>
                )}
                {aiSupportStatus.supports_required && (
                  <p className="mt-1 text-[10px] text-amber-200">
                    {aiSupportStatus.support_type === 'tree(auto)'
                      ? 'Soportes en árbol'
                      : 'Soportes normales'}{' '}
                    ·{' '}
                    {aiSupportStatus.support_on_build_plate_only
                      ? 'Solo desde cama'
                      : 'Desde pieza y cama'}{' '}
                    · Separación Z {aiSupportStatus.support_z_distance.toFixed(2)} mm / XY{' '}
                    {(aiSupportStatus.support_xy_distance ?? recommendedSupportXY).toFixed(2)} mm
                  </p>
                )}
                <p className="mt-1 leading-snug text-[10px] text-slate-200">
                  {aiSupportStatus.reasoning}
                </p>
              </div>
            )}

            {supports && (
              <div className="mt-2.5 space-y-2 border-t border-slate-800 pt-2">
                <div className="grid grid-cols-2 gap-1.5">
                  <button
                    type="button"
                    onClick={() => {
                      onChangeSupportType('tree(auto)');
                      if (supportStyle === 'grid' || supportStyle === 'snug') {
                        onChangeSupportStyle?.('default');
                      }
                    }}
                    className={`rounded-lg border py-1 text-[11px] font-medium transition ${
                      supportType === 'tree(auto)'
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400'
                    }`}
                  >
                    Árbol (Orgánico)
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      onChangeSupportType('normal(auto)');
                      if (
                        supportStyle === 'tree_slim' ||
                        supportStyle === 'tree_strong' ||
                        supportStyle === 'tree_hybrid' ||
                        supportStyle === 'organic'
                      ) {
                        onChangeSupportStyle?.('default');
                      }
                    }}
                    className={`rounded-lg border py-1 text-[11px] font-medium transition ${
                      supportType === 'normal(auto)'
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400'
                    }`}
                  >
                    Normal / Típico
                  </button>
                </div>

                {onChangeSupportStyle && (
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-[11px] text-slate-300">Estilo de soporte</span>
                    <select
                      value={supportStyle}
                      onChange={(e) => onChangeSupportStyle(e.target.value)}
                      className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] font-medium text-slate-100 focus:border-cyan-500 focus:outline-none"
                    >
                      <option value="default">Por defecto</option>
                      {supportType.startsWith('normal') ? (
                        <>
                          <option value="grid">Rejilla</option>
                          <option value="snug">Ajustado (Snug)</option>
                        </>
                      ) : (
                        <>
                          <option value="tree_slim">Árbol delgado</option>
                          <option value="tree_strong">Árbol fuerte</option>
                          <option value="tree_hybrid">Árbol híbrido</option>
                          <option value="organic">Árbol orgánico</option>
                        </>
                      )}
                    </select>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-1.5">
                  <button
                    type="button"
                    onClick={() => onChangeSupportOnBuildPlateOnly(true)}
                    className={`rounded-lg border py-1 text-[11px] font-medium transition ${
                      supportOnBuildPlateOnly
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400'
                    }`}
                  >
                    Solo desde placa
                  </button>
                  <button
                    type="button"
                    onClick={() => onChangeSupportOnBuildPlateOnly(false)}
                    className={`rounded-lg border py-1 text-[11px] font-medium transition ${
                      !supportOnBuildPlateOnly
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400'
                    }`}
                  >
                    Figura y placa
                  </button>
                </div>

                <div>
                  <div className="mb-0.5 flex items-center justify-between text-[11px]">
                    <span className="text-slate-300">
                      Separación Z (desprendimiento) · Rec {recommendedSupportZ.toFixed(2)}
                    </span>
                    <span className="font-mono font-semibold text-cyan-300">
                      {supportZDistance.toFixed(2)} mm
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0.12}
                    max={0.45}
                    step={0.02}
                    value={supportZDistance}
                    onChange={(e) =>
                      onChangeSupportZDistance(Number(e.target.value))
                    }
                    className="w-full cursor-pointer accent-cyan-500"
                  />
                </div>

                <div>
                  <div className="mb-0.5 flex items-center justify-between text-[11px]">
                    <span className="text-slate-300">
                      Separación XY (lateral) · Rec {recommendedSupportXY.toFixed(2)}
                    </span>
                    <span className="font-mono font-semibold text-emerald-300">
                      {supportXyDistance.toFixed(2)} mm
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0.25}
                    max={1.50}
                    step={0.05}
                    value={supportXyDistance}
                    onChange={(e) =>
                      onChangeSupportXyDistance(Number(e.target.value))
                    }
                    className="w-full cursor-pointer accent-emerald-500"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Adherencia a Cama (Balsa / Brim / Sin Balsa con ancho IA) */}
          <div className="mt-2 space-y-2 rounded-xl border border-slate-800 bg-slate-950/60 p-2.5">
            <div className="flex flex-wrap items-center justify-between gap-1">
              <div className="flex items-center gap-1.5">
                <span className="text-xs font-medium text-slate-200">
                  Adherencia en Cama
                </span>
                {adhesionLabel ? (
                  <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200">
                    {adhesionLabel}
                  </span>
                ) : analysis?.suggests_raft ? (
                  <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] text-amber-300">
                    Balsa sugerida
                  </span>
                ) : null}
              </div>
              <div className="inline-flex rounded-lg border border-slate-800 bg-slate-900 p-0.5 text-[10px]">
                <button
                  type="button"
                  onClick={() => setAdhesionScope('global')}
                  className={`rounded-md px-2 py-0.5 font-medium transition ${
                    adhesionScope === 'global'
                      ? 'bg-cyan-500/20 text-cyan-200'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {t.step3.scopeGlobal}
                </button>
                <button
                  type="button"
                  onClick={() => setAdhesionScope('per_part')}
                  className={`rounded-md px-2 py-0.5 font-medium transition ${
                    adhesionScope === 'per_part'
                      ? 'bg-cyan-500/20 text-cyan-200'
                      : 'text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {t.step3.scopePerPart}
                </button>
              </div>
            </div>
            {adhesionScope === 'per_part' ? (
              <div className="space-y-1.5 border-t border-slate-800/80 pt-2">
                <p className="text-[10px] text-slate-400">{t.step3.perPartAdhesionHint}</p>
                {sceneObjects.length === 0 && instances.length === 0 ? (
                  <p className="rounded-lg border border-slate-800 bg-slate-900/60 px-2 py-1.5 text-[10px] text-slate-400">
                    {t.step3.noPartsForOverride}
                  </p>
                ) : (
                  <div className="max-h-44 space-y-1.5 overflow-y-auto pr-0.5">
                    {(sceneObjects.length > 0
                      ? sceneObjects.map((obj, idx) => ({
                          key: obj.object_id,
                          name: obj.name || `Pieza ${idx + 1}`,
                          isSelected: selectedObjectIds.includes(obj.object_id),
                          overrides: obj.overrides ?? {},
                          onSelect: () => onSelectObjects?.([obj.object_id]),
                          onUpdate: (patch: Partial<ObjectPrintOverrides>) => {
                            if (!onChangeSceneObjects) return;
                            onChangeSceneObjects(
                              sceneObjects.map((o) =>
                                o.object_id === obj.object_id
                                  ? { ...o, overrides: { ...(o.overrides ?? {}), ...patch } }
                                  : o,
                              ),
                            );
                          },
                        }))
                      : instances.map((inst, idx) => ({
                          key: inst.instance_id,
                          name: `Pieza #${idx + 1}`,
                          isSelected: false,
                          overrides: inst.overrides ?? {},
                          onSelect: undefined,
                          onUpdate: (patch: Partial<ObjectPrintOverrides>) => {
                            if (!onChangeInstances) return;
                            onChangeInstances(
                              instances.map((it) =>
                                it.instance_id === inst.instance_id
                                  ? { ...it, overrides: { ...(it.overrides ?? {}), ...patch } }
                                  : it,
                              ),
                            );
                          },
                        }))
                    ).map((row) => {
                      const activeBrim = row.overrides.brim_type ?? 'inherit';
                      return (
                        <div
                          key={row.key}
                          onClick={row.onSelect}
                          className={`space-y-1 rounded-lg border p-1.5 transition ${
                            row.isSelected
                              ? 'border-cyan-500/60 bg-cyan-500/10'
                              : 'border-slate-800 bg-slate-900/70'
                          } ${row.onSelect ? 'cursor-pointer' : ''}`}
                        >
                          <div className="flex items-center justify-between gap-1 text-[11px]">
                            <span className="truncate font-medium text-slate-200">{row.name}</span>
                          </div>
                          <div
                            className="grid grid-cols-4 gap-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {(
                              [
                                ['inherit', t.step3.overrideInherit],
                                ['no_brim', t.step3.overrideNoBrim],
                                ['outer_only', t.step3.overrideBrim],
                                ['raft', t.step3.overrideRaft],
                              ] as const
                            ).map(([mode, label]) => (
                              <button
                                key={mode}
                                type="button"
                                onClick={() => {
                                  row.onUpdate({
                                    brim_type: mode,
                                    brim_width: mode === 'outer_only' ? 5 : 0,
                                    raft_layers: mode === 'raft' ? 2 : 0,
                                  });
                                }}
                                className={`rounded border py-0.5 text-[10px] font-medium transition ${
                                  activeBrim === mode
                                    ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                                    : 'border-slate-800 bg-slate-950 text-slate-400 hover:text-slate-200'
                                }`}
                              >
                                {label}
                              </button>
                            ))}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            ) : (
            <>
            <div className="grid grid-cols-3 gap-1.5">
              {(
                [
                  ['none', 'Sin Balsa'],
                  ['brim', `Brim ${Math.round(brimWidthMm)} mm`],
                  ['raft', 'Balsa (Raft 2)'],
                ] as const
              ).map(([mode, label]) => {
                const active = adhesionType === mode;
                return (
                  <button
                    key={mode}
                    type="button"
                    onClick={() => onChangeAdhesionType(mode)}
                    className={`rounded-lg border py-1 text-[11px] font-medium transition ${
                      active
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
            {adhesionType === 'brim' && (
              <div>
                <div className="mb-0.5 flex items-center justify-between text-[10px]">
                  <span className="text-slate-400">Ancho Brim Exterior (Gap 0.12 mm)</span>
                  <span className="font-mono font-semibold text-cyan-300">
                    {Math.round(brimWidthMm)} mm
                  </span>
                </div>
                <input
                  type="range"
                  min={4}
                  max={10}
                  step={1}
                  value={brimWidthMm}
                  onChange={(e) => onChangeBrimWidthMm(Number(e.target.value))}
                  className="w-full cursor-pointer accent-cyan-500"
                />
              </div>
            )}
            </>
            )}
          </div>

          {/* Sugerencia M600 cuando la impresora es monocolor pero el .3mf tiene varios colores */}
          {!isMulticolorPrinter && analysis?.is_multicolor && !lithophaneMode && (
            <div className="mt-2.5 rounded-xl border border-amber-500/35 bg-amber-950/20 p-2.5 text-[11px] text-amber-200">
              <div className="flex items-center gap-1.5 font-semibold">
                <Palette className="h-3.5 w-3.5 text-amber-400" />
                <span>Modelo multicolor en impresora monocolor</span>
              </div>
              <p className="mt-1 text-[10px] leading-relaxed text-amber-200/80">
                Esta máquina está configurada como monocolor. Puedes laminar normalmente o usar{' '}
                <strong>+ Pausa aquí (M600 / PAUSE)</strong> en el visor G-code para cambiar de filamento por capa.
              </p>
            </div>
          )}

          {/* Panel Multicabezal T0..Tn para impresoras multicolor (oculto en Modo Litofanía) */}
          {isMulticolorPrinter && !lithophaneMode && (
            <div className="mt-2.5 space-y-2.5 rounded-xl border border-purple-500/35 bg-purple-950/15 p-2.5">
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-purple-200">
                  <Palette className="h-3.5 w-3.5 text-purple-400" />
                  Multicabezal 4 Extrusores (T0–T3)
                </span>
                <span className="rounded bg-purple-500/20 px-1.5 py-0.5 font-mono text-[10px] text-purple-300">
                  Standby 170°C
                </span>
              </div>

              {/* Torre de Purga con Anclaje Anti-Desprendimiento */}
              <div className="space-y-1.5 rounded-lg border border-purple-500/25 bg-slate-950/75 px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-[11px] font-semibold text-slate-200">
                      {primeTowerEnabled
                        ? 'Torre de Purga: Activada (≥45 mm + Brim 15 mm)'
                        : 'Torre de Purga: Desactivada manualmente'}
                    </div>
                    {primeTowerReason && (
                      <p className="truncate text-[10px] text-purple-300/80">
                        {primeTowerReason}
                      </p>
                    )}
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-checked={primeTowerEnabled}
                    aria-label="Torre de Purga Inteligente"
                    onClick={() => onTogglePrimeTower(!primeTowerEnabled)}
                    className={`relative h-5 w-10 shrink-0 rounded-full transition ${
                      primeTowerEnabled ? 'bg-purple-500' : 'bg-slate-700'
                    }`}
                  >
                    <span
                      className={`absolute top-0.5 left-0.5 h-4 w-4 rounded-full bg-white transition-transform ${
                        primeTowerEnabled ? 'translate-x-5' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
                {primeTowerEnabled && (
                  <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] text-emerald-200">
                    <span className="font-semibold">
                      Anclaje Torre de Purga: Brim Reforzado (12–15 mm) + Base Estabilizada
                    </span>
                    {onChangePrimeTowerBrimWidthMm && (
                      <label className="flex items-center gap-1 text-[10px] text-emerald-200">
                        <span>Brim:</span>
                        <input
                          type="number"
                          min={8}
                          max={40}
                          step={1}
                          placeholder={
                            (analysis?.dimensions_mm?.z ?? 0) > 80 ? 'Auto 15' : 'Auto 12'
                          }
                          value={primeTowerBrimWidthMm ?? ''}
                          onChange={(e) => {
                            const raw = e.target.value.trim();
                            if (!raw) {
                              onChangePrimeTowerBrimWidthMm(null);
                              return;
                            }
                            const num = Number(raw);
                            if (Number.isFinite(num)) {
                              onChangePrimeTowerBrimWidthMm(Math.max(8, Math.min(40, num)));
                            }
                          }}
                          className="w-16 rounded border border-emerald-500/40 bg-slate-950 px-1.5 py-0.5 text-right font-mono text-[10px] text-emerald-100 placeholder-emerald-400/60 focus:border-emerald-400 focus:outline-none"
                          title="Ancho personalizado del brim de la torre de purga en mm (vacío = Auto 12 mm / 15 mm si Z > 80 mm)"
                        />
                        <span>mm</span>
                      </label>
                    )}
                  </div>
                )}
              </div>

              <div className="space-y-2">
                {extrudersConfig.map((slot) => {
                  const defs = getSlotSpoolDefaults(slot.material);
                  const sMin = typeof slot.spool_min === 'number' ? slot.spool_min : defs.min;
                  const sMax = typeof slot.spool_max === 'number' ? slot.spool_max : defs.max;
                  const sFlow =
                    typeof slot.max_volumetric_speed === 'number'
                      ? slot.max_volumetric_speed
                      : getSlotVolumetricSpeed(
                          slot.material,
                          Boolean(slot.high_speed),
                          volumetricLimits,
                          highSpeedVolumetricLimits,
                          selectedProfileId,
                        );
                  return (
                    <div
                      key={slot.extruder_index}
                      className="flex flex-col gap-1.5 rounded-lg border border-slate-800 bg-slate-950/80 p-2"
                    >
                      <div className="flex flex-wrap items-center justify-between gap-1.5">
                        <div className="flex items-center gap-1.5">
                          <span
                            className="h-3.5 w-3.5 rounded border border-white/25"
                            style={{ backgroundColor: slot.color_hex }}
                          />
                          <span className="font-mono text-[11px] font-bold text-slate-100">
                            Slot {slot.extruder_index + 1} (T{slot.extruder_index})
                          </span>
                          <input
                            type="text"
                            maxLength={7}
                            value={slot.color_hex}
                            onChange={(e) => {
                              const next = extrudersConfig.map((s) =>
                                s.extruder_index === slot.extruder_index
                                  ? { ...s, color_hex: e.target.value }
                                  : s,
                              );
                              onChangeExtrudersConfig(next);
                            }}
                            aria-label={`Hexadecimal T${slot.extruder_index}`}
                            className="w-[66px] rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] uppercase text-slate-200 focus:border-cyan-400 focus:outline-none"
                          />
                        </div>

                        <div className="flex items-center gap-1">
                          <select
                            value={slot.material}
                            onChange={(e) => {
                              const matVal = e.target.value as ExtruderSlotConfig['material'];
                              const newDefs = getSlotSpoolDefaults(matVal);
                              const updatedBase: ExtruderSlotConfig = {
                                ...slot,
                                material: matVal,
                                spool_min: newDefs.min,
                                spool_max: newDefs.max,
                              };
                              const calc = computeSlotThermalConfig(
                                updatedBase,
                                selectedProfileId,
                                nozzleDiameter,
                                volumetricLimits,
                                highSpeedVolumetricLimits,
                              );
                              const next = extrudersConfig.map((s) =>
                                s.extruder_index === slot.extruder_index
                                  ? {
                                      ...updatedBase,
                                      nozzle_temp: calc.nozzleNormal,
                                      nozzle_temp_initial_layer: calc.nozzleInitial,
                                      max_volumetric_speed: calc.maxVolFlow,
                                    }
                                  : s,
                              );
                              onChangeExtrudersConfig(next);
                            }}
                            className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[11px] text-slate-200"
                          >
                            <option value="pla">PLA</option>
                            <option value="petg">PETG</option>
                            <option value="abs">ABS</option>
                            <option value="tpu">TPU</option>
                          </select>

                          <button
                            type="button"
                            title="Filamento Alta Velocidad (HS) para este carrete"
                            onClick={() => {
                              const nextHs = !slot.high_speed;
                              const updatedBase: ExtruderSlotConfig = {
                                ...slot,
                                high_speed: nextHs,
                                spool_min: sMin,
                                spool_max: sMax,
                              };
                              const calc = computeSlotThermalConfig(
                                updatedBase,
                                selectedProfileId,
                                nozzleDiameter,
                                volumetricLimits,
                                highSpeedVolumetricLimits,
                              );
                              const next = extrudersConfig.map((s) =>
                                s.extruder_index === slot.extruder_index
                                  ? {
                                      ...updatedBase,
                                      nozzle_temp: calc.nozzleNormal,
                                      nozzle_temp_initial_layer: calc.nozzleInitial,
                                      max_volumetric_speed: calc.maxVolFlow,
                                    }
                                  : s,
                              );
                              onChangeExtrudersConfig(next);
                            }}
                            className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold transition ${
                              slot.high_speed
                                ? 'border-amber-400 bg-amber-500/20 text-amber-200'
                                : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'
                            }`}
                          >
                            HS
                          </button>
                        </div>
                      </div>

                      {/* Rango térmico del carrete + lectura calculada */}
                      {(() => {
                        const draft = draftSpoolRanges[slot.extruder_index];
                        const draftMinStr = draft?.min ?? String(sMin);
                        const draftMaxStr = draft?.max ?? String(sMax);
                        const isRangeDirty =
                          draftMinStr !== String(sMin) || draftMaxStr !== String(sMax);

                        const applySpoolRange = () => {
                          const parsedMin = Number(draftMinStr);
                          const parsedMax = Number(draftMaxStr);
                          const cleanMin = Math.max(
                            150,
                            Math.min(310, Number.isFinite(parsedMin) ? Math.round(parsedMin) : sMin),
                          );
                          const cleanMax = Math.max(
                            cleanMin + 5,
                            Math.min(320, Number.isFinite(parsedMax) ? Math.round(parsedMax) : sMax),
                          );
                          const updatedBase: ExtruderSlotConfig = {
                            ...slot,
                            spool_min: cleanMin,
                            spool_max: cleanMax,
                          };
                          const calc = computeSlotThermalConfig(
                            updatedBase,
                            selectedProfileId,
                            nozzleDiameter,
                            volumetricLimits,
                            highSpeedVolumetricLimits,
                          );
                          const next = extrudersConfig.map((s) =>
                            s.extruder_index === slot.extruder_index
                              ? {
                                  ...updatedBase,
                                  nozzle_temp: calc.nozzleNormal,
                                  nozzle_temp_initial_layer: calc.nozzleInitial,
                                  max_volumetric_speed: calc.maxVolFlow,
                                }
                              : s,
                          );
                          onChangeExtrudersConfig(next);
                          setDraftSpoolRanges((prev) => {
                            const copy = { ...prev };
                            delete copy[slot.extruder_index];
                            return copy;
                          });
                        };

                        return (
                          <div className="flex flex-wrap items-center justify-between gap-1.5 text-[10px]">
                            <div className="flex items-center gap-1 text-slate-400">
                              <span>Carrete:</span>
                              <input
                                type="text"
                                inputMode="numeric"
                                aria-label={`Temp mínima carrete T${slot.extruder_index}`}
                                value={draftMinStr}
                                onChange={(e) => {
                                  const raw = e.target.value.replace(/[^\d]/g, '');
                                  setDraftSpoolRanges((prev) => ({
                                    ...prev,
                                    [slot.extruder_index]: {
                                      min: raw,
                                      max: draftMaxStr,
                                    },
                                  }));
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault();
                                    applySpoolRange();
                                  }
                                }}
                                className="w-11 rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-center font-mono text-[10px] text-slate-200 focus:border-cyan-400 focus:outline-none"
                              />
                              <span>a</span>
                              <input
                                type="text"
                                inputMode="numeric"
                                aria-label={`Temp máxima carrete T${slot.extruder_index}`}
                                value={draftMaxStr}
                                onChange={(e) => {
                                  const raw = e.target.value.replace(/[^\d]/g, '');
                                  setDraftSpoolRanges((prev) => ({
                                    ...prev,
                                    [slot.extruder_index]: {
                                      min: draftMinStr,
                                      max: raw,
                                    },
                                  }));
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === 'Enter') {
                                    e.preventDefault();
                                    applySpoolRange();
                                  }
                                }}
                                className="w-11 rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-center font-mono text-[10px] text-slate-200 focus:border-cyan-400 focus:outline-none"
                              />
                              <span>°C</span>
                              <button
                                type="button"
                                onClick={applySpoolRange}
                                className={`ml-0.5 rounded border px-1.5 py-0.5 text-[9px] font-semibold transition ${
                                  isRangeDirty
                                    ? 'border-cyan-400 bg-cyan-500/25 text-cyan-100 hover:bg-cyan-500/35'
                                    : 'border-slate-700 bg-slate-900 text-slate-400 hover:border-slate-600 hover:text-slate-200'
                                }`}
                              >
                                Aplicar
                              </button>
                            </div>

                            <span className="font-mono text-[10px] text-cyan-300">
                              1.ª Capa: {slot.nozzle_temp_initial_layer}°C · Imp: {slot.nozzle_temp}°C · Máx {sFlow} mm³/s
                            </span>
                          </div>
                        );
                      })()}

                      {/* 12 muestras directas de color de filamento en 1 clic */}
                      <div className="grid grid-cols-12 gap-1">
                        {COLOR_PRESETS.map((preset) => {
                          const selected =
                            slot.color_hex.toUpperCase() === preset.hex.toUpperCase();
                          return (
                            <button
                              key={preset.hex}
                              type="button"
                              onClick={() => {
                                const next = extrudersConfig.map((s) =>
                                  s.extruder_index === slot.extruder_index
                                    ? { ...s, color_hex: preset.hex }
                                    : s,
                                );
                                onChangeExtrudersConfig(next);
                              }}
                              title={`${preset.name} (${preset.hex})`}
                              className={`h-4 w-full rounded-sm border transition ${
                                selected
                                  ? 'scale-110 border-white ring-2 ring-cyan-400'
                                  : 'border-white/20 hover:scale-105 hover:border-white/60'
                              }`}
                              style={{ backgroundColor: preset.hex }}
                            />
                          );
                        })}
                      </div>
                    </div>
                  );
                })}
              </div>

              {/* Resumen Multi-Material Inteligente (Cama + Habitáculo + Velocidades + Alertas) */}
              {(() => {
                const summary = computeHeterogeneousSummary(
                  extrudersConfig,
                  nozzleDiameter,
                  volumetricLimits,
                  highSpeedVolumetricLimits,
                  selectedProfileId,
                );
                const chamberCfg = getOptimalChamberConfig(
                  extrudersConfig.map((s) => s.material),
                );
                const effChamberTemp = chamberTempTarget ?? chamberCfg.targetTemp;
                return (
                  <div className="space-y-1.5 rounded-lg border border-cyan-500/25 bg-cyan-950/20 p-2 text-[10px]">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <label className="flex items-center gap-1.5 font-semibold text-cyan-200">
                        <span>Cama:</span>
                        <input
                          type="number"
                          min={40}
                          max={115}
                          step={1}
                          value={bedTemp}
                          onChange={(e) => {
                            const val = Number(e.target.value);
                            if (Number.isFinite(val)) {
                              onChangeBedTemp(Math.max(40, Math.min(115, Math.round(val))));
                            }
                          }}
                          className="w-12 rounded border border-cyan-500/40 bg-slate-900 px-1.5 py-0.5 text-center font-mono text-[11px] font-bold text-white outline-none focus:border-cyan-400"
                        />
                        <span className="font-mono text-white">°C</span>
                        {bedTemp !== summary.negotiatedBedTemp ? (
                          <button
                            type="button"
                            onClick={() => onChangeBedTemp(summary.negotiatedBedTemp)}
                            className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-[9px] text-cyan-300 hover:bg-slate-700"
                            title="Restaurar temperatura negociada automática"
                          >
                            Auto ({summary.negotiatedBedTemp}°C)
                          </button>
                        ) : (
                          <span className="text-[9px] font-normal text-cyan-300/75">(Auto)</span>
                        )}
                      </label>
                      <span className="font-mono text-slate-300">
                        Vel. máx. conjunto: <strong className="text-amber-300">{summary.maxLinearSpeed} mm/s</strong> (T{summary.bottleneckSlotIdx}: {summary.minFlow} mm³/s)
                      </span>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-cyan-500/15 pt-1.5">
                      <span className="font-semibold text-emerald-200">
                        Habitáculo: <strong className="font-mono text-white">{effChamberTemp}°C</strong> · {chamberCfg.modeLabel}
                      </span>
                      <label className="flex items-center gap-1.5 text-[10px] text-slate-300">
                        <span>Obj. cabina:</span>
                        <select
                          value={chamberTempTarget === null ? 'auto' : String(chamberTempTarget)}
                          onChange={(e) => {
                            const val = e.target.value;
                            onChangeChamberTempTarget(val === 'auto' ? null : Number(val));
                          }}
                          className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-white outline-none focus:border-cyan-400"
                        >
                          <option value="auto">Auto ({chamberCfg.targetTemp}°C)</option>
                          {[25, 30, 35, 40, 45, 50, 55].map((t) => (
                            <option key={t} value={String(t)}>
                              {t}°C
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    {summary.hasIncompatibleBodyMix && summary.incompatibleNote && (
                      <div className="rounded border border-amber-500/40 bg-amber-950/35 px-2 py-1 text-[10px] leading-snug text-amber-200">
                        {summary.incompatibleNote}
                      </div>
                    )}
                  </div>
                );
              })()}

              {/* Asignación interactiva: Todos los colores del .3MF (Color #1..#N) -> Cabezal físico (T0–T3) */}
              {analysis?.is_multicolor &&
                ((analysis.detected_colors && analysis.detected_colors.length > 1) ||
                  (analysis.extruder_triangle_percentages &&
                    Object.keys(analysis.extruder_triangle_percentages).length > 1)) && (() => {
                  const colorRows =
                    analysis.detected_colors && analysis.detected_colors.length > 0
                      ? analysis.detected_colors
                      : Object.entries(analysis.extruder_triangle_percentages || {})
                          .sort(([a], [b]) => Number(a.replace('T', '')) - Number(b.replace('T', '')))
                          .map(([tKey, pct], idx) => {
                            const zIdx = Number(tKey.replace('T', ''));
                            return {
                              index: idx + 1,
                              zone_key: `zone_${zIdx}`,
                              name: `Color #${idx + 1}`,
                              hex_color: analysis.detected_filament_colors?.[zIdx] || '#94A3B8',
                              percentage: pct,
                              z_min_mm: 0,
                              z_max_mm: analysis.dimensions_mm?.z ?? 0,
                              suggested_slot: Math.min(3, idx),
                            };
                          });
                  const effLh = sliderLayerHeight || 0.2;

                  return (
                    <div className="space-y-1.5 border-t border-purple-500/20 pt-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-[11px] font-medium text-purple-200">
                          Colores del modelo → Cabezal físico ({colorRows.length} zonas)
                        </span>
                        <span className="rounded bg-purple-500/20 px-1.5 py-0.5 font-mono text-[10px] text-purple-200">
                          {colorRows.length > 4 ? `+4 Colores · Auto M25` : 'paint_color'}
                        </span>
                      </div>
                      <div className="max-h-72 space-y-1.5 overflow-y-auto pr-0.5">
                        {colorRows.map((col, rIdx) => {
                          const mappedSlot =
                            partExtruderMap[col.zone_key] ?? col.suggested_slot;
                          const targetColor =
                            extrudersConfig[mappedSlot]?.color_hex || col.hex_color;
                          const peers = colorRows.filter((other, oIdx) => {
                            if (oIdx === rIdx) return false;
                            const otherSlot =
                              partExtruderMap[other.zone_key] ?? other.suggested_slot;
                            return otherSlot === mappedSlot;
                          });
                          const conflictingPeer = peers.find(
                            (other) =>
                              Math.max(col.z_min_mm, other.z_min_mm) <=
                              Math.min(col.z_max_mm, other.z_max_mm),
                          );
                          const earlierPeer = peers
                            .filter((other) => other.z_max_mm < col.z_min_mm)
                            .sort((a, b) => b.z_max_mm - a.z_max_mm)[0];

                          return (
                            <div
                              key={col.zone_key}
                              className="space-y-1 rounded-lg border border-slate-800 bg-slate-950 px-2 py-1.5 text-[11px]"
                            >
                              <div className="flex items-center justify-between gap-2">
                                <div className="flex min-w-0 items-center gap-1.5">
                                  <span
                                    className="h-3 w-3 shrink-0 rounded-sm border border-white/25"
                                    style={{ backgroundColor: col.hex_color }}
                                    title={`Color original en .3MF: ${col.hex_color}`}
                                  />
                                  <span className="truncate font-medium text-slate-200">
                                    {col.name}
                                  </span>
                                  <span className="shrink-0 font-mono text-[10px] text-slate-400">
                                    ({col.percentage.toFixed(1)}%)
                                  </span>
                                  <span className="shrink-0 font-mono text-[9px] text-slate-500">
                                    Z: {col.z_min_mm.toFixed(1)}–{col.z_max_mm.toFixed(1)}mm
                                  </span>
                                </div>
                                <div className="flex shrink-0 items-center gap-1.5">
                                  <span
                                    className="h-2.5 w-2.5 shrink-0 rounded-full border border-white/25"
                                    style={{ backgroundColor: targetColor }}
                                    title={`Carrete asignado: ${targetColor}`}
                                  />
                                  <select
                                    value={mappedSlot}
                                    aria-label={`Cabezal para ${col.name}`}
                                    onChange={(e) =>
                                      onChangePartExtruderMap({
                                        ...partExtruderMap,
                                        [col.zone_key]: Number(e.target.value),
                                      })
                                    }
                                    className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200"
                                  >
                                    {[0, 1, 2, 3].map((t) => {
                                      const sc = extrudersConfig[t];
                                      const presetName =
                                        COLOR_PRESETS.find(
                                          (p) =>
                                            p.hex.toUpperCase() ===
                                            sc?.color_hex?.toUpperCase(),
                                        )?.name || sc?.color_hex;
                                      return (
                                        <option key={t} value={t}>
                                          T{t} · {presetName} (
                                          {sc?.material?.toUpperCase() || 'PLA'})
                                        </option>
                                      );
                                    })}
                                  </select>
                                </div>
                              </div>

                              {peers.length > 0 && (
                                conflictingPeer ? (
                                  <p className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-200">
                                    ⚠ Cruce en Z (
                                    {Math.max(col.z_min_mm, conflictingPeer.z_min_mm).toFixed(1)}–
                                    {Math.min(col.z_max_mm, conflictingPeer.z_max_mm).toFixed(1)} mm)
                                    con {conflictingPeer.name} en T{mappedSlot}: compartirán el mismo
                                    filamento en esas capas o elige otro cabezal/orientación
                                  </p>
                                ) : earlierPeer ? (
                                  <p className="rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-200">
                                    ✓ Sin cruce en Z · Pausa automática en Z=
                                    {col.z_min_mm.toFixed(1)} mm (Capa{' '}
                                    {Math.max(2, Math.round(col.z_min_mm / effLh))}) para cambiar
                                    carrete en T{mappedSlot}
                                  </p>
                                ) : null
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}

              {/* Partes multicolor detectadas en archivo .3MF (ocultar si es una sola malla pintada por triángulo) */}
              {analysis?.multimaterial_parts &&
                analysis.multimaterial_parts.length > 0 &&
                (analysis.multimaterial_parts.length > 1 || !analysis.is_multicolor) && (
                <div className="space-y-1.5 border-t border-purple-500/20 pt-2">
                  <span className="block text-[11px] font-medium text-purple-200">
                    Partes del .3MF → Cabezal (T0–T3)
                  </span>
                  <div className="max-h-36 space-y-1 overflow-y-auto pr-0.5">
                    {analysis.multimaterial_parts.map((part) => {
                      const assignedExt = analysis.is_multicolor
                        ? (partExtruderMap[part.part_id] ?? 0)
                        : (partExtruderMap[part.part_id] ?? part.extruder);
                      const slotHex =
                        assignedExt > 0
                          ? (extrudersConfig[assignedExt - 1]?.color_hex || part.color_hex || '#94A3B8')
                          : (part.color_hex || '#94A3B8');
                      return (
                        <div
                          key={part.part_id}
                          className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950 px-2 py-1"
                        >
                          <div className="flex min-w-0 items-center gap-1.5">
                            <span
                              className="h-3 w-3 shrink-0 rounded-sm border border-white/25"
                              style={{ backgroundColor: slotHex }}
                            />
                            <span className="truncate text-[11px] font-medium text-slate-200">
                              {part.name}
                            </span>
                            <span className="shrink-0 font-mono text-[10px] text-slate-500">
                              {part.triangle_count.toLocaleString()}
                            </span>
                          </div>
                          <select
                            value={assignedExt}
                            onChange={(e) => {
                              const nextVal = Number(e.target.value);
                              const nextMap = { ...partExtruderMap };
                              if (analysis.is_multicolor && nextVal === 0) {
                                delete nextMap[part.part_id];
                              } else {
                                nextMap[part.part_id] = nextVal;
                              }
                              onChangePartExtruderMap(nextMap);
                            }}
                            className="shrink-0 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200"
                          >
                            {analysis.is_multicolor && (
                              <option value={0}>Pintura original del .3MF (Multicolor)</option>
                            )}
                            {[1, 2, 3, 4].map((extNum) => (
                              <option key={extNum} value={extNum}>
                                Slot {extNum} (T{extNum - 1})
                              </option>
                            ))}
                          </select>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Asignación figura vs soportes */}
              <div className="grid grid-cols-2 gap-1.5 pt-0.5">
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">
                    Cabezal Figura Base
                  </label>
                  <select
                    value={modelExtruder}
                    onChange={(e) => onChangeModelExtruder(Number(e.target.value))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-100"
                  >
                    {[0, 1, 2, 3].map((i) => (
                      <option key={i} value={i}>
                        Slot {i + 1} (T{i}) · {extrudersConfig[i]?.material.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">
                    Cabezal Soportes
                  </label>
                  <select
                    value={supportExtruder}
                    onChange={(e) => onChangeSupportExtruder(Number(e.target.value))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-100"
                  >
                    {[0, 1, 2, 3].map((i) => (
                      <option key={i} value={i}>
                        Slot {i + 1} (T{i}) · {extrudersConfig[i]?.material.toUpperCase()}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Pintura por rango de altura Z */}
              <div className="space-y-1.5 border-t border-purple-500/20 pt-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-purple-200">
                    Pintura por Altura Z (mm)
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      const prevEnd =
                        zColorRanges.length > 0
                          ? zColorRanges[zColorRanges.length - 1].max_z
                          : 0;
                      const nextIdx = (zColorRanges.length + 1) % 4;
                      onChangeZColorRanges([
                        ...zColorRanges,
                        { min_z: prevEnd, max_z: prevEnd + 40, extruder_index: nextIdx },
                      ]);
                    }}
                    className="flex items-center gap-1 rounded-md border border-purple-500/40 bg-purple-500/20 px-2 py-0.5 text-[10px] font-semibold text-purple-200 hover:bg-purple-500/30"
                  >
                    <Plus className="h-3 w-3" />
                    Añadir franja Z
                  </button>
                </div>

                {zColorRanges.map((rng, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-1.5 rounded-lg border border-slate-800 bg-slate-950 px-2 py-1"
                  >
                    <input
                      type="number"
                      min={0}
                      step={5}
                      value={rng.min_z}
                      onChange={(e) => {
                        const val = Math.max(0, Number(e.target.value) || 0);
                        onChangeZColorRanges(
                          zColorRanges.map((r, rIdx) =>
                            rIdx === idx ? { ...r, min_z: val } : r,
                          ),
                        );
                      }}
                      className="w-12 rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-center font-mono text-[10px] text-slate-200"
                    />
                    <span className="text-[10px] text-slate-500">–</span>
                    <input
                      type="number"
                      min={1}
                      step={5}
                      value={rng.max_z}
                      onChange={(e) => {
                        const val = Math.max(rng.min_z + 1, Number(e.target.value) || 1);
                        onChangeZColorRanges(
                          zColorRanges.map((r, rIdx) =>
                            rIdx === idx ? { ...r, max_z: val } : r,
                          ),
                        );
                      }}
                      className="w-12 rounded border border-slate-700 bg-slate-900 px-1 py-0.5 text-center font-mono text-[10px] text-slate-200"
                    />
                    <span className="text-[10px] text-slate-400">mm →</span>
                    <select
                      value={rng.extruder_index}
                      onChange={(e) => {
                        const ex = Number(e.target.value);
                        onChangeZColorRanges(
                          zColorRanges.map((r, rIdx) =>
                            rIdx === idx ? { ...r, extruder_index: ex } : r,
                          ),
                        );
                      }}
                      className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200"
                    >
                      {[0, 1, 2, 3].map((i) => (
                        <option key={i} value={i}>
                          Slot {i + 1} (T{i})
                        </option>
                      ))}
                    </select>
                    <button
                      type="button"
                      onClick={() =>
                        onChangeZColorRanges(zColorRanges.filter((_, rIdx) => rIdx !== idx))
                      }
                      className="ml-auto text-slate-500 hover:text-rose-400"
                      title="Eliminar franja Z"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Mapeo Extendido Multicolor (+4 Colores reales · Creator 5 Pro) */}
          {selectedProfileId === 'creator5_pro' &&
            analysis?.multimaterial_parts &&
            (analysis.detected_colors && analysis.detected_colors.length > 0
              ? analysis.detected_colors.length > 4
              : analysis.multimaterial_parts.length > 4) && (
              <div className="mt-2.5 space-y-2 rounded-xl border border-fuchsia-500/35 bg-fuchsia-500/5 p-2.5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-fuchsia-200">
                    <Palette className="h-3.5 w-3.5 text-fuchsia-400" />
                    Mapeo Extendido Multicolor (+4 Colores · Creator 5 Pro)
                  </span>
                  <span className="rounded bg-fuchsia-500/20 px-1.5 py-0.5 font-mono text-[10px] text-fuchsia-200">
                    {analysis.multimaterial_parts.length} colores
                  </span>
                </div>
                <p className="text-[10px] text-slate-400">
                  Asigna colores extra (5+) a T0–T3 si no se cruzan en Z; al laminar se inyectará pausa M25 automática.
                </p>
                <div className="space-y-1.5">
                  {analysis.multimaterial_parts.map((part, pIdx) => {
                    const assignedSlot =
                      partExtruderMap[part.part_id] ??
                      part.suggested_slot ??
                      ((part.extruder - 1) % 4);
                    const zMin = part.z_min_mm ?? 0;
                    const zMax = part.z_max_mm ?? 0;
                    const peers = (analysis.multimaterial_parts ?? []).filter((other, oIdx) => {
                      if (oIdx === pIdx) return false;
                      const otherSlot =
                        partExtruderMap[other.part_id] ??
                        other.suggested_slot ??
                        ((other.extruder - 1) % 4);
                      return otherSlot === assignedSlot;
                    });
                    const hasConflict = peers.some((other) => {
                      const oMin = other.z_min_mm ?? 0;
                      const oMax = other.z_max_mm ?? 0;
                      return Math.max(zMin, oMin) <= Math.min(zMax, oMax);
                    });
                    const earlierPeer = peers
                      .filter((other) => (other.z_max_mm ?? 0) < zMin)
                      .sort((a, b) => (b.z_max_mm ?? 0) - (a.z_max_mm ?? 0))[0];

                    return (
                      <div
                        key={part.part_id}
                        className="flex flex-col gap-1 rounded-lg border border-slate-800 bg-slate-950/75 p-2 text-[11px]"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex min-w-0 items-center gap-1.5">
                            <span
                              className="h-3 w-3 shrink-0 rounded-full border border-slate-600"
                              style={{ backgroundColor: part.color_hex || '#94a3b8' }}
                            />
                            <span className="truncate font-medium text-slate-200">
                              {part.name}
                            </span>
                            <span className="shrink-0 font-mono text-[10px] text-slate-400">
                              [{zMin.toFixed(1)}–{zMax.toFixed(1)}mm]
                            </span>
                          </div>
                          <select
                            value={assignedSlot}
                            onChange={(e) =>
                              onChangePartExtruderMap({
                                ...partExtruderMap,
                                [part.part_id]: Number(e.target.value),
                              })
                            }
                            className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-slate-100"
                          >
                            {[0, 1, 2, 3].map((slot) => (
                              <option key={slot} value={slot}>
                                T{slot}
                              </option>
                            ))}
                          </select>
                        </div>
                        {peers.length > 0 && (
                          <span
                            className={`inline-flex w-fit rounded px-1.5 py-0.5 text-[10px] font-medium ${
                              hasConflict
                                ? 'border border-rose-500/40 bg-rose-500/15 text-rose-200'
                                : 'border border-emerald-500/40 bg-emerald-500/15 text-emerald-200'
                            }`}
                          >
                            {hasConflict
                              ? 'Conflicto en Z: ambos colores coinciden en la misma capa'
                              : `Sin cruce en Z · Pausa automática en Z=${(((earlierPeer?.z_max_mm ?? zMin) + zMin) / 2).toFixed(1)}mm`}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

          {/* Perfiles Dinámicos por Máquina + Material + Boquilla + HS */}
          <div className="mt-2.5 space-y-2">
            <div className="flex items-center justify-between gap-2">
              <p className="text-xs font-medium text-slate-300">
                Perfiles Dinámicos (Arachne + Gyroid)
              </p>
              <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] font-bold text-cyan-300">
                {sliderLayerHeight.toFixed(2)} mm
              </span>
            </div>

            {/* Slider Discreto Calidad vs. Velocidad (0.08 - 0.28 mm) */}
            <div className="rounded-xl border border-slate-800 bg-slate-950/75 p-2.5">
              <div className="mb-1 flex items-center justify-between text-[10px]">
                <span className="font-semibold text-cyan-200">
                  {sliderScaleInfo.title}
                </span>
                <span className="text-slate-400">{sliderScaleInfo.sub}</span>
              </div>
              <input
                type="range"
                min={0.08}
                max={lithophaneMode ? 0.12 : 0.28}
                step={0.04}
                value={sliderLayerHeight}
                onChange={(e) => {
                  const nextH = Number(Number(e.target.value).toFixed(2));
                  setSliderLayerHeight(nextH);
                  onSelectDynamicProfile(
                    specializedProfileId === 'none' ? qualityPreset : specializedProfileId,
                    undefined,
                    nextH,
                  );
                }}
                className="w-full cursor-pointer accent-cyan-400"
              />
              <div className="mt-0.5 flex items-center justify-between text-[9px] text-slate-400">
                <span>Calidad Máxima (0.08)</span>
                <span>{lithophaneMode ? 'Litofanía (0.12)' : 'Máxima Velocidad (0.28)'}</span>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-1.5">
              {dynamicPresets.map((opt) => {
                const active =
                  specializedProfileId === 'none'
                    ? qualityPreset === opt.id
                    : specializedProfileId === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() =>
                      onSelectDynamicProfile(opt.id, opt.speedMmS, opt.layerHeight)
                    }
                    className={`rounded-xl border px-3 py-1.5 text-left transition ${
                      active
                        ? 'border-cyan-500/70 bg-cyan-500/10'
                        : 'border-slate-800 bg-slate-950/60 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="text-xs font-semibold text-slate-100">
                        {opt.label}
                      </span>
                      <div className="flex shrink-0 items-center gap-1">
                        {opt.shielded && (
                          <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-200">
                            Blindaje Anti-Delaminación
                          </span>
                        )}
                        {active && (
                          <ShieldCheck className="h-3.5 w-3.5 text-cyan-400" />
                        )}
                      </div>
                    </div>
                    <p className="text-[10px] text-slate-400">{opt.desc}</p>
                  </button>
                );
              })}
            </div>
          </div>
        </section>

      {/* PASO 4 COLAPSABLE */}
      <section className="rounded-xl border border-slate-800 bg-slate-900/95 p-3.5">
        <button
          type="button"
          onClick={() => setIsStep4Expanded((prev) => !prev)}
          className="flex w-full items-center justify-between gap-2 text-left"
        >
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500/20 text-[11px] font-bold text-cyan-300">
              4
            </span>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-200">
              Laminar y Exportar
            </h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={!effectiveProfileSnapshot}
              onClick={(ev) => {
                ev.stopPropagation();
                if (effectiveProfileSnapshot) setProfileDrawerOpen(true);
              }}
              className={`flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[10px] font-semibold transition ${
                effectiveProfileSnapshot
                  ? 'border-cyan-500/45 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25'
                  : 'cursor-not-allowed border-slate-700/60 bg-slate-900/50 text-slate-500 opacity-50'
              }`}
              title={
                effectiveProfileSnapshot
                  ? t.profileInspector.savedBadge
                  : t.profileInspector.disabledTooltip
              }
            >
              <SlidersHorizontal className="h-3 w-3" />
              <span>{t.profileInspector.buttonLabel}</span>
            </button>
            {!isStep4Expanded && sliceResult && (
              <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-300">
                Laminado listo · {sliceResult.estimated_time} · {sliceResult.filament_grams}g
              </span>
            )}
            {!analysis?.fits_in_volume && analysis && (
              <span className="text-[10px] font-medium text-amber-300">
                Auto-Ajusta o Auto-Orienta
              </span>
            )}
            {isStep4Expanded ? (
              <ChevronDown className="h-4 w-4 text-slate-400" />
            ) : (
              <ChevronUp className="h-4 w-4 text-slate-400" />
            )}
          </div>
        </button>

        {isStep4Expanded && (
        <div className="mt-2.5">

        <div className="mb-2 space-y-1.5">
          {!isUsbOrSdPrinter && (
            <label
              onClick={(e) => e.stopPropagation()}
              className="flex cursor-pointer items-center justify-between rounded-xl border border-slate-800 bg-slate-950/75 px-3 py-1.5 text-[11px] transition hover:border-cyan-500/40"
            >
              <span className="flex items-center gap-1.5 font-medium text-slate-200">
                <Video className="h-3.5 w-3.5 text-cyan-400" />
                Grabar Timelapse
                <span className="text-[10px] text-slate-400">
                  ({selectedProfileId === 'creator5_pro' ? 'Timelapse local + impresora' : 'Klipper por capa'})
                </span>
              </span>
              <input
                type="checkbox"
                disabled={isSlicing}
                checked={enableTimelapse}
                onClick={(e) => e.stopPropagation()}
                onChange={(e) => {
                  e.stopPropagation();
                  onToggleEnableTimelapse(e.target.checked);
                }}
                className="h-3.5 w-3.5 accent-cyan-500 disabled:opacity-40"
              />
            </label>
          )}

          <label
            onClick={(e) => e.stopPropagation()}
            className="flex cursor-pointer items-center justify-between rounded-xl border border-slate-800 bg-slate-950/75 px-3 py-1.5 text-[11px] transition hover:border-cyan-500/40"
          >
            <span className="flex items-center gap-1.5 font-medium text-slate-200">
              <Gauge className="h-3.5 w-3.5 text-emerald-400" />
              Nivelación / Calibración previa
              <span className="text-[10px] text-slate-400">
                ({autoLeveling ? 'Activa' : 'Directo sin sondeo'})
              </span>
            </span>
            <input
              type="checkbox"
              disabled={isSlicing}
              checked={autoLeveling}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => {
                e.stopPropagation();
                onToggleAutoLeveling(e.target.checked);
              }}
              className="h-3.5 w-3.5 accent-emerald-500 disabled:opacity-40"
            />
          </label>

          {onChangeInfillDensityOverride && (
            <div
              onClick={(e) => e.stopPropagation()}
              className="space-y-1.5 rounded-xl border border-slate-800 bg-slate-950/75 px-3 py-2 text-[11px]"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium text-slate-200">
                  Relleno (Infill)
                  <span className="ml-1 text-[10px] text-slate-400">
                    ({infillDensityOverride !== null ? `${infillDensityOverride}%` : 'Auto perfil'})
                  </span>
                </span>
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={5}
                    disabled={isSlicing}
                    placeholder="Auto"
                    value={infillDensityOverride ?? ''}
                    onChange={(e) => {
                      const raw = e.target.value;
                      if (raw === '') {
                        onChangeInfillDensityOverride(null);
                        return;
                      }
                      const num = Math.max(0, Math.min(100, Math.round(Number(raw) || 0)));
                      onChangeInfillDensityOverride(num);
                    }}
                    className="w-14 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-right font-mono text-[11px] font-bold text-cyan-300 focus:border-cyan-500 focus:outline-none disabled:opacity-40"
                  />
                  <span className="font-mono text-[10px] text-slate-400">%</span>
                </div>
              </div>
              <div className="grid grid-cols-6 gap-1">
                {[
                  { label: 'Auto', val: null },
                  { label: '12%', val: 12 },
                  { label: '15%', val: 15 },
                  { label: '25%', val: 25 },
                  { label: '50%', val: 50 },
                  { label: '100%', val: 100 },
                ].map((opt) => {
                  const active = infillDensityOverride === opt.val;
                  return (
                    <button
                      key={opt.label}
                      type="button"
                      disabled={isSlicing}
                      onClick={() => onChangeInfillDensityOverride(opt.val)}
                      className={`rounded border py-0.5 font-mono text-[10px] font-semibold transition disabled:opacity-40 ${
                        active
                          ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                          : 'border-slate-800 bg-slate-900 text-slate-400 hover:border-slate-700 hover:text-slate-200'
                      }`}
                    >
                      {opt.label}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>

        <button
          type="button"
          disabled={!canSlice}
          onClick={() => {
            setInstantOverlayMode('slicing');
            onSlice();
          }}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-cyan-500/20 transition hover:from-cyan-400 hover:to-blue-500 disabled:cursor-not-allowed disabled:opacity-45"
        >
          {isSlicing ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" />
              Laminando en motor nativo...
            </>
          ) : (
            <>
              <Play className="h-4 w-4 fill-current" />
              Laminar Modelo
            </>
          )}
        </button>

        <div className="mt-1.5 space-y-1.5">
          <div className="flex gap-1.5">
            <button
              type="button"
              disabled={!sliceResult || isSlicing || isAnalyzingAI || isOptimizingSliceAI}
              onClick={() => {
                setInstantOverlayMode('ai_analyze');
                onAnalyzeModelAI();
              }}
              title={
                !sliceResult
                  ? 'Lamina primero para evaluar tiempos, soportes y acabados reales'
                  : 'Detecta el tipo de modelo y sugiere estrategias de acabado y orientación con DeepSeek IA'
              }
              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-cyan-500/45 bg-gradient-to-r from-cyan-500/15 to-violet-500/15 px-3 py-2 text-xs font-semibold text-cyan-100 transition hover:from-cyan-500/25 hover:to-violet-500/25 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {isAnalyzingAI || isOptimizingSliceAI ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-300" />
              ) : (
                <Sparkles className="h-3.5 w-3.5 text-cyan-300" />
              )}
              <span>
                {isAnalyzingAI
                  ? 'Analizando modelo y laminado...'
                  : isOptimizingSliceAI
                    ? 'Optimizando y re-laminando...'
                    : t.step4.aiAnalysis}
              </span>
            </button>
            <button
              type="button"
              onClick={() => {
                onRefreshSavedProjects();
                setDefectTargetProj(null);
                setDefectResult(null);
                setProjectsModalTab('diagnostics');
                setProjectsModalOpen(true);
              }}
              className="rounded-xl border border-slate-700 bg-slate-800/90 px-2.5 py-2 text-[11px] font-semibold text-slate-200 hover:border-cyan-500/50 hover:text-cyan-200"
              title="Ver proyectos guardados y diagnosticar defectos post-impresión"
            >
              Proyectos
            </button>
          </div>
          {!sliceResult && (
            <p className="text-center text-[10px] text-slate-400">
              {t.step4.sliceFirstForAi}
            </p>
          )}

          {aiAnalysisResult && sliceResult && (
            isAiPresetsExpanded ? (
              <div className="space-y-2 rounded-xl border border-cyan-500/35 bg-slate-950/90 p-2.5 text-[11px]">
                <div className="flex items-start justify-between gap-2">
                  <p className="font-semibold leading-snug text-cyan-200">
                    {aiAnalysisResult.detected_type_summary}
                  </p>
                  <div className="flex shrink-0 items-center gap-1">
                    <span className="rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[9px] text-cyan-300">
                      {aiAnalysisResult.provider}
                    </span>
                    {aiOptimizeComparison && (
                      <button
                        type="button"
                        onClick={() => setIsAiPresetsExpanded(false)}
                        className="rounded border border-slate-700 bg-slate-800 px-1.5 py-0.5 text-[9px] text-slate-300 hover:bg-slate-700"
                      >
                        Ocultar ▲
                      </button>
                    )}
                  </div>
                </div>
                <input
                  type="text"
                  value={aiUserNotes}
                  onChange={(e) => setAiUserNotes(e.target.value)}
                  placeholder="Nota opcional (ej: sin soportes en cara frontal, textura mate...)"
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-[10px] text-slate-100 placeholder-slate-500 outline-none focus:border-cyan-400"
                />
                {aiAnalysisResult.filter_note && (
                  <p className="rounded-lg border border-cyan-500/20 bg-cyan-950/25 px-2 py-1 text-[9px] leading-snug text-cyan-200">
                    {aiAnalysisResult.filter_note}
                  </p>
                )}

                {aiAnalysisResult.contextual_options &&
                  aiAnalysisResult.contextual_options.length > 0 && (
                    <div className="space-y-1">
                      <p className="text-[9px] font-semibold uppercase tracking-wide text-slate-400">
                        Opciones Fijas Contextuales
                      </p>
                      <div className="grid grid-cols-1 gap-1">
                        {aiAnalysisResult.contextual_options.map((opt) => {
                          const overridesList = opt.quality_overrides ?? [];
                          const isOverrideOption = overridesList.length > 0;
                          const isSelectedOverride =
                            isOverrideOption &&
                            overridesList.every((ov) => aiQualityOverrides.includes(ov));
                          return (
                            <button
                              key={opt.id}
                              type="button"
                              disabled={isOptimizingSliceAI || isSlicing}
                              onClick={() => {
                                if (isOverrideOption && onToggleAiQualityOverride) {
                                  overridesList.forEach((ov) => onToggleAiQualityOverride(ov));
                                  return;
                                }
                                setInstantOverlayMode('ai_optimize');
                                onOptimizeSliceWithAI(
                                  opt.preset_id,
                                  aiUserNotes,
                                  opt.layer_height,
                                );
                              }}
                              className={`flex w-full flex-col items-start rounded-lg border px-2.5 py-1.5 text-left transition disabled:opacity-45 ${
                                isSelectedOverride
                                  ? 'border-emerald-400/70 bg-emerald-500/15 ring-1 ring-emerald-400/40'
                                  : 'border-slate-800 bg-slate-900/90 hover:border-cyan-500/50 hover:bg-cyan-500/10'
                              }`}
                            >
                              <div className="flex w-full items-center justify-between gap-1">
                                <span className="text-[10px] font-semibold text-slate-100">
                                  {isSelectedOverride ? '✓ ' : ''}
                                  {opt.label}
                                </span>
                                <span className="shrink-0 font-mono text-[9px] font-semibold text-amber-200">
                                  {opt.estimated_time_str}
                                </span>
                              </div>
                              <span className="font-mono text-[9px] text-cyan-300">
                                {opt.layer_height.toFixed(2)} mm · {opt.calibrated_speed_mms} mm/s ·{' '}
                                {opt.calibrated_temp_c}°C
                              </span>
                              <span className="text-[9px] text-slate-400">{opt.description}</span>
                            </button>
                          );
                        })}
                      </div>
                      {aiQualityOverrides.length > 0 && (
                        <div className="mt-1.5 space-y-1.5 rounded-lg border border-emerald-500/40 bg-emerald-950/25 p-2">
                          <div className="flex flex-wrap items-center justify-between gap-1">
                            <div className="flex flex-wrap gap-1">
                              {aiQualityOverrides.map((ov) => (
                                <span
                                  key={ov}
                                  className="rounded-full border border-emerald-500/45 bg-emerald-500/20 px-2 py-0.5 text-[9px] font-semibold text-emerald-200"
                                >
                                  {ov === 'adaptive_layers'
                                    ? 'Capa Adaptativa'
                                    : ov === 'dense_support_interface'
                                      ? 'Soportes Anti-Cicatriz'
                                      : ov === 'high_contrast_purge'
                                        ? 'Purga 1.35×'
                                        : 'Acabado Completo'}
                                </span>
                              ))}
                            </div>
                            {onClearAiQualityOverrides && (
                              <button
                                type="button"
                                onClick={onClearAiQualityOverrides}
                                className="text-[9px] text-slate-400 hover:text-slate-200"
                              >
                                Limpiar
                              </button>
                            )}
                          </div>
                          <button
                            type="button"
                            disabled={isSlicing || isOptimizingSliceAI}
                            onClick={() => onSlice()}
                            className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-emerald-500 px-2.5 py-1.5 text-[11px] font-bold text-slate-950 transition hover:bg-emerald-400 disabled:opacity-50"
                          >
                            <Sparkles className="h-3.5 w-3.5" />
                            Re-laminar con Mejora Seleccionada
                          </button>
                        </div>
                      )}
                    </div>
                  )}

                <div className="space-y-1.5">
                  {(() => {
                    const groupsToShow =
                      showAllResolutions && aiAnalysisResult.all_layer_resolutions?.length
                        ? aiAnalysisResult.all_layer_resolutions
                        : aiAnalysisResult.layer_resolutions;
                    return groupsToShow && groupsToShow.length > 0 ? (
                      groupsToShow.map((group) => {
                      const isGroupOpen = expandedLayerHeight === group.layer_height;
                      return (
                        <div
                          key={group.layer_height}
                          className={`rounded-lg border transition ${
                            group.is_recommended
                              ? 'border-cyan-500/45 bg-slate-900/95'
                              : 'border-slate-800 bg-slate-900/75'
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedLayerHeight((prev) =>
                                prev === group.layer_height ? null : group.layer_height,
                              )
                            }
                            className="flex w-full items-center justify-between gap-2 px-2.5 py-1.5 text-left"
                          >
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="font-mono text-[11px] font-bold text-cyan-300">
                                  {group.layer_height.toFixed(2)} mm
                                </span>
                                <span className="text-[11px] font-semibold text-slate-100">
                                  {group.title}
                                </span>
                                {group.is_recommended && (
                                  <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-emerald-200">
                                    Recomendado IA
                                  </span>
                                )}
                              </div>
                              <p className="truncate text-[9px] text-slate-400">
                                {group.subtitle} · {group.calibrated_speed_mms} mm/s ·{' '}
                                {group.calibrated_temp_c}°C
                              </p>
                            </div>
                            <div className="flex shrink-0 items-center gap-1.5">
                              <span className="font-mono text-[10px] font-semibold text-amber-200">
                                {group.estimated_time_str}
                              </span>
                              {isGroupOpen ? (
                                <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
                              ) : (
                                <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                              )}
                            </div>
                          </button>

                          {isGroupOpen && (
                            <div className="space-y-1 border-t border-slate-800/80 px-2 py-1.5">
                              {group.options.map((sub) => (
                                <button
                                  key={sub.id}
                                  type="button"
                                  disabled={isOptimizingSliceAI || isSlicing}
                                  onClick={() => {
                                    setInstantOverlayMode('ai_optimize');
                                    onOptimizeSliceWithAI(
                                      sub.preset_id,
                                      aiUserNotes,
                                      sub.layer_height,
                                    );
                                  }}
                                  className="flex w-full flex-col items-start rounded-md border border-slate-800 bg-slate-950/85 px-2 py-1 text-left transition hover:border-cyan-500/50 hover:bg-cyan-500/10 disabled:opacity-45"
                                >
                                  <div className="flex w-full items-center justify-between gap-1">
                                    <span className="text-[10px] font-semibold text-slate-100">
                                      {sub.label}
                                    </span>
                                    <span className="font-mono text-[9px] font-semibold text-cyan-300">
                                      {sub.calibrated_speed_mms} mm/s · {sub.calibrated_temp_c}°C ·{' '}
                                      {sub.estimated_time_str}
                                    </span>
                                  </div>
                                  <span className="text-[9px] text-slate-400">
                                    {sub.description}
                                  </span>
                                </button>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })
                  ) : null;
                  })()}
                  {!lithophaneMode &&
                    aiAnalysisResult.model_category !== 'lithophane_flat' &&
                    aiAnalysisResult.all_layer_resolutions &&
                    aiAnalysisResult.all_layer_resolutions.length >
                      (aiAnalysisResult.layer_resolutions?.length ?? 0) && (
                      <button
                        type="button"
                        onClick={() => setShowAllResolutions((prev) => !prev)}
                        className="w-full pt-0.5 text-center text-[10px] font-medium text-slate-400 underline hover:text-cyan-300"
                      >
                        {showAllResolutions
                          ? 'Ocultar resoluciones fuera de categoría'
                          : 'Ver todas las resoluciones (0.08–0.28 mm)'}
                      </button>
                    )}
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setIsAiPresetsExpanded(true)}
                className="flex w-full items-center justify-between gap-2 rounded-xl border border-cyan-500/35 bg-slate-950/90 px-2.5 py-1.5 text-left text-[10px] transition hover:border-cyan-400/60"
              >
                <span className="truncate font-semibold text-cyan-200">
                  Estrategia aplicada:{' '}
                  <strong className="text-white">
                    {aiOptimizeComparison?.strategyLabel || 'Personalizada'}
                  </strong>
                </span>
                <span className="shrink-0 font-semibold text-violet-300">
                  Cambiar opción ▼
                </span>
              </button>
            )
          )}

          {aiOptimizeComparison && (
            <div
              ref={aiResultRef}
              className="space-y-2 rounded-xl border border-violet-500/40 bg-violet-950/20 p-2.5 text-[10px]"
            >
              <div className="flex items-center justify-between gap-1">
                <span className="font-bold text-violet-200">
                  {aiOptimizeComparison.strategyLabel}
                </span>
                <span className="font-mono text-[9px] text-emerald-300">
                  Capa {aiOptimizeComparison.after.layerHeight}mm
                  {aiOptimizeComparison.after.fuzzySkin ? ' · Piel Difusa' : ''}
                </span>
              </div>
              <p className="leading-snug text-slate-300">{aiOptimizeComparison.explanation}</p>
              <div className="grid grid-cols-2 gap-1.5 rounded-lg bg-slate-950/75 p-1.5 font-mono text-[9px]">
                <div>
                  <p className="text-slate-400">Laminado Inicial</p>
                  <p className="text-slate-200">
                    {aiOptimizeComparison.before.time} · {aiOptimizeComparison.before.grams}g
                  </p>
                  <p className="text-slate-400">
                    Sop: {aiOptimizeComparison.before.supportGrams}g · {aiOptimizeComparison.before.rot}
                  </p>
                </div>
                <div>
                  <p className="text-emerald-300">Optimizado IA</p>
                  <p className="font-bold text-white">
                    {aiOptimizeComparison.after.time} · {aiOptimizeComparison.after.grams}g
                  </p>
                  <p className="text-cyan-300">
                    Sop: {aiOptimizeComparison.after.supportGrams}g · {aiOptimizeComparison.after.rot}
                  </p>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-1.5">
                {canRollbackInitialSlice && (
                  <button
                    type="button"
                    onClick={onRollbackToInitialSlice}
                    className="rounded-lg border border-amber-500/45 bg-amber-500/15 px-2 py-1 font-semibold text-amber-100 hover:bg-amber-500/25"
                  >
                    Volver al laminado inicial
                  </button>
                )}
                <button
                  type="button"
                  onClick={onRollbackToUnsliced}
                  className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 font-semibold text-slate-200 hover:bg-slate-700"
                >
                  Volver al inicio sin laminar
                </button>
              </div>
            </div>
          )}
        </div>

        {isSlicing && (
          <div className="mt-2 space-y-1.5">
            <div className="overflow-hidden rounded-full bg-slate-800">
              <div className="h-1.5 w-2/3 animate-pulse rounded-full bg-cyan-400" />
            </div>
            {onCancelSlice && (
              <button
                type="button"
                onClick={onCancelSlice}
                className="w-full rounded-lg border border-rose-500/40 bg-rose-500/15 py-1 text-[11px] font-semibold text-rose-200 hover:bg-rose-500/25"
              >
                Cancelar laminado
              </button>
            )}
          </div>
        )}

        {errorMsg && (
          <div className="mt-2 max-h-20 overflow-y-auto rounded-lg border border-rose-500/50 bg-rose-500/15 p-2 text-[11px] text-rose-200">
            {errorMsg}
          </div>
        )}

        {/* Gestor de Pausas Programadas por Capa */}
        <div className="mt-2.5 space-y-2 rounded-xl border border-amber-500/25 bg-slate-950/70 p-2.5">
          <div className="flex items-center justify-between">
            <span className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-200">
              <Pause className="h-3.5 w-3.5 text-amber-400" />
              {t.step4.scheduledPauses}
            </span>
            <span className="font-mono text-[10px] text-slate-400">
              {layerPauses.length} activa(s)
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <input
              type="number"
              min={1}
              value={pauseLayerInput}
              onChange={(e) => setPauseLayerInput(e.target.value)}
              placeholder="Capa"
              className="w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100"
            />
            <input
              type="text"
              value={pauseNoteInput}
              onChange={(e) => setPauseNoteInput(e.target.value)}
              placeholder="Nota (ej. Insertar imán)"
              className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-slate-100 placeholder:text-slate-500"
            />
            <button
              type="button"
              onClick={() => {
                const ln = Math.max(1, Math.round(Number(pauseLayerInput) || 1));
                onAddLayerPause(ln, null, pauseNoteInput.trim());
                setPauseNoteInput('');
              }}
              className="flex shrink-0 items-center gap-1 rounded-lg border border-amber-500/45 bg-amber-500/15 px-2 py-1 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/25"
            >
              <Plus className="h-3 w-3" />
              Añadir
            </button>
          </div>
          {layerPauses.length > 0 && (
            <div className="space-y-1">
              {layerPauses.map((p) => (
                <div
                  key={p.layer}
                  className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/90 px-2 py-1 text-[10px]"
                >
                  <div className="flex min-w-0 items-center gap-1.5">
                    <span className="font-mono font-bold text-amber-300">
                      Capa {p.layer}
                    </span>
                    {p.z_mm != null && (
                      <span className="font-mono text-slate-400">
                        (Z {Number(p.z_mm).toFixed(1)}mm)
                      </span>
                    )}
                    {p.note && (
                      <span className="truncate text-slate-300">· {p.note}</span>
                    )}
                    {p.source === 'auto_multicolor' && (
                      <span className="rounded bg-fuchsia-500/20 px-1 py-0.5 text-[9px] text-fuchsia-200">
                        Auto M25
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => onRemoveLayerPause(p.layer)}
                    title="Eliminar pausa"
                    className="text-slate-400 hover:text-rose-400"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {sliceResult && !isSlicing && (
          <div className="mt-2.5 space-y-2 rounded-xl border border-emerald-500/35 bg-emerald-500/5 p-2.5">
            <div className="flex items-center justify-between gap-2">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Laminado listo
              </span>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  disabled={!effectiveProfileSnapshot}
                  onClick={() => {
                    if (effectiveProfileSnapshot) setProfileDrawerOpen(true);
                  }}
                  className={`flex items-center gap-1 rounded-lg border px-2 py-0.5 text-[10px] font-semibold transition ${
                    effectiveProfileSnapshot
                      ? 'border-cyan-500/45 bg-cyan-500/15 text-cyan-200 hover:bg-cyan-500/25'
                      : 'cursor-not-allowed border-slate-700/60 bg-slate-900/50 text-slate-500 opacity-50'
                  }`}
                  title={
                    effectiveProfileSnapshot
                      ? t.profileInspector.savedBadge
                      : t.profileInspector.disabledTooltip
                  }
                >
                  <SlidersHorizontal className="h-3 w-3" />
                  <span>{t.profileInspector.buttonLabel}</span>
                </button>
                <span className="font-mono text-[10px] text-slate-400">
                  {sliceResult.job_id}
                </span>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-1.5 text-center">
              <div className="rounded-lg bg-slate-950/70 p-1.5">
                <Clock className="mx-auto mb-0.5 h-3 w-3 text-cyan-400" />
                <p className="font-mono text-[11px] font-bold text-slate-100">
                  {sliceResult.estimated_time}
                </p>
              </div>
              <div className="rounded-lg bg-slate-950/70 p-1.5">
                <Layers className="mx-auto mb-0.5 h-3 w-3 text-orange-400" />
                <p className="font-mono text-[11px] font-bold text-slate-100">
                  {sliceResult.filament_grams} g
                </p>
              </div>
              <div className="rounded-lg bg-slate-950/70 p-1.5">
                <Ruler className="mx-auto mb-0.5 h-3 w-3 text-emerald-400" />
                <p className="font-mono text-[11px] font-bold text-slate-100">
                  {sliceResult.filament_meters} m
                </p>
              </div>
            </div>

            {(sliceResult.supports_enabled || sliceResult.support_z_distance != null) && (
              <div className="flex flex-wrap items-center justify-between gap-1 rounded-lg border border-cyan-500/25 bg-slate-950/75 px-2.5 py-1.5 text-[10px]">
                <span className="font-semibold text-cyan-200">
                  Soportes {sliceResult.support_type ? `(${sliceResult.support_type})` : ''}
                  {sliceResult.support_weight_g
                    ? ` · ${sliceResult.support_weight_g} g (${sliceResult.support_percentage ?? 0}%)`
                    : ''}
                </span>
                <span className="font-mono text-emerald-300">
                  Z: {sliceResult.support_z_distance != null ? `${sliceResult.support_z_distance.toFixed(2)} mm` : '—'} · X/Y:{' '}
                  {sliceResult.support_xy_distance != null ? `${sliceResult.support_xy_distance.toFixed(2)} mm` : '—'}
                </span>
              </div>
            )}

            {/* Desglose de costos en tiempo real (sincronizado con Calculadora Comercial) */}
            <div className="rounded-lg border border-emerald-500/25 bg-slate-950/80 px-2.5 py-1.5 text-[11px]">
              <div className="flex items-center justify-between text-slate-400">
                <span>Filamento: {formatPesos(materialCost)}</span>
                <span>Energía ({activePrinterWatts}W): {formatPesos(energyCost)}</span>
              </div>
              <div className="mt-1 flex items-center justify-between border-t border-slate-800 pt-1">
                <span className="font-semibold text-slate-200">
                  Solo Filamento y Energía
                </span>
                <span className="font-mono text-xs font-bold text-emerald-300">
                  {formatPesos(totalCost)}
                </span>
              </div>
            </div>

            <button
              type="button"
              onClick={() => setQuoteModalOpen(true)}
              className="flex w-full items-center justify-center gap-2 rounded-xl border border-amber-500/50 bg-gradient-to-r from-amber-500/20 to-emerald-500/20 px-3 py-2 text-xs font-semibold text-amber-200 transition hover:border-amber-400 hover:from-amber-500/30 hover:to-emerald-500/30"
            >
              <Calculator className="h-3.5 w-3.5 text-amber-300" />
              {t.step4.saleCalculator}
            </button>

            {layerPauses.length > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[10px] text-amber-200">
                <span className="font-semibold">
                  {layerPauses.length} Pausa{layerPauses.length === 1 ? '' : 's'} programada
                  {layerPauses.length === 1 ? '' : 's'}:{' '}
                </span>
                {layerPauses
                  .map((p) => {
                    const slotSuffix = p.slot != null ? ` (T${p.slot})` : '';
                    const zSuffix = p.z_mm != null && p.slot == null ? ` (Z ${Number(p.z_mm).toFixed(1)}mm)` : '';
                    return `Capa ${p.layer}${slotSuffix}${zSuffix}`;
                  })
                  .join(' · ')}
              </div>
            )}

            {/* Selector USB Serial vs SD /Volumes/ para Ender 3 S1 Pro y FLSUN Super Racer */}
            {isUsbOrSdPrinter && (
              <div className="space-y-1.5 rounded-lg border border-slate-800 bg-slate-950/70 p-2">
                <div className="grid grid-cols-2 gap-1">
                  <button
                    type="button"
                    onClick={() => setEnderMode('sd_volume')}
                    className={`flex items-center justify-center gap-1 rounded-md border py-1 text-[10px] font-semibold ${
                      enderMode === 'sd_volume'
                        ? 'border-emerald-500 bg-emerald-500/20 text-emerald-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400'
                    }`}
                  >
                    <HardDrive className="h-3 w-3" />
                    Guardar en SD
                  </button>
                  <button
                    type="button"
                    onClick={() => setEnderMode('usb_serial')}
                    className={`flex items-center justify-center gap-1 rounded-md border py-1 text-[10px] font-semibold ${
                      enderMode === 'usb_serial'
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400'
                    }`}
                  >
                    <Usb className="h-3 w-3" />
                    USB Serial
                  </button>
                </div>
                {enderMode === 'sd_volume' && (
                  <input
                    type="text"
                    list="wizard-sd-volumes"
                    value={effectiveSdPath}
                    onChange={(e) => setSelectedSdPath(e.target.value)}
                    placeholder="/Volumes/SD_CARD (o carpeta)"
                    className="w-full rounded border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[10px] text-slate-200"
                  />
                )}
                <datalist id="wizard-sd-volumes">
                  {detectedVolumes.map((v) => (
                    <option key={v} value={v} />
                  ))}
                </datalist>
              </div>
            )}

            {isUsbOrSdPrinter ? (
              <div className="grid grid-cols-2 gap-1.5">
                <button
                  type="button"
                  onClick={() =>
                    void triggerFileDownload(
                      getGcodeUrl(sliceResult.gcode_url),
                      `slicerhub_${sliceResult.job_id}.gcode`,
                    )
                  }
                  className="flex items-center justify-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/15 px-2.5 py-2 text-xs font-semibold text-emerald-200 transition hover:bg-emerald-500/25"
                >
                  <Download className="h-3.5 w-3.5" />
                  Descargar
                </button>
                <button
                  type="button"
                  disabled={uploadActionMode !== null}
                  onClick={() =>
                    onSendToPrinter(
                      enderMode,
                      enderMode === 'sd_volume' ? effectiveSdPath : undefined,
                      true,
                    )
                  }
                  className="flex items-center justify-center gap-1.5 rounded-xl border border-cyan-500/50 bg-cyan-500/20 px-2.5 py-2 text-xs font-semibold text-cyan-100 transition hover:bg-cyan-500/30 disabled:opacity-50"
                >
                  {uploadActionMode === 'upload_and_print' ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Send className="h-3.5 w-3.5" />
                  )}
                  {enderMode === 'sd_volume' ? 'Guardar en SD' : 'Imprimir USB'}
                </button>
              </div>
            ) : (
              <div className="space-y-1.5">
                <div className="grid grid-cols-2 gap-1.5">
                  <button
                    type="button"
                    disabled={uploadActionMode !== null}
                    onClick={() =>
                      setPendingOutputAction((cur) =>
                        cur === 'upload_only' ? null : 'upload_only',
                      )
                    }
                    className="flex items-center justify-center gap-1 rounded-xl border border-indigo-500/45 bg-indigo-500/15 px-2 py-2 text-[11px] font-semibold text-indigo-100 transition hover:bg-indigo-500/25 disabled:opacity-50"
                  >
                    {uploadActionMode === 'upload_only' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Upload className="h-3.5 w-3.5" />
                    )}
                    {t.step4.uploadOnly}
                  </button>
                  <button
                    type="button"
                    disabled={uploadActionMode !== null}
                    onClick={() =>
                      setPendingOutputAction((cur) =>
                        cur === 'upload_and_print' ? null : 'upload_and_print',
                      )
                    }
                    className="flex items-center justify-center gap-1 rounded-xl border border-cyan-500/50 bg-cyan-500/20 px-2 py-2 text-[11px] font-semibold text-cyan-100 transition hover:bg-cyan-500/30 disabled:opacity-50"
                  >
                    {uploadActionMode === 'upload_and_print' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Send className="h-3.5 w-3.5" />
                    )}
                    {t.step4.uploadAndPrint}
                  </button>
                </div>

                <button
                  type="button"
                  disabled={uploadActionMode !== null}
                  onClick={() =>
                    setPendingOutputAction((cur) =>
                      cur === 'download' ? null : 'download',
                    )
                  }
                  className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-emerald-500/35 bg-emerald-500/10 py-1.5 text-[11px] font-semibold text-emerald-200 transition hover:bg-emerald-500/20"
                >
                  <Download className="h-3.5 w-3.5" />
                  {selectedProfileId === 'creator5_pro'
                    ? 'Descargar G-code (.gcode / .gcode.3mf)'
                    : 'Descargar G-code (.gcode)'}
                </button>

                {pendingOutputAction && (
                  <div className="space-y-2 rounded-xl border border-amber-500/40 bg-slate-950/95 p-2.5 text-[10px]">
                    <div>
                      <label className="mb-1 block font-semibold text-slate-200">
                        Nombre del archivo G-code
                      </label>
                      <div className="flex items-center overflow-hidden rounded-lg border border-slate-700 bg-slate-900">
                        <input
                          type="text"
                          value={customBaseName}
                          onChange={(e) =>
                            setCustomBaseName(
                              e.target.value.replace(/[^A-Za-z0-9_-]+/g, '_'),
                            )
                          }
                          placeholder="mi_modelo"
                          className="min-w-0 flex-1 bg-transparent px-2 py-1 font-mono text-[11px] text-slate-100 outline-none"
                        />
                        <span className="border-l border-slate-700 bg-slate-800 px-2 py-1 font-mono text-[11px] font-semibold text-cyan-300">
                          {pendingOutputAction === 'download' &&
                          selectedProfileId === 'creator5_pro' &&
                          downloadFormat === 'gcode.3mf'
                            ? '.gcode.3mf'
                            : '.gcode'}
                        </span>
                      </div>
                    </div>

                    {pendingOutputAction === 'download' && selectedProfileId === 'creator5_pro' && (
                      <div className="grid grid-cols-2 gap-1.5">
                        <button
                          type="button"
                          onClick={() => setDownloadFormat('gcode.3mf')}
                          className={`rounded-lg border px-2 py-1 font-semibold transition ${
                            downloadFormat === 'gcode.3mf'
                              ? 'border-emerald-500/70 bg-emerald-500/20 text-emerald-200'
                              : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'
                          }`}
                        >
                          .gcode.3mf (Flash Studio)
                        </button>
                        <button
                          type="button"
                          onClick={() => setDownloadFormat('gcode')}
                          className={`rounded-lg border px-2 py-1 font-semibold transition ${
                            downloadFormat === 'gcode'
                              ? 'border-cyan-500/70 bg-cyan-500/20 text-cyan-200'
                              : 'border-slate-700 bg-slate-900 text-slate-400 hover:text-slate-200'
                          }`}
                        >
                          .gcode estándar
                        </button>
                      </div>
                    )}

                    {pendingOutputAction === 'upload_and_print' ? (
                      <div className="space-y-1.5">
                        <p className="font-semibold text-amber-200">
                          ¿Ejecutar nivelación/calibración antes de imprimir?
                        </p>
                        <div className="grid grid-cols-2 gap-1.5">
                          <button
                            type="button"
                            disabled={uploadActionMode !== null}
                            onClick={() => {
                              const clean =
                                customBaseName.replace(/^_+|_+$/g, '') ||
                                `slicerhub_${sliceResult.job_id}`;
                              setPendingOutputAction(null);
                              onToggleAutoLeveling(false);
                              onSendToPrinter('network', undefined, true, false, clean);
                            }}
                            className="rounded-lg border border-cyan-500/50 bg-cyan-500/20 px-2 py-1.5 font-semibold text-cyan-100 hover:bg-cyan-500/30 disabled:opacity-50"
                          >
                            Imprimir directo (Sin calibrar)
                          </button>
                          <button
                            type="button"
                            disabled={uploadActionMode !== null}
                            onClick={() => {
                              const clean =
                                customBaseName.replace(/^_+|_+$/g, '') ||
                                `slicerhub_${sliceResult.job_id}`;
                              setPendingOutputAction(null);
                              onToggleAutoLeveling(true);
                              onSendToPrinter('network', undefined, true, true, clean);
                            }}
                            className="rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-2 py-1.5 font-semibold text-emerald-100 hover:bg-emerald-500/30 disabled:opacity-50"
                          >
                            Calibrar e Imprimir
                          </button>
                        </div>
                      </div>
                    ) : pendingOutputAction === 'upload_only' ? (
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => setPendingOutputAction(null)}
                          className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 font-semibold text-slate-300"
                        >
                          Cancelar
                        </button>
                        <button
                          type="button"
                          disabled={uploadActionMode !== null}
                          onClick={() => {
                            const clean =
                              customBaseName.replace(/^_+|_+$/g, '') ||
                              `slicerhub_${sliceResult.job_id}`;
                            setPendingOutputAction(null);
                            onSendToPrinter('network', undefined, false, undefined, clean);
                          }}
                          className="rounded-lg border border-indigo-500/60 bg-indigo-500/25 px-3 py-1 font-semibold text-indigo-100 hover:bg-indigo-500/35"
                        >
                          Confirmar Subida
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          type="button"
                          onClick={() => setPendingOutputAction(null)}
                          className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 font-semibold text-slate-300"
                        >
                          Cancelar
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            const cleanName =
                              customBaseName.replace(/^_+|_+$/g, '') ||
                              `slicerhub_${sliceResult.job_id}`;
                            const isC5P = selectedProfileId === 'creator5_pro';
                            setPendingOutputAction(null);
                            if (isC5P && downloadFormat === 'gcode.3mf') {
                              const ffUrl = `${API_BASE_URL}/export/${encodeURIComponent(sliceResult.job_id)}/flashforge-3mf?object_name=${encodeURIComponent(cleanName)}`;
                              void triggerFileDownload(ffUrl, `${cleanName}.gcode.3mf`);
                              return;
                            }
                            const baseUrl = getGcodeUrl(sliceResult.gcode_url, cleanName);
                            const sep = baseUrl.includes('?') ? '&' : '?';
                            const dlUrl = isC5P ? `${baseUrl}${sep}format=flashforge` : baseUrl;
                            void triggerFileDownload(dlUrl, `${cleanName}.gcode`);
                          }}
                          className="rounded-lg border border-emerald-500/60 bg-emerald-500/25 px-3 py-1 font-semibold text-emerald-100 hover:bg-emerald-500/35"
                        >
                          Confirmar Descarga
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            {sendPrintMsg && (
              <p className="rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-2 py-1 text-[10px] text-cyan-200">
                {sendPrintMsg}
              </p>
            )}
          </div>
        )}
        </div>
        )}
      </section>
      </div>

      {projectsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="flex max-h-[85vh] w-full max-w-2xl flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
            <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
              <div>
                <h3 className="text-sm font-bold text-white">
                  {projectsModalTab === 'saved'
                    ? 'Proyectos Guardados'
                    : 'Diagnóstico Post-Impresión'}
                </h3>
                <p className="text-[11px] text-slate-400">
                  {projectsModalTab === 'saved'
                    ? 'Abre un proyecto completo guardado con su modelo 3D, perfiles y parámetros.'
                    : 'Recarga parámetros de laminados previos o corrige defectos físicos con DeepSeek IA.'}
                </p>
              </div>
              <button
                type="button"
                onClick={() => {
                  setProjectsModalOpen(false);
                  onChangeExternalProjectsOpen?.(false);
                }}
                className="rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs font-semibold text-slate-200 hover:bg-slate-700"
              >
                Cerrar
              </button>
            </div>

            <div className="flex gap-1.5 border-b border-slate-800/80 bg-slate-950/50 px-4 py-2">
              <button
                type="button"
                onClick={() => setProjectsModalTab('saved')}
                className={`rounded-lg border px-3 py-1 text-[11px] font-semibold transition ${
                  projectsModalTab === 'saved'
                    ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-200'
                    : 'border-slate-800 bg-slate-900/70 text-slate-400 hover:text-slate-200'
                }`}
              >
                Proyectos Guardados ({recentProjects.length})
              </button>
              <button
                type="button"
                onClick={() => setProjectsModalTab('diagnostics')}
                className={`rounded-lg border px-3 py-1 text-[11px] font-semibold transition ${
                  projectsModalTab === 'diagnostics'
                    ? 'border-amber-500/60 bg-amber-500/15 text-amber-200'
                    : 'border-slate-800 bg-slate-900/70 text-slate-400 hover:text-slate-200'
                }`}
              >
                Diagnóstico Post-Impresión ({savedProjects.length})
              </button>
            </div>

            <div className="flex-1 space-y-3 overflow-y-auto p-4">
              {projectsModalTab === 'saved' ? (
                recentProjects.length === 0 ? (
                  <p className="py-8 text-center text-xs text-slate-400">
                    Aún no tienes proyectos completos guardados. Al laminar o guardar un proyecto aparecerá aquí.
                  </p>
                ) : (
                  <div className="space-y-2">
                    {recentProjects.slice(0, visibleRecentLimit).map((rp) => (
                      <div
                        key={rp.project_id}
                        className="flex items-center gap-3 rounded-xl border border-cyan-500/25 bg-slate-950/85 p-2.5 text-xs"
                      >
                        <div className="h-14 w-16 shrink-0 overflow-hidden rounded-lg border border-slate-800 bg-slate-900">
                          {rp.thumbnail_url ? (
                            <img
                              src={rp.thumbnail_url}
                              alt={rp.title}
                              className="h-full w-full object-cover"
                            />
                          ) : (
                            <div className="flex h-full w-full items-center justify-center text-[10px] text-slate-600">
                              3D
                            </div>
                          )}
                        </div>
                        <div className="min-w-0 flex-1 space-y-0.5">
                          <p className="truncate text-xs font-bold text-slate-100">
                            {rp.title}
                          </p>
                          <p className="truncate font-mono text-[10px] text-slate-400">
                            {rp.original_filename} ·{' '}
                            {rp.updated_at ? new Date(rp.updated_at).toLocaleString() : ''}
                          </p>
                          <p className="font-mono text-[10px] text-cyan-300">
                            {rp.printer_id} · {String(rp.material || 'pla').toUpperCase()}
                            {rp.slice_metrics?.estimated_time
                              ? ` · ${rp.slice_metrics.estimated_time}`
                              : ''}
                            {rp.slice_metrics?.filament_grams
                              ? ` · ${rp.slice_metrics.filament_grams}g`
                              : ''}
                          </p>
                        </div>
                        <div className="flex shrink-0 flex-col gap-1 sm:flex-row">
                          <button
                            type="button"
                            onClick={() => {
                              onLoadFullProject?.(rp.project_id);
                              setProjectsModalOpen(false);
                              onChangeExternalProjectsOpen?.(false);
                            }}
                            className="rounded-lg border border-cyan-500/45 bg-cyan-500/15 px-2.5 py-1 text-[10px] font-semibold text-cyan-100 hover:bg-cyan-500/25"
                          >
                            Abrir aquí
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              onOpenProjectNewWindow?.(rp.project_id);
                              setProjectsModalOpen(false);
                              onChangeExternalProjectsOpen?.(false);
                            }}
                            className="flex items-center gap-1 rounded-lg border border-emerald-500/45 bg-emerald-500/15 px-2.5 py-1 text-[10px] font-semibold text-emerald-100 hover:bg-emerald-500/25"
                          >
                            <ExternalLink className="h-3 w-3" />
                            Nueva ventana
                          </button>
                          {onDeleteFullProject && (
                            <button
                              type="button"
                              onClick={() => onDeleteFullProject(rp.project_id)}
                              title="Eliminar proyecto"
                              className="rounded-lg border border-slate-700 bg-slate-900 px-1.5 py-1 text-slate-400 hover:border-rose-500/50 hover:text-rose-300"
                            >
                              <X className="h-3.5 w-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    ))}
                    {(recentProjects.length > visibleRecentLimit || (visibleRecentLimit > 10 && recentProjects.length > 10)) && (
                      <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
                        <span className="text-[11px] text-slate-400">
                          Mostrando {Math.min(visibleRecentLimit, recentProjects.length)} de {recentProjects.length} proyectos
                        </span>
                        <div className="flex items-center gap-2">
                          {visibleRecentLimit < recentProjects.length && (
                            <>
                              <button
                                type="button"
                                onClick={() => setVisibleRecentLimit((prev) => prev + 10)}
                                className="rounded-lg border border-cyan-500/45 bg-cyan-500/15 px-3 py-1 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
                              >
                                Ver {Math.min(10, recentProjects.length - visibleRecentLimit)} más
                              </button>
                              <button
                                type="button"
                                onClick={() => setVisibleRecentLimit(recentProjects.length)}
                                className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1 text-[11px] font-semibold text-slate-200 hover:bg-slate-700"
                              >
                                Ver todos ({recentProjects.length})
                              </button>
                            </>
                          )}
                          {visibleRecentLimit > 10 && recentProjects.length > 10 && (
                            <button
                              type="button"
                              onClick={() => setVisibleRecentLimit(10)}
                              className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1 text-[11px] font-semibold text-slate-300 hover:bg-slate-800"
                            >
                              Mostrar últimos 10
                            </button>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )
              ) : isLoadingProjects ? (
                <div className="flex items-center justify-center gap-2 py-8 text-xs text-slate-400">
                  <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
                  Cargando proyectos...
                </div>
              ) : savedProjects.length === 0 ? (
                <p className="py-8 text-center text-xs text-slate-400">
                  Aún no hay registros de laminado para diagnóstico en esta sesión.
                </p>
              ) : (
                savedProjects.map((proj) => (
                  <div
                    key={proj.project_id}
                    className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/75 p-3 text-xs"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="min-w-0">
                        <p className="truncate font-semibold text-slate-100">
                          {proj.model_filename}{' '}
                          <span className="font-mono text-[10px] text-cyan-300">
                            ({proj.project_id})
                          </span>
                        </p>
                        <p className="font-mono text-[10px] text-slate-400">
                          {proj.printer_id} · {proj.material.toUpperCase()} · {proj.metrics?.estimated_time || '—'} ·{' '}
                          {proj.metrics?.filament_grams ?? 0}g · {proj.ai_strategy || 'Estándar'}
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => {
                            onLoadSavedProject(proj);
                            setProjectsModalOpen(false);
                          }}
                          className="rounded-lg border border-cyan-500/45 bg-cyan-500/15 px-2 py-1 text-[10px] font-semibold text-cyan-100 hover:bg-cyan-500/25"
                        >
                          Cargar parámetros
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setDefectTargetProj(
                              defectTargetProj?.project_id === proj.project_id ? null : proj,
                            );
                            setDefectResult(null);
                          }}
                          className="rounded-lg border border-amber-500/45 bg-amber-500/15 px-2 py-1 text-[10px] font-semibold text-amber-100 hover:bg-amber-500/25"
                        >
                          Corregir defecto
                        </button>
                      </div>
                    </div>

                    {defectTargetProj?.project_id === proj.project_id && (
                      <div className="space-y-2 border-t border-slate-800 pt-2">
                        <div className="flex flex-wrap gap-1">
                          {[
                            'Líneas gruesas / banding en una cara',
                            'Cicatrices o marcas de soporte',
                            'Hilos / stringing',
                            'Capa inicial despegada',
                            'Vibración / ringing',
                          ].map((chip) => (
                            <button
                              key={chip}
                              type="button"
                              onClick={() => setDefectText(chip)}
                              className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[9px] text-slate-300 hover:border-amber-400 hover:text-amber-200"
                            >
                              {chip}
                            </button>
                          ))}
                        </div>
                        <div className="flex gap-1.5">
                          <input
                            type="text"
                            value={defectText}
                            onChange={(e) => setDefectText(e.target.value)}
                            placeholder="Describe el defecto físico observado..."
                            className="min-w-0 flex-1 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] text-white outline-none focus:border-amber-400"
                          />
                          <button
                            type="button"
                            disabled={isDiagnosingDefect || defectText.trim().length < 2}
                            onClick={async () => {
                              setInstantOverlayMode('ai_analyze');
                              setIsDiagnosingDefect(true);
                              setDefectResult(null);
                              try {
                                const res = await requestAIDefectDiagnose({
                                  project_id: proj.project_id,
                                  project_data: proj as unknown as Record<string, unknown>,
                                  defect_description: defectText.trim(),
                                });
                                setDefectResult(res);
                              } finally {
                                setIsDiagnosingDefect(false);
                              }
                            }}
                            className="rounded-lg border border-amber-500/60 bg-amber-500/25 px-3 py-1 text-[11px] font-semibold text-amber-100 hover:bg-amber-500/35 disabled:opacity-40"
                          >
                            {isDiagnosingDefect ? 'Analizando...' : 'Diagnosticar IA'}
                          </button>
                        </div>

                        {defectResult && (
                          <div className="space-y-1.5 rounded-lg border border-emerald-500/35 bg-emerald-950/20 p-2 text-[10px]">
                            <p className="font-semibold text-amber-200">
                              Causa raíz: {defectResult.root_cause}
                            </p>
                            <p className="text-slate-200">{defectResult.explanation}</p>
                            <button
                              type="button"
                              onClick={() => {
                                setInstantOverlayMode('slicing');
                                setProjectsModalOpen(false);
                                onApplyDefectCorrection(proj, defectResult.corrected_params);
                              }}
                              className="rounded-lg border border-emerald-500/60 bg-emerald-500/25 px-2.5 py-1 font-semibold text-emerald-100 hover:bg-emerald-500/35"
                            >
                              Aplicar corrección y re-laminar
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}

      <QuoteCalculatorModal
        open={quoteModalOpen}
        onClose={() => setQuoteModalOpen(false)}
        initialData={
          sliceResult
            ? {
                modelName: stlFile?.name,
                printerProfileId: selectedProfileId,
                printerName: selectedPrinter?.display_name || selectedPrinterId,
                material,
                hours: Math.floor(Math.max(0, Math.round(estHours * 3600)) / 3600),
                minutes: Math.floor((Math.max(0, Math.round(estHours * 3600)) % 3600) / 60),
                grams: sliceResult.filament_grams,
                filamentPricePerKg:
                  costs.spoolWeightGrams > 0
                    ? Math.round((costs.spoolCostPesos / costs.spoolWeightGrams) * 1000)
                    : 100000,
              }
            : null
        }
      />

      <GlobalProcessingOverlay
        active={overlayActive}
        mode={rawOverlayMode ?? lastOverlayMode}
        printerName={selectedPrinter?.display_name || selectedPrinterId}
        printerIp={selectedPrinter?.ip || ''}
        fileSizeMb={(stlFile?.size ?? 0) / (1024 * 1024)}
        triangleCount={analysis?.triangle_count ?? 0}
        layerHeightMm={qualityPreset === 'rapidez_extrema' ? 0.24 : 0.2}
      />

      {effectiveProfileSnapshot && (
        <ProfileInspectorDrawer
          open={profileDrawerOpen}
          onClose={() => setProfileDrawerOpen(false)}
          snapshot={effectiveProfileSnapshot}
          projectTitle={stlFile?.name || 'Proyecto 3D'}
          isSlicing={isSlicing}
          onApplyAndReslice={async (ov) => {
            await onApplyProfileAndReslice?.(ov);
          }}
        />
      )}
    </div>
  );
}
