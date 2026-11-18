import { useEffect, useMemo, useState, type ChangeEvent, type DragEvent } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  DollarSign,
  Download,
  FileUp,
  Flame,
  Gauge,
  HardDrive,
  Layers,
  Loader2,
  Palette,
  Play,
  Plus,
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
  Zap,
} from 'lucide-react';
import {
  fetchTelemetryLearnings,
  getGcodeUrl,
  type AISupportOrientResponse,
  type AdhesionType,
  type ExtruderSlotConfig,
  type MachineMaterialLearningsResponse,
  type MaterialType,
  type MeshAnalysisResponse,
  type NozzleDiameter,
  type PrinterId,
  type PrinterInfo,
  type ProfileId,
  type QualityPreset,
  type SliceResponse,
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
    bed: 75,
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
  qualityPreset: QualityPreset;
  onChangePreset: (p: QualityPreset) => void;
  isOptimizingAI: boolean;
  aiReasoning: string | null;
  aiProvider: string | null;
  onAISupportOrient: () => void;
  isOptimizingSupportAI: boolean;
  aiSupportStatus: AISupportOrientResponse | null;
  onSlice: () => void;
  onCancelSlice?: () => void;
  isSlicing: boolean;
  sliceResult: SliceResponse | null;
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
  qualityPreset,
  onChangePreset,
  isOptimizingAI,
  aiReasoning,
  aiProvider,
  onAISupportOrient,
  isOptimizingSupportAI,
  aiSupportStatus,
  onSlice,
  onCancelSlice,
  isSlicing,
  sliceResult,
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
}: SlicerWizardProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [showManualTemps, setShowManualTemps] = useState(false);
  const [costs, setCosts] = useState<CostSettings>(loadSavedCosts);
  const [enderMode, setEnderMode] = useState<'sd_volume' | 'usb_serial'>('sd_volume');
  const [selectedSdPath, setSelectedSdPath] = useState<string>('');
  const [pendingOutputAction, setPendingOutputAction] = useState<
    'download' | 'upload_only' | 'upload_and_print' | null
  >(null);
  const [customBaseName, setCustomBaseName] = useState<string>('');
  const [learnings, setLearnings] = useState<MachineMaterialLearningsResponse | null>(null);
  const [learningsOpen, setLearningsOpen] = useState(false);
  const [draftSpoolRanges, setDraftSpoolRanges] = useState<
    Record<number, { min: string; max: string }>
  >({});

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

  const estHours = sliceResult ? parseEstimatedHours(sliceResult.estimated_time) : 0;
  const materialCost =
    sliceResult && costs.spoolWeightGrams > 0
      ? (sliceResult.filament_grams / costs.spoolWeightGrams) * costs.spoolCostPesos
      : 0;
  const energyCost = sliceResult ? estHours * costs.energyCostPerHour : 0;
  const totalCost = materialCost + energyCost;

  const matMeta = MATERIAL_DEFAULTS[material];
  const matKey = `${material}_master`;
  const selectedPrinter = printers.find((p) => p.printer_id === selectedPrinterId);
  const selectedProfileId: ProfileId =
    selectedPrinter?.profile_id ?? (selectedPrinterId as ProfileId);

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
    const lineW = nozzleDiameter * 1.05;
    const calcSpeed = (lh: number, factor: number) => {
      const flowSpeed = Math.round((effFlowLimit / (lh * lineW)) * factor);
      return Math.max(35, Math.min(machineCapMmS, flowSpeed));
    };

    return [
      {
        id: 'estandar' as QualityPreset,
        label: `${shortMachine} · ${matTag} · Estándar (${(nozzleDiameter * 0.5).toFixed(2)} mm)`,
        desc: `${calcSpeed(nozzleDiameter * 0.5, 0.72)} mm/s · ${effTemp}°C · Z=${supportZDistance.toFixed(2)} · XY=${supportXyDistance.toFixed(2)}mm · Gyroid 12%`,
      },
      {
        id: 'mecanico_resistente' as QualityPreset,
        label: `${shortMachine} · ${matTag} · Mecánico (${(nozzleDiameter * 0.5).toFixed(2)} mm)`,
        desc: `${calcSpeed(nozzleDiameter * 0.5, 0.58)} mm/s · ${effTemp}°C · 4 paredes · Gyroid 25% · Sándwich`,
      },
      {
        id: 'alta_velocidad' as QualityPreset,
        label: `${shortMachine} · ${matTag} · Alta Velocidad (${(nozzleDiameter * 0.5).toFixed(2)} mm)`,
        desc: `${calcSpeed(nozzleDiameter * 0.5, 0.92)} mm/s · ${effTemp}°C · Z=${supportZDistance.toFixed(2)} · Gyroid 10%`,
      },
      {
        id: 'rapidez_extrema' as QualityPreset,
        label: `${shortMachine} · ${matTag} · Rapidez Extrema (${(nozzleDiameter * 0.7).toFixed(2)} mm)`,
        desc: `${calcSpeed(nozzleDiameter * 0.7, 1.0)} mm/s · ${effTemp}°C · Z=${supportZDistance.toFixed(2)} · Gyroid 8%`,
      },
    ];
  }, [
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

  const handleDrop = (e: DragEvent<HTMLLabelElement>) => {
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

  const handleFileInput = (e: ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (picked) onSelectStl(picked);
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
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border border-slate-800/80 bg-slate-950/60">
      {/* Área scrollable con Pasos 1, 2 y 3 */}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {/* PASO 1: Selector de impresora */}
        <section className="rounded-xl border border-slate-800 bg-slate-900/75 p-3.5">
          <div className="mb-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500/20 text-[11px] font-bold text-cyan-300">
                1
              </span>
              <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-200">
                Impresora
              </h2>
            </div>
            <span className="text-[11px] text-slate-400">
              {printers.length} máquinas
            </span>
          </div>

          <div className="grid grid-cols-1 gap-1.5">
            {printers.map((p) => {
              const active = p.printer_id === selectedPrinterId;
              const volLabel =
                p.kinematics === 'delta'
                  ? `Ø${p.diameter_mm}×${p.height_mm} mm`
                  : `${p.bed_mm?.join('×')} mm`;
              const kinLabel =
                p.kinematics === 'delta'
                  ? 'Delta Klipper'
                  : p.kinematics === 'corexy_toolchanger_4x'
                    ? 'CoreXY 4-Tool'
                    : 'Cartesiana Marlin 2';

              return (
                <button
                  key={p.printer_id}
                  type="button"
                  data-printer-id={p.printer_id}
                  onClick={() => onSelectPrinter(p.printer_id)}
                  className={`flex cursor-pointer items-center justify-between rounded-xl border px-3 py-2 text-left transition ${
                    active
                      ? 'border-cyan-500/70 bg-cyan-500/10 shadow-sm shadow-cyan-500/10'
                      : 'border-slate-800 bg-slate-950/60 hover:border-slate-700'
                  }`}
                >
                  <div className="min-w-0 pr-2">
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
                  </div>
                  <span className="shrink-0 rounded-md bg-slate-800/90 px-2 py-0.5 font-mono text-[11px] text-cyan-300">
                    {p.max_volumetric_flow_mm3_s} mm³/s
                  </span>
                </button>
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
            </div>
          </div>

          <label
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
            <input
              type="file"
              accept=".stl,.3mf"
              onChange={handleFileInput}
              className="hidden"
            />
          </label>

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

          {/* Selector Material (oculto en Creator 5 Pro porque usa los 4 cabezales T0–T3) */}
          {selectedProfileId !== 'creator5_pro' && (
            <>
              <div className="grid grid-cols-4 gap-1.5">
                {(Object.keys(MATERIAL_DEFAULTS) as MaterialType[]).map((mat) => {
                  const active = material === mat;
                  const disabledByLitho = lithophaneMode && mat !== 'pla';
                  return (
                    <button
                      key={mat}
                      type="button"
                      disabled={disabledByLitho}
                      title={
                        disabledByLitho
                          ? 'Las litofanías requieren PLA blanco/translúcido'
                          : undefined
                      }
                      onClick={() => {
                        if (!disabledByLitho) onChangeMaterial(mat);
                      }}
                      className={`rounded-lg border py-1.5 text-xs font-semibold transition ${
                        disabledByLitho
                          ? 'cursor-not-allowed border-slate-800/60 bg-slate-950/30 text-slate-600 opacity-45'
                          : active
                            ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                            : 'border-slate-800 bg-slate-950/60 text-slate-400 hover:text-slate-200'
                      }`}
                    >
                      {MATERIAL_DEFAULTS[mat].label}
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
            </div>

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
                    onClick={() => onChangeSupportType('tree(auto)')}
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
                    onClick={() => onChangeSupportType('normal(auto)')}
                    className={`rounded-lg border py-1 text-[11px] font-medium transition ${
                      supportType === 'normal(auto)'
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-900 text-slate-400'
                    }`}
                  >
                    Normal / Típico
                  </button>
                </div>

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
          </div>

          {/* Panel Multicabezal T0..T3 solo para FlashForge Creator 5 Pro */}
          {selectedProfileId === 'creator5_pro' && (
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

              {/* Torre de Purga Inteligente Ultra-Ahorro */}
              <div className="flex items-center justify-between gap-2 rounded-lg border border-purple-500/25 bg-slate-950/75 px-2.5 py-1.5">
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold text-slate-200">
                    {primeTowerEnabled
                      ? 'Activada Ultra-Ahorro 20mm + Purga en Relleno'
                      : 'Torre de Purga: Desactivada (Ahorro 4 cabezales)'}
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
                            T{slot.extruder_index}
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
                            <option value="soporte">Soporte</option>
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
                      <span className="font-semibold text-cyan-200">
                        Cama negociada: <strong className="font-mono text-white">{summary.negotiatedBedTemp}°C</strong>
                      </span>
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

              {/* Asignación interactiva: Zonas pintadas del .3MF -> Cabezal físico (T0–T3) */}
              {analysis?.is_multicolor &&
                analysis.extruder_triangle_percentages &&
                Object.keys(analysis.extruder_triangle_percentages).length > 1 && (
                  <div className="space-y-1.5 border-t border-purple-500/20 pt-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[11px] font-medium text-purple-200">
                        Colores del modelo → Cabezal físico ({analysis.detected_extruder_count ?? Object.keys(analysis.extruder_triangle_percentages).length} zonas)
                      </span>
                      <span className="rounded bg-purple-500/20 px-1.5 py-0.5 font-mono text-[10px] text-purple-200">
                        paint_color
                      </span>
                    </div>
                    <div className="space-y-1">
                      {[0, 1, 2, 3].map((zoneIdx) => {
                        const pct = analysis.extruder_triangle_percentages?.[`T${zoneIdx}`];
                        if (pct === undefined) return null;
                        const origHex =
                          analysis.detected_filament_colors?.[zoneIdx] || '#94A3B8';
                        const mappedSlot = partExtruderMap[`zone_${zoneIdx}`] ?? zoneIdx;
                        const targetColor =
                          extrudersConfig[mappedSlot]?.color_hex || origHex;
                        return (
                          <div
                            key={zoneIdx}
                            className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950 px-2 py-1 text-[11px]"
                          >
                            <div className="flex min-w-0 items-center gap-1.5">
                              <span
                                className="h-3 w-3 shrink-0 rounded-sm border border-white/25"
                                style={{ backgroundColor: origHex }}
                                title={`Color original en .3MF: ${origHex}`}
                              />
                              <span className="text-slate-200">
                                Color #{zoneIdx + 1}
                              </span>
                              <span className="font-mono text-[10px] text-slate-400">
                                ({pct.toFixed(1)}%)
                              </span>
                            </div>
                            <div className="flex items-center gap-1.5">
                              <span
                                className="h-2.5 w-2.5 shrink-0 rounded-full border border-white/25"
                                style={{ backgroundColor: targetColor }}
                                title={`Carrete asignado: ${targetColor}`}
                              />
                              <select
                                value={mappedSlot}
                                aria-label={`Cabezal para Color #${zoneIdx + 1}`}
                                onChange={(e) =>
                                  onChangePartExtruderMap({
                                    ...partExtruderMap,
                                    [`zone_${zoneIdx}`]: Number(e.target.value),
                                  })
                                }
                                className="rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200"
                              >
                                {[0, 1, 2, 3].map((t) => {
                                  const sc = extrudersConfig[t];
                                  const presetName =
                                    COLOR_PRESETS.find(
                                      (p) => p.hex.toUpperCase() === sc?.color_hex?.toUpperCase(),
                                    )?.name || sc?.color_hex;
                                  return (
                                    <option key={t} value={t}>
                                      T{t} · {presetName} ({sc?.material?.toUpperCase() || 'PLA'})
                                    </option>
                                  );
                                })}
                              </select>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

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
                      const assignedExt = partExtruderMap[part.part_id] ?? part.extruder;
                      const slotHex =
                        extrudersConfig[assignedExt - 1]?.color_hex ||
                        part.color_hex ||
                        '#94A3B8';
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
                            onChange={(e) =>
                              onChangePartExtruderMap({
                                ...partExtruderMap,
                                [part.part_id]: Number(e.target.value),
                              })
                            }
                            className="shrink-0 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 font-mono text-[10px] text-cyan-200"
                          >
                            {[1, 2, 3, 4].map((extNum) => (
                              <option key={extNum} value={extNum}>
                                T{extNum - 1}
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
                        T{i} ({extrudersConfig[i]?.material.toUpperCase()})
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
                        T{i} ({extrudersConfig[i]?.material.toUpperCase()})
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
                          T{i}
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

          {/* Perfiles Dinámicos por Máquina + Material + Boquilla + HS */}
          <div className="mt-2.5 space-y-1.5">
            <p className="text-xs font-medium text-slate-300">
              Perfiles Dinámicos (Arachne + Gyroid)
            </p>
            <div className="grid grid-cols-1 gap-1.5">
              {dynamicPresets.map((opt) => {
                const active = qualityPreset === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => onChangePreset(opt.id)}
                    className={`rounded-xl border px-3 py-1.5 text-left transition ${
                      active
                        ? 'border-cyan-500/70 bg-cyan-500/10'
                        : 'border-slate-800 bg-slate-950/60 hover:border-slate-700'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-100">
                        {opt.label}
                      </span>
                      {active && (
                        <ShieldCheck className="h-3.5 w-3.5 text-cyan-400" />
                      )}
                    </div>
                    <p className="text-[10px] text-slate-400">{opt.desc}</p>
                  </button>
                );
              })}
            </div>
          </div>
          {/* Costos de Producción en Pesos (Persistente en localStorage) */}
          <div className="mt-2.5 space-y-2 rounded-xl border border-slate-800 bg-slate-950/60 p-2.5">
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-200">
              <DollarSign className="h-3.5 w-3.5 text-emerald-400" />
              <span>Costos de Producción (Pesos)</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              <div>
                <label className="mb-0.5 block text-[10px] text-slate-400">
                  Peso rollo (g)
                </label>
                <input
                  type="number"
                  min={50}
                  step={50}
                  value={costs.spoolWeightGrams}
                  onChange={(e) =>
                    setCosts((c) => ({
                      ...c,
                      spoolWeightGrams: Math.max(1, Number(e.target.value) || 1000),
                    }))
                  }
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100"
                />
              </div>
              <div>
                <label className="mb-0.5 block text-[10px] text-slate-400">
                  Costo rollo ($)
                </label>
                <input
                  type="number"
                  min={0}
                  step={1000}
                  value={costs.spoolCostPesos}
                  onChange={(e) =>
                    setCosts((c) => ({
                      ...c,
                      spoolCostPesos: Math.max(0, Number(e.target.value) || 0),
                    }))
                  }
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100"
                />
              </div>
              <div>
                <label className="mb-0.5 block text-[10px] text-slate-400">
                  Energía / h ($)
                </label>
                <input
                  type="number"
                  min={0}
                  step={100}
                  value={costs.energyCostPerHour}
                  onChange={(e) =>
                    setCosts((c) => ({
                      ...c,
                      energyCostPerHour: Math.max(0, Number(e.target.value) || 0),
                    }))
                  }
                  className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100"
                />
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* PASO 4 STICKY: Fijo en la parte inferior de la barra lateral */}
      <section className="sticky bottom-0 z-10 border-t border-slate-800 bg-slate-900/95 p-3.5 backdrop-blur">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500/20 text-[11px] font-bold text-cyan-300">
              4
            </span>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-200">
              Laminar y Exportar
            </h2>
          </div>
          {!analysis?.fits_in_volume && analysis && (
            <span className="text-[10px] font-medium text-amber-300">
              Auto-Ajusta o Auto-Orienta
            </span>
          )}
        </div>

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
                  ({selectedProfileId === 'creator5_pro' ? 'timeLapseVideo' : 'Klipper por capa'})
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
        </div>

        <button
          type="button"
          disabled={!canSlice}
          onClick={onSlice}
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

        <div className="mt-1.5 space-y-1">
          <button
            type="button"
            disabled={!sliceResult || isSlicing || isOptimizingSupportAI}
            onClick={onAISupportOrient}
            title={
              !sliceResult
                ? 'Lamina primero para evaluar tiempos y soportes reales'
                : 'Evalúa con DeepSeek IA si rotar o ajustar soportes ahorra tiempo y material'
            }
            className="flex w-full items-center justify-center gap-1.5 rounded-xl border border-cyan-500/45 bg-gradient-to-r from-cyan-500/15 to-violet-500/15 px-3 py-2 text-xs font-semibold text-cyan-100 transition hover:from-cyan-500/25 hover:to-violet-500/25 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isOptimizingSupportAI ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-300" />
            ) : (
              <Sparkles className="h-3.5 w-3.5 text-cyan-300" />
            )}
            <span>
              {isOptimizingSupportAI
                ? 'Optimizando y re-laminando...'
                : 'Soporte con IA (Ángulo Anti-Soportes)'}
            </span>
          </button>
          {!sliceResult && (
            <p className="text-center text-[10px] text-slate-400">
              Lamina primero para evaluar tiempos y soportes reales
            </p>
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

        {sliceResult && !isSlicing && (
          <div className="mt-2.5 space-y-2 rounded-xl border border-emerald-500/35 bg-emerald-500/5 p-2.5">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-300">
                <CheckCircle2 className="h-3.5 w-3.5" />
                Laminado listo
              </span>
              <span className="font-mono text-[10px] text-slate-400">
                {sliceResult.job_id}
              </span>
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

            {/* Desglose de costos en tiempo real */}
            <div className="rounded-lg border border-emerald-500/25 bg-slate-950/80 px-2.5 py-1.5 text-[11px]">
              <div className="flex items-center justify-between text-slate-400">
                <span>Filamento: {formatPesos(materialCost)}</span>
                <span>Energía: {formatPesos(energyCost)}</span>
              </div>
              <div className="mt-1 flex items-center justify-between border-t border-slate-800 pt-1">
                <span className="font-semibold text-slate-200">
                  Costo Total Estimado
                </span>
                <span className="font-mono text-xs font-bold text-emerald-300">
                  {formatPesos(totalCost)}
                </span>
              </div>
            </div>

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
                    Subir sin Imprimir
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
                    Subir e Imprimir Ahora
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
                  Descargar G-code (.gcode)
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
                          .gcode
                        </span>
                      </div>
                    </div>

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
                            const baseUrl = getGcodeUrl(sliceResult.gcode_url, cleanName);
                            const sep = baseUrl.includes('?') ? '&' : '?';
                            const dlUrl = isC5P ? `${baseUrl}${sep}format=flashforge` : baseUrl;
                            const ext = '.gcode';
                            setPendingOutputAction(null);
                            void triggerFileDownload(dlUrl, `${cleanName}${ext}`);
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
      </section>
    </div>
  );
}
