import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Activity, AlertTriangle, Box, Calculator, Cpu, FolderOpen, Globe, Plus, Redo2, Server, Settings, Sliders, Undo2, X } from 'lucide-react';
import { useI18n } from './i18n/I18nContext';
import { useSessionHistory } from './hooks/useSessionHistory';
import { ErrorJournalModal } from './components/ErrorJournalModal';
import { QuoteCalculatorModal } from './components/QuoteCalculatorModal';
import { SystemSetupModal } from './components/SystemSetupModal';
import {
  API_BASE_URL,
  analyzeMesh,
  applyLayerPauses,
  autoArrangeModels,
  clearLastSession,
  cutMeshByPlane,
  deleteFullProject,
  deleteUserPrinter,
  fetchAIRecommendation,
  fetchCachedMeshFile,
  fetchCatalog,
  fetchFullProject,
  fetchGcodeText,
  fetchLayOnFaceCandidates,
  fetchPrintersConfig,
  fetchRecentProjects,
  fetchSavedProjects,
  fetchSystemEnvironment,
  fetchUserPrefs,
  getProjectModelFileUrl,
  requestAIAnalyzeModel,
  requestAIOrientations,
  requestAIOptimizeSlice,
  requestAISupportOrient,
  saveFullProject,
  exportSelection,
  saveUserPrefs,
  sliceModel,
  splitMeshObjects,
  uploadJobToPrinter,
  type AIAnalyzeModelResponse,
  type AIOrientationsResponse,
  type AIOptimizeSliceResponse,
  type AISupportOrientResponse,
  type FullProjectSummary,
  type OrientationOption,
  type AdhesionType,
  type ExtruderSlotConfig,
  type LayerPauseItem,
  type LayOnFaceCandidate,
  type MachineProfileInfo,
  type MaterialType,
  type MeshAnalysisResponse,
  type ModelInstanceTransform,
  type ModelTransform,
  type NozzleDiameter,
  type PrinterId,
  type PrinterInfo,
  type PrintersConfigResponse,
  type ProfileId,
  type SlicedProfileSnapshot,
  type SupportBlockerItem,
  type QualityPreset,
  type SavedProjectRecord,
  type SceneObjectTransform,
  type SliceResponse,
  type SupportType,
  type ZColorRange,
} from './services/api';
import { AddPrinterModal } from './components/AddPrinterModal';
import { FarmDashboard } from './components/FarmDashboard';
import { PrinterSettingsModal } from './components/PrinterSettingsModal';
import {
  MATERIAL_DEFAULTS,
  SlicerWizard,
  computeAutoTemperatures,
  computeDefaultSupportXY,
  computeSlotThermalConfig,
  negotiateMultiMaterialBedTemp,
} from './components/SlicerWizard';
import { Viewport3D, arrangeSceneObjectsOnBed } from './components/Viewport3D';
import { GlobalProcessingOverlay } from './components/GlobalProcessingOverlay';

const DEFAULT_TRANSFORM: ModelTransform = {
  scalePercent: 100,
  rotX: 0,
  rotY: 0,
  rotZ: 0,
  offsetX: 0,
  offsetY: 0,
  offsetZ: 0,
  dropToBed: true,
  uniformScale: true,
};

const DEFAULT_EXTRUDERS: ExtruderSlotConfig[] = [
  { extruder_index: 0, material: 'pla', color_hex: '#22d3ee', high_speed: false, spool_min: 190, spool_max: 225, nozzle_temp: 213, nozzle_temp_initial_layer: 220, max_volumetric_speed: 32 },
  { extruder_index: 1, material: 'pla', color_hex: '#f97316', high_speed: false, spool_min: 190, spool_max: 225, nozzle_temp: 213, nozzle_temp_initial_layer: 220, max_volumetric_speed: 32 },
  { extruder_index: 2, material: 'soporte', color_hex: '#22c55e', high_speed: false, spool_min: 190, spool_max: 220, nozzle_temp: 210, nozzle_temp_initial_layer: 216, max_volumetric_speed: 32 },
  { extruder_index: 3, material: 'pla', color_hex: '#a855f7', high_speed: false, spool_min: 190, spool_max: 225, nozzle_temp: 213, nozzle_temp_initial_layer: 220, max_volumetric_speed: 32 },
];

const PREFS_STORAGE_KEY = 'nikk_slider_prefs_v1';

interface SavedUserPrefs {
  selectedPrinterId?: PrinterId;
  material?: MaterialType;
  nozzleDiameter?: NozzleDiameter;
  highSpeedFilament?: boolean;
  lithophaneMode?: boolean;
  spoolMinTemp?: number;
  spoolMaxTemp?: number;
  qualityPreset?: QualityPreset;
  autoLeveling?: boolean;
  extrudersConfig?: ExtruderSlotConfig[];
  modelExtruder?: number;
  supportExtruder?: number;
  last_session?: LastSessionData;
}

interface LastSessionData {
  mesh_id: string;
  file_name: string;
  printer_id?: PrinterId;
  transform?: ModelTransform;
  part_extruder_map?: Record<string, number>;
  z_color_ranges?: ZColorRange[];
  supports?: boolean;
  support_type?: SupportType;
  support_on_build_plate_only?: boolean;
  support_z_distance?: number;
  support_xy_distance?: number;
  adhesion_type?: AdhesionType;
  brim_width_mm?: number;
  scene_objects?: SceneObjectTransform[];
  selected_object_ids?: string[];
  support_blockers?: SupportBlockerItem[];
  saved_at?: string;
}

function loadSavedUserPrefs(): SavedUserPrefs {
  try {
    const raw = window.localStorage.getItem(PREFS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Partial<SavedUserPrefs>;
    return typeof parsed === 'object' && parsed ? parsed : {};
  } catch {
    return {};
  }
}

function formatSecondsDiff(sec: number): string {
  const abs = Math.max(0, Math.round(sec));
  const h = Math.floor(abs / 3600);
  const m = Math.floor((abs % 3600) / 60);
  const s = abs % 60;
  if (h > 0) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (m > 0) return `${m}m ${String(s).padStart(2, '0')}s`;
  return `${s}s`;
}

function parseTimeStrToSeconds(txt: string): number {
  let total = 0;
  const re = /(\d+)\s*([dhms])/gi;
  let m: RegExpExecArray | null;
  while ((m = re.exec(txt)) !== null) {
    const val = Number(m[1]);
    const unit = m[2].toLowerCase();
    if (unit === 'd') total += val * 86400;
    else if (unit === 'h') total += val * 3600;
    else if (unit === 'm') total += val * 60;
    else if (unit === 's') total += val;
  }
  return total;
}

export function App() {
  const { lang, toggleLang, t } = useI18n();
  const [initialPrefs] = useState<SavedUserPrefs>(() => loadSavedUserPrefs());
  const initLithophane = Boolean(initialPrefs.lithophaneMode);
  const initMat: MaterialType = initLithophane
    ? 'pla'
    : initialPrefs.material && initialPrefs.material in MATERIAL_DEFAULTS
      ? initialPrefs.material
      : 'pla';
  const initNozzle: NozzleDiameter =
    initialPrefs.nozzleDiameter &&
      [0.2, 0.4, 0.6, 0.8].includes(initialPrefs.nozzleDiameter)
      ? initialPrefs.nozzleDiameter
      : 0.4;

  const [activeTab, setActiveTab] = useState<'wizard' | 'monitor'>('wizard');
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [isLoadingExternalFile, setIsLoadingExternalFile] = useState<string | null>(null);
  const dragCounterRef = useRef(0);
  const suppressRestorePromptRef = useRef(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [journalOpen, setJournalOpen] = useState(false);
  const [quoteCalculatorOpen, setQuoteCalculatorOpen] = useState(false);
  const [systemSetupOpen, setSystemSetupOpen] = useState(false);

  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const [machineProfiles, setMachineProfiles] = useState<MachineProfileInfo[]>([]);
  const [printersConfig, setPrintersConfig] =
    useState<PrintersConfigResponse | null>(null);
  const [volumetricLimits, setVolumetricLimits] = useState<
    Record<string, Record<string, number>>
  >({});
  const [highSpeedVolumetricLimits, setHighSpeedVolumetricLimits] = useState<
    Record<string, Record<string, number>>
  >({});
  const [selectedPrinterId, setSelectedPrinterId] = useState<PrinterId>(
    initialPrefs.selectedPrinterId || 'flsun_t1_pro_1',
  );
  const [addPrinterOpen, setAddPrinterOpen] = useState(false);

  const [stlFile, setStlFile] = useState<File | null>(null);
  const [meshId, setMeshId] = useState<string | null>(null);
  const [transform, setTransform] = useState<ModelTransform>(DEFAULT_TRANSFORM);
  const [analysis, setAnalysis] = useState<MeshAnalysisResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isAutoOrienting, setIsAutoOrienting] = useState(false);
  const [isAutoArranging, setIsAutoArranging] = useState(false);
  const [isCuttingMesh, setIsCuttingMesh] = useState(false);
  const [isSplittingObjects, setIsSplittingObjects] = useState(false);
  const [sceneObjects, setSceneObjects] = useState<SceneObjectTransform[]>([]);
  const [selectedObjectIds, setSelectedObjectIds] = useState<string[]>([]);
  const [autoOrientMsg, setAutoOrientMsg] = useState<string | null>(null);
  const [orientationsData, setOrientationsData] =
    useState<AIOrientationsResponse | null>(null);
  const [selectedOrientationId, setSelectedOrientationId] = useState<string | null>(
    null,
  );

  const [material, setMaterial] = useState<MaterialType>(initMat);
  const [nozzleDiameter, setNozzleDiameter] = useState<NozzleDiameter>(initNozzle);
  const [highSpeedFilament, setHighSpeedFilament] = useState<boolean>(
    Boolean(initialPrefs.highSpeedFilament),
  );
  const [lithophaneMode, setLithophaneMode] = useState<boolean>(initLithophane);
  const [spoolMinTemp, setSpoolMinTemp] = useState<number>(
    typeof initialPrefs.spoolMinTemp === 'number'
      ? initialPrefs.spoolMinTemp
      : MATERIAL_DEFAULTS[initMat].recMin,
  );
  const [spoolMaxTemp, setSpoolMaxTemp] = useState<number>(
    typeof initialPrefs.spoolMaxTemp === 'number'
      ? initialPrefs.spoolMaxTemp
      : MATERIAL_DEFAULTS[initMat].recMax,
  );
  const [nozzleTempInitial, setNozzleTempInitial] = useState<number>(
    MATERIAL_DEFAULTS[initMat].nozzleInitial,
  );
  const [nozzleTemp, setNozzleTemp] = useState<number>(
    MATERIAL_DEFAULTS[initMat].nozzle,
  );
  const [bedTemp, setBedTemp] = useState<number>(MATERIAL_DEFAULTS[initMat].bed);

  const [supports, setSupports] = useState<boolean>(false);
  const [supportType, setSupportType] = useState<SupportType>('tree(auto)');
  const [supportStyle, setSupportStyle] = useState<string>('default');
  const [supportOnBuildPlateOnly, setSupportOnBuildPlateOnly] =
    useState<boolean>(true);
  const [supportZDistance, setSupportZDistance] = useState<number>(
    MATERIAL_DEFAULTS[initMat].defaultSupportZ,
  );
  const [supportXyDistance, setSupportXyDistance] = useState<number>(
    computeDefaultSupportXY(initMat, initNozzle),
  );
  const [adhesionType, setAdhesionType] = useState<AdhesionType>(
    initLithophane ? 'brim' : 'none',
  );
  const [brimWidthMm, setBrimWidthMm] = useState<number>(initLithophane ? 8 : 6);
  const [adhesionLabel, setAdhesionLabel] = useState<string | null>(
    initLithophane ? 'Brim Exterior 8 mm · Gap 0.12 mm (Litofanía)' : null,
  );
  const [primeTowerEnabled, setPrimeTowerEnabled] = useState<boolean>(false);
  const [primeTowerReason, setPrimeTowerReason] = useState<string | null>(null);
  const [primeTowerBrimOverride, setPrimeTowerBrimOverride] = useState<number | null>(null);
  const [enableTimelapse, setEnableTimelapse] = useState<boolean>(false);
  const [autoLeveling, setAutoLeveling] = useState<boolean>(
    Boolean(initialPrefs.autoLeveling),
  );
  const [qualityPreset, setQualityPreset] = useState<QualityPreset>(
    initialPrefs.qualityPreset || 'estandar',
  );
  const [specializedProfileId, setSpecializedProfileId] = useState<
    | 'none'
    | 'detalle_fino'
    | 'detalle_optimo'
    | 'piel_difusa'
    | 'rapido_funcional'
    | 'litofania_hd'
    | 'litofania_ultra'
    | 'litofania_vertical'
  >('none');

  const [isOptimizingAI, setIsOptimizingAI] = useState(false);
  const [aiReasoning, setAiReasoning] = useState<string | null>(null);
  const [aiProvider, setAiProvider] = useState<string | null>(null);
  const [isOptimizingSupportAI, setIsOptimizingSupportAI] = useState(false);
  const [aiSupportStatus, setAiSupportStatus] =
    useState<AISupportOrientResponse | null>(null);
  const [isAnalyzingAI, setIsAnalyzingAI] = useState(false);
  const [aiAnalysisResult, setAiAnalysisResult] =
    useState<AIAnalyzeModelResponse | null>(null);
  const [aiQualityOverrides, setAiQualityOverrides] = useState<string[]>([]);
  const [isOptimizingSliceAI, setIsOptimizingSliceAI] = useState(false);
  const [aiOptimizeComparison, setAiOptimizeComparison] = useState<{
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
  } | null>(null);

  const [layerHeightOverride, setLayerHeightOverride] = useState<number | null>(null);
  const [outerWallSpeedOverride, setOuterWallSpeedOverride] = useState<number | null>(null);
  const [flowRatioOverride, setFlowRatioOverride] = useState<number | null>(null);
  const [infillDensityOverride, setInfillDensityOverride] = useState<number | null>(null);
  const [fuzzySkin, setFuzzySkin] = useState(false);
  const [fuzzySkinThickness, setFuzzySkinThickness] = useState(0.25);
  const [fuzzySkinPointDistance, setFuzzySkinPointDistance] = useState(0.4);
  const [aiStrategyLabel, setAiStrategyLabel] = useState<string | null>(null);

  const [initialSliceSnapshot, setInitialSliceSnapshot] = useState<{
    sliceResult: SliceResponse;
    gcodeText: string | null;
    transform: ModelTransform;
    analysis: MeshAnalysisResponse | null;
    supports: boolean;
    supportType: SupportType;
    supportOnBuildPlateOnly: boolean;
    supportZDistance: number;
    supportXyDistance: number;
    adhesionType: AdhesionType;
    brimWidthMm: number;
    nozzleTemp: number;
    bedTemp: number;
    layerHeightOverride: number | null;
    outerWallSpeedOverride: number | null;
    flowRatioOverride: number | null;
    infillDensityOverride: number | null;
    fuzzySkin: boolean;
    aiStrategyLabel: string | null;
  } | null>(null);

  const [savedProjects, setSavedProjects] = useState<SavedProjectRecord[]>([]);
  const [recentProjects, setRecentProjects] = useState<FullProjectSummary[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [activeProjectTitle, setActiveProjectTitle] = useState<string | null>(null);
  const [windowSessionId] = useState<string>(() => {
    const p = new URLSearchParams(window.location.search).get('window_session_id');
    return p || `win_${Math.random().toString(36).slice(2, 10)}`;
  });
  const windowAccent = (() => {
    const palette = [
      { name: 'Cian Eléctrico', hex: '#22d3ee' },
      { name: 'Ámbar Dorado', hex: '#f59e0b' },
      { name: 'Esmeralda', hex: '#10b981' },
      { name: 'Violeta', hex: '#a855f7' },
      { name: 'Coral', hex: '#fb7185' },
    ];
    let h = 0;
    for (let i = 0; i < windowSessionId.length; i += 1) {
      h = (h * 31 + windowSessionId.charCodeAt(i)) >>> 0;
    }
    return palette[h % palette.length];
  })();
  const [openWindows, setOpenWindows] = useState<
    Record<string, { windowId: string; title: string; color: string; updatedAt: number }>
  >({});
  const [externalProjectsOpen, setExternalProjectsOpen] = useState(false);
  const [projectToast, setProjectToast] = useState<string | null>(null);
  const [isLoadingProjects, setIsLoadingProjects] = useState(false);

  const [isSlicing, setIsSlicing] = useState(false);
  const [sliceResult, setSliceResult] = useState<SliceResponse | null>(null);
  const [slicedProfileSnapshot, setSlicedProfileSnapshot] = useState<SlicedProfileSnapshot | null>(null);
  const [profileDrawerOpen, setProfileDrawerOpen] = useState(false);
  const [supportBlockers, setSupportBlockers] = useState<SupportBlockerItem[]>([]);
  const [gcodeText, setGcodeText] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const [uploadActionMode, setUploadActionMode] = useState<
    'upload_only' | 'upload_and_print' | null
  >(null);
  const [sendPrintMsg, setSendPrintMsg] = useState<string | null>(null);

  const [extrudersConfig, setExtrudersConfig] = useState<ExtruderSlotConfig[]>(() => {
    if (
      Array.isArray(initialPrefs.extrudersConfig) &&
      initialPrefs.extrudersConfig.length === 4
    ) {
      return initialPrefs.extrudersConfig.map((s, idx) => ({
        ...DEFAULT_EXTRUDERS[idx],
        ...s,
        extruder_index: idx,
      }));
    }
    return DEFAULT_EXTRUDERS;
  });
  const [modelExtruder, setModelExtruder] = useState<number>(() =>
    typeof initialPrefs.modelExtruder === 'number' &&
    initialPrefs.modelExtruder >= 0 &&
    initialPrefs.modelExtruder <= 3
      ? initialPrefs.modelExtruder
      : 0,
  );
  const [supportExtruder, setSupportExtruder] = useState<number>(() =>
    typeof initialPrefs.supportExtruder === 'number' &&
    initialPrefs.supportExtruder >= 0 &&
    initialPrefs.supportExtruder <= 3
      ? initialPrefs.supportExtruder
      : 0,
  );
  const [zColorRanges, setZColorRanges] = useState<ZColorRange[]>([]);
  const [layerPauses, setLayerPauses] = useState<LayerPauseItem[]>([]);
  const [partExtruderMap, setPartExtruderMap] = useState<Record<string, number>>({});
  const [chamberTempTarget, setChamberTempTarget] = useState<number | null>(null);
  const [pendingRestoreSession, setPendingRestoreSession] =
    useState<LastSessionData | null>(null);
  const [isRestoringSession, setIsRestoringSession] = useState(false);

  const analyzeSeqRef = useRef(0);
  const prefsLoadedRef = useRef(false);
  const lastSupportSyncKeyRef = useRef<string>('');

  const sessionSnapshot = useMemo(
    () => ({
      selectedPrinterId,
      transform,
      sceneObjects,
      selectedObjectIds,
      material,
      nozzleDiameter,
      highSpeedFilament,
      lithophaneMode,
      spoolMinTemp,
      spoolMaxTemp,
      nozzleTempInitial,
      nozzleTemp,
      bedTemp,
      supports,
      supportType,
      supportStyle,
      supportOnBuildPlateOnly,
      supportZDistance,
      supportXyDistance,
      adhesionType,
      brimWidthMm,
      primeTowerEnabled,
      qualityPreset,
      specializedProfileId,
      layerHeightOverride,
      outerWallSpeedOverride,
      flowRatioOverride,
      infillDensityOverride,
      fuzzySkin,
      fuzzySkinThickness,
      fuzzySkinPointDistance,
      extrudersConfig,
      modelExtruder,
      supportExtruder,
      partExtruderMap,
      layerPauses,
      supportBlockers,
    }),
    [
      selectedPrinterId,
      transform,
      sceneObjects,
      selectedObjectIds,
      material,
      nozzleDiameter,
      highSpeedFilament,
      lithophaneMode,
      spoolMinTemp,
      spoolMaxTemp,
      nozzleTempInitial,
      nozzleTemp,
      bedTemp,
      supports,
      supportType,
      supportStyle,
      supportOnBuildPlateOnly,
      supportZDistance,
      supportXyDistance,
      adhesionType,
      brimWidthMm,
      primeTowerEnabled,
      qualityPreset,
      specializedProfileId,
      layerHeightOverride,
      outerWallSpeedOverride,
      flowRatioOverride,
      infillDensityOverride,
      fuzzySkin,
      fuzzySkinThickness,
      fuzzySkinPointDistance,
      extrudersConfig,
      modelExtruder,
      supportExtruder,
      partExtruderMap,
      layerPauses,
      supportBlockers,
    ],
  );

  const applySessionSnapshot = useCallback((snap: typeof sessionSnapshot) => {
    setSelectedPrinterId(snap.selectedPrinterId);
    setTransform(snap.transform);
    setSceneObjects(snap.sceneObjects);
    setSelectedObjectIds(snap.selectedObjectIds);
    setMaterial(snap.material);
    setNozzleDiameter(snap.nozzleDiameter);
    setHighSpeedFilament(snap.highSpeedFilament);
    setLithophaneMode(snap.lithophaneMode);
    setSpoolMinTemp(snap.spoolMinTemp);
    setSpoolMaxTemp(snap.spoolMaxTemp);
    setNozzleTempInitial(snap.nozzleTempInitial);
    setNozzleTemp(snap.nozzleTemp);
    setBedTemp(snap.bedTemp);
    setSupports(snap.supports);
    setSupportType(snap.supportType);
    setSupportStyle(snap.supportStyle);
    setSupportOnBuildPlateOnly(snap.supportOnBuildPlateOnly);
    setSupportZDistance(snap.supportZDistance);
    setSupportXyDistance(snap.supportXyDistance);
    setAdhesionType(snap.adhesionType);
    setBrimWidthMm(snap.brimWidthMm);
    setPrimeTowerEnabled(snap.primeTowerEnabled);
    setQualityPreset(snap.qualityPreset);
    setSpecializedProfileId(snap.specializedProfileId);
    setLayerHeightOverride(snap.layerHeightOverride);
    setOuterWallSpeedOverride(snap.outerWallSpeedOverride);
    setFlowRatioOverride(snap.flowRatioOverride);
    setInfillDensityOverride(snap.infillDensityOverride);
    setFuzzySkin(snap.fuzzySkin);
    setFuzzySkinThickness(snap.fuzzySkinThickness);
    setFuzzySkinPointDistance(snap.fuzzySkinPointDistance);
    setExtrudersConfig(snap.extrudersConfig);
    setModelExtruder(snap.modelExtruder);
    setSupportExtruder(snap.supportExtruder);
    setPartExtruderMap(snap.partExtruderMap);
    setLayerPauses(snap.layerPauses);
    setSupportBlockers(snap.supportBlockers);
  }, []);

  const {
    canUndo,
    canRedo,
    undoCount,
    redoCount,
    undo: undoSession,
    redo: redoSession,
    resetHistory: resetSessionHistory,
  } = useSessionHistory({
    currentSnapshot: sessionSnapshot,
    onApplySnapshot: applySessionSnapshot,
    maxSteps: 80,
    debounceMs: 280,
  });

  useEffect(() => {
    const onGlobalKeyDown = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const key = e.key.toLowerCase();
      const target = e.target as HTMLElement | null;
      const tag = target?.tagName ?? '';
      const isTextInput =
        (tag === 'INPUT' &&
          !['range', 'checkbox', 'radio', 'button', 'submit'].includes(
            (target as HTMLInputElement).type || '',
          )) ||
        tag === 'TEXTAREA' ||
        Boolean(target?.isContentEditable);

      const isUndo = key === 'z' && !e.shiftKey;
      const isRedo =
        (e.ctrlKey && !e.metaKey && key === 'r') ||
        (e.metaKey && key === 'y') ||
        (e.ctrlKey && key === 'y') ||
        (key === 'z' && e.shiftKey);

      if (isTextInput && !isRedo) return;

      if (isUndo) {
        e.preventDefault();
        e.stopPropagation();
        undoSession();
      } else if (isRedo) {
        e.preventDefault();
        e.stopPropagation();
        redoSession();
      }
    };
    window.addEventListener('keydown', onGlobalKeyDown, { capture: true });
    return () => window.removeEventListener('keydown', onGlobalKeyDown, { capture: true });
  }, [undoSession, redoSession]);

  const activePrinter =
    printers.find((p) => p.printer_id === selectedPrinterId) ?? null;
  const activeProfileId: ProfileId =
    activePrinter?.profile_id ?? 'flsun_t1_pro';

  const refreshCatalog = () =>
    fetchCatalog()
      .then((catalog) => {
        setPrinters(catalog.printers);
        setMachineProfiles(catalog.machine_profiles ?? []);
        setVolumetricLimits(catalog.volumetric_limits_mm3_s);
        setHighSpeedVolumetricLimits(
          catalog.high_speed_volumetric_limits_mm3_s ?? {},
        );
        setSelectedPrinterId((cur) => {
          if (catalog.printers.some((p) => p.printer_id === cur)) return cur;
          return catalog.printers[0]?.printer_id ?? cur;
        });
      })
      .catch((err: unknown) => {
        setErrorMsg(
          err instanceof Error
            ? `No se pudo conectar con el backend FastAPI: ${err.message}`
            : 'Error cargando el catálogo de impresoras.',
        );
      });

  useEffect(() => {
    void refreshCatalog();

    fetchPrintersConfig()
      .then((cfg) => setPrintersConfig(cfg))
      .catch(() => {
        // Opcional en arranque si aún se está conectando
      });

    fetchUserPrefs()
      .then((raw) => {
        const p = raw as SavedUserPrefs;
        if (typeof p.selectedPrinterId === 'string' && p.selectedPrinterId) {
          setSelectedPrinterId(p.selectedPrinterId);
        }
        if (p.material && p.material in MATERIAL_DEFAULTS) {
          setMaterial(p.material);
        }
        if (p.nozzleDiameter && [0.2, 0.4, 0.6, 0.8].includes(p.nozzleDiameter)) {
          setNozzleDiameter(p.nozzleDiameter);
        }
        if (typeof p.highSpeedFilament === 'boolean') {
          setHighSpeedFilament(p.highSpeedFilament);
        }
        if (typeof p.lithophaneMode === 'boolean') {
          setLithophaneMode(p.lithophaneMode);
        }
        const effMatForSpool: MaterialType =
          p.material && ['pla', 'petg', 'abs', 'tpu'].includes(p.material)
            ? p.material
            : initMat;
        const matBounds = MATERIAL_DEFAULTS[effMatForSpool];
        const validSavedSpool =
          typeof p.spoolMinTemp === 'number' &&
          typeof p.spoolMaxTemp === 'number' &&
          p.spoolMaxTemp >= matBounds.nozzleMin &&
          p.spoolMinTemp <= matBounds.nozzleMax;
        if (validSavedSpool) {
          setSpoolMinTemp(p.spoolMinTemp as number);
          setSpoolMaxTemp(p.spoolMaxTemp as number);
        } else {
          setSpoolMinTemp(matBounds.recMin);
          setSpoolMaxTemp(matBounds.recMax);
        }
        if (p.qualityPreset) setQualityPreset(p.qualityPreset);
        if (typeof p.autoLeveling === 'boolean') setAutoLeveling(p.autoLeveling);
        if (Array.isArray(p.extrudersConfig) && p.extrudersConfig.length === 4) {
          setExtrudersConfig(
            p.extrudersConfig.map((s, idx) => ({
              ...DEFAULT_EXTRUDERS[idx],
              ...s,
              extruder_index: idx,
            })),
          );
        }
        if (typeof p.modelExtruder === 'number' && p.modelExtruder >= 0 && p.modelExtruder <= 3) {
          setModelExtruder(p.modelExtruder);
        }
        if (typeof p.supportExtruder === 'number' && p.supportExtruder >= 0 && p.supportExtruder <= 3) {
          setSupportExtruder(p.supportExtruder);
        }
        if (
          !suppressRestorePromptRef.current &&
          p.last_session &&
          typeof p.last_session.mesh_id === 'string' &&
          p.last_session.mesh_id &&
          typeof p.last_session.file_name === 'string' &&
          p.last_session.file_name
        ) {
          setPendingRestoreSession(p.last_session);
        }
      })
      .catch(() => {
        // Fallback a localStorage si el backend aún está iniciando
      })
      .finally(() => {
        prefsLoadedRef.current = true;
      });
  }, []);

  // Persistir última configuración del usuario en localStorage y en disco del backend
  useEffect(() => {
    const payload = {
      selectedPrinterId,
      material,
      nozzleDiameter,
      highSpeedFilament,
      lithophaneMode,
      spoolMinTemp,
      spoolMaxTemp,
      qualityPreset,
      autoLeveling,
      extrudersConfig,
      modelExtruder,
      supportExtruder,
    };
    try {
      window.localStorage.setItem(PREFS_STORAGE_KEY, JSON.stringify(payload));
    } catch {
      // Ignorar errores de cuota de localStorage
    }
    if (!prefsLoadedRef.current) return;
    const timer = window.setTimeout(() => {
      void saveUserPrefs(payload).catch(() => {});
    }, 250);
    return () => window.clearTimeout(timer);
  }, [
    selectedPrinterId,
    material,
    nozzleDiameter,
    highSpeedFilament,
    lithophaneMode,
    spoolMinTemp,
    spoolMaxTemp,
    qualityPreset,
    autoLeveling,
    extrudersConfig,
    modelExtruder,
    supportExtruder,
  ]);

  // Guardar última sesión de modelo importado en disco para ofrecer reabrirlo al iniciar
  useEffect(() => {
    if (!prefsLoadedRef.current || !meshId || !stlFile) return;
    const timer = window.setTimeout(() => {
      void saveUserPrefs({
        last_session: {
          mesh_id: meshId,
          file_name: stlFile.name,
          printer_id: selectedPrinterId,
          transform,
          part_extruder_map: partExtruderMap,
          z_color_ranges: zColorRanges,
          supports,
          support_type: supportType,
          support_on_build_plate_only: supportOnBuildPlateOnly,
          support_z_distance: supportZDistance,
          support_xy_distance: supportXyDistance,
          adhesion_type: adhesionType,
          brim_width_mm: brimWidthMm,
          scene_objects: sceneObjects,
          selected_object_ids: selectedObjectIds,
          support_blockers: supportBlockers,
          saved_at: new Date().toISOString(),
        },
      }).catch(() => {});
    }, 450);
    return () => window.clearTimeout(timer);
  }, [
    meshId,
    stlFile,
    selectedPrinterId,
    transform,
    partExtruderMap,
    zColorRanges,
    supports,
    supportType,
    supportOnBuildPlateOnly,
    supportZDistance,
    supportXyDistance,
    adhesionType,
    brimWidthMm,
    sceneObjects,
    selectedObjectIds,
    supportBlockers,
  ]);

  // Recalcular temperaturas/caudal de T0..T3 si cambia boquilla o perfil y negociar cama en Creator 5 Pro
  useEffect(() => {
    if (activeProfileId !== 'creator5_pro') return;
    setExtrudersConfig((prev) =>
      prev.map((slot) => {
        const calc = computeSlotThermalConfig(
          slot,
          activeProfileId,
          nozzleDiameter,
          volumetricLimits,
          highSpeedVolumetricLimits,
        );
        if (
          slot.nozzle_temp === calc.nozzleNormal &&
          slot.nozzle_temp_initial_layer === calc.nozzleInitial &&
          slot.max_volumetric_speed === calc.maxVolFlow
        ) {
          return slot;
        }
        return {
          ...slot,
          spool_min: calc.spoolMin,
          spool_max: calc.spoolMax,
          nozzle_temp: calc.nozzleNormal,
          nozzle_temp_initial_layer: calc.nozzleInitial,
          max_volumetric_speed: calc.maxVolFlow,
        };
      }),
    );
  }, [activeProfileId, nozzleDiameter, volumetricLimits, highSpeedVolumetricLimits]);

  useEffect(() => {
    if (activeProfileId !== 'creator5_pro') return;
    const bodySlots = extrudersConfig.filter((s) => s.material !== 'soporte');
    const primarySlot =
      extrudersConfig[modelExtruder]?.material !== 'soporte'
        ? extrudersConfig[modelExtruder]
        : bodySlots[0];
    const effBodyMat: MaterialType =
      primarySlot && primarySlot.material in MATERIAL_DEFAULTS
        ? (primarySlot.material as MaterialType)
        : material;

    if (primarySlot && !lithophaneMode && effBodyMat !== material) {
      handleChangeMaterial(effBodyMat);
    } else if (primarySlot && !lithophaneMode) {
      const matMeta = MATERIAL_DEFAULTS[effBodyMat];
      if (spoolMaxTemp < matMeta.nozzleMin || spoolMinTemp > matMeta.nozzleMax) {
        setSpoolMinTemp(matMeta.recMin);
        setSpoolMaxTemp(matMeta.recMax);
      }
    }

    const supportSlot = extrudersConfig[supportExtruder];
    const supMat = supportSlot?.material ?? effBodyMat;
    const syncKey = `${supMat}_${effBodyMat}_${nozzleDiameter}`;
    if (!lithophaneMode && lastSupportSyncKeyRef.current !== syncKey) {
      lastSupportSyncKeyRef.current = syncKey;
      if (supMat === 'soporte') {
        setSupportZDistance(0.15);
        setSupportXyDistance(computeDefaultSupportXY(effBodyMat, nozzleDiameter));
      } else if (supMat in MATERIAL_DEFAULTS) {
        const m = supMat as MaterialType;
        setSupportZDistance(MATERIAL_DEFAULTS[m].defaultSupportZ);
        setSupportXyDistance(computeDefaultSupportXY(m, nozzleDiameter));
      }
    }

    const distinctBody = new Set(bodySlots.map((s) => s.material));
    if (distinctBody.size > 1) {
      setBedTemp(negotiateMultiMaterialBedTemp(extrudersConfig.map((s) => s.material)));
    }
  }, [
    activeProfileId,
    extrudersConfig,
    modelExtruder,
    supportExtruder,
    nozzleDiameter,
    lithophaneMode,
  ]);

  // Recalcular automáticamente las 3 temperaturas óptimas según perfil, material, rango y HS
  useEffect(() => {
    const matMeta = MATERIAL_DEFAULTS[material];
    const effMin =
      spoolMaxTemp < matMeta.nozzleMin || spoolMinTemp > matMeta.nozzleMax
        ? matMeta.recMin
        : spoolMinTemp;
    const effMax =
      spoolMaxTemp < matMeta.nozzleMin || spoolMinTemp > matMeta.nozzleMax
        ? matMeta.recMax
        : spoolMaxTemp;
    if (effMin !== spoolMinTemp || effMax !== spoolMaxTemp) {
      setSpoolMinTemp(effMin);
      setSpoolMaxTemp(effMax);
    }
    const auto = computeAutoTemperatures(
      activeProfileId,
      material,
      effMin,
      effMax,
      highSpeedFilament,
      nozzleDiameter,
    );
    setNozzleTempInitial(auto.nozzleInitial);
    setNozzleTemp(auto.nozzleNormal);
    setBedTemp(auto.bed);
  }, [
    activeProfileId,
    material,
    spoolMinTemp,
    spoolMaxTemp,
    highSpeedFilament,
    nozzleDiameter,
  ]);

  const runAnalysis = async (
    printerId: PrinterId,
    nextTransform: ModelTransform,
    options: { file?: File; cachedMeshId?: string; preserveUserSettings?: boolean },
  ) => {
    const seq = ++analyzeSeqRef.current;
    setIsAnalyzing(true);
    setErrorMsg(null);
    setSliceResult(null);
    setSendPrintMsg(null);
    setGcodeText(null);
    try {
      let res: MeshAnalysisResponse;
      try {
        res = await analyzeMesh({
          printerId,
          file: options.cachedMeshId ? undefined : options.file,
          meshId: options.cachedMeshId,
          transform: nextTransform,
        });
      } catch (cachedErr) {
        if (options.cachedMeshId && stlFile) {
          res = await analyzeMesh({
            printerId,
            file: stlFile,
            transform: nextTransform,
          });
        } else {
          throw cachedErr;
        }
      }
      if (seq !== analyzeSeqRef.current) return;
      setMeshId(res.mesh_id);
      setAnalysis(res);
      if (!options.preserveUserSettings) {
        setSupports(res.suggests_supports);
        setAdhesionType(res.suggests_raft ? 'raft' : 'none');
      }

      // Al cargar un archivo .3mf nuevo, inicializar mapeo de partes y zonas de color hacia T0..T3
      // SIN sobrescribir los colores físicos reales configurados en los carretes T0..T3
      if (options.file) {
        const nextMap: Record<string, number> = {};
        if (!res.is_multicolor && res.multimaterial_parts && res.multimaterial_parts.length > 0) {
          for (const p of res.multimaterial_parts) {
            nextMap[p.part_id] = p.extruder;
          }
        }
        const zoneCount = Math.max(
          res.detected_extruder_count ?? 1,
          res.detected_filament_colors?.length ?? 0,
        );
        if (res.is_multicolor && zoneCount > 1) {
          for (let z = 0; z < Math.min(4, zoneCount); z += 1) {
            nextMap[`zone_${z}`] = z;
          }
        }
        setPartExtruderMap(nextMap);
      }
    } catch (err: unknown) {
      if (seq !== analyzeSeqRef.current) return;
      setAnalysis(null);
      setErrorMsg(
        err instanceof Error ? err.message : 'Error analizando el archivo STL.',
      );
    } finally {
      if (seq === analyzeSeqRef.current) {
        setIsAnalyzing(false);
      }
    }
  };

  const handleSelectPrinter = (id: PrinterId) => {
    setSelectedPrinterId(id);
    setAutoOrientMsg(null);
    setAiSupportStatus(null);
    setSendPrintMsg(null);
    setErrorMsg(null);
    if (!stlFile) {
      if (meshId) setMeshId(null);
      return;
    }
    if (meshId) {
      void runAnalysis(id, transform, { cachedMeshId: meshId });
    } else {
      void runAnalysis(id, transform, { file: stlFile });
    }
  };

  const handleSelectStl = (file: File) => {
    setStlFile(file);
    setMeshId(null);
    setSceneObjects([]);
    setSelectedObjectIds([]);
    setTransform(DEFAULT_TRANSFORM);
    setAutoOrientMsg(null);
    setAiReasoning(null);
    setAiProvider(null);
    setAiSupportStatus(null);
    setSendPrintMsg(null);
    void runAnalysis(selectedPrinterId, DEFAULT_TRANSFORM, { file });
  };

  const handleChangeTransform = (nextTransform: ModelTransform) => {
    setTransform(nextTransform);
    setAutoOrientMsg(null);
    if (meshId) {
      void runAnalysis(selectedPrinterId, nextTransform, { cachedMeshId: meshId });
    } else if (stlFile) {
      void runAnalysis(selectedPrinterId, nextTransform, { file: stlFile });
    }
  };

  const applyRotationToTransform = (
    prev: ModelTransform,
    rx: number,
    ry: number,
    rz: number,
  ): ModelTransform => ({
    ...prev,
    rotX: rx,
    rotY: ry,
    rotZ: rz,
    offsetX: 0,
    offsetY: 0,
    offsetZ: 0,
    dropToBed: true,
    ...(prev.instances && prev.instances.length > 0
      ? {
          instances: prev.instances.map((inst) => ({
            ...inst,
            rot_x: rx,
            rot_y: ry,
            rot_z: rz,
            offset_x: 0,
            offset_y: 0,
            offset_z: 0,
            drop_to_bed: true,
          })),
        }
      : {}),
  });

  const applyOrientationToScene = (
    opt: OrientationOption,
    targetObjectId?: string | null,
  ) => {
    if (sceneObjects.length > 0) {
      if (targetObjectId) {
        setSceneObjects((prev) =>
          prev.map((obj) =>
            obj.object_id === targetObjectId
              ? {
                  ...obj,
                  rot_x: opt.rotation.rx,
                  rot_y: opt.rotation.ry,
                  rot_z: opt.rotation.rz,
                  offset_z: 0,
                  drop_to_bed: true,
                }
              : obj,
          ),
        );
        return;
      }

      const perObj = opt.per_object_rotations;
      setSceneObjects((prev) => {
        const rotated = prev.map((obj) => {
          const r = perObj?.[obj.object_id] ?? opt.rotation;
          return {
            ...obj,
            rot_x: r.rx,
            rot_y: r.ry,
            rot_z: r.rz,
            offset_z: 0,
            drop_to_bed: true,
          };
        });
        return rotated.length > 1
          ? arrangeSceneObjectsOnBed(
              rotated,
              new Set(rotated.map((o) => o.object_id)),
              activePrinter,
            )
          : rotated;
      });
      return;
    }

    handleChangeTransform(
      applyRotationToTransform(
        transform,
        opt.rotation.rx,
        opt.rotation.ry,
        opt.rotation.rz,
      ),
    );
  };

  const handleAutoOrient = async () => {
    if (!meshId && !stlFile) return;
    setIsAutoOrienting(true);
    setErrorMsg(null);
    setSliceResult(null);
    setSendPrintMsg(null);
    setGcodeText(null);
    const seq = ++analyzeSeqRef.current;
    const singleSelectedObj =
      sceneObjects.length > 0 && selectedObjectIds.length === 1
        ? sceneObjects.find((o) => o.object_id === selectedObjectIds[0]) ?? null
        : null;
    try {
      const res = await requestAIOrientations({
        printerId: selectedPrinterId,
        material,
        meshId,
        file: meshId ? null : stlFile,
        scalePercent: singleSelectedObj?.scale_percent || transform.scalePercent || 100,
        objectId: singleSelectedObj?.object_id ?? null,
        sceneObjects: !singleSelectedObj && sceneObjects.length > 1 ? sceneObjects : undefined,
      });
      if (seq !== analyzeSeqRef.current) return;
      setMeshId(res.mesh_id);
      setOrientationsData(res);
      const rec =
        res.options.find((o) => o.id === res.recommended_id) ?? res.options[0];
      if (rec) {
        setSelectedOrientationId(rec.id);
        applyOrientationToScene(rec, res.target_object_id);
        setAutoOrientMsg(`${rec.title}: ${rec.explanation}`);
      }
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error
          ? err.message
          : 'Error al calcular orientaciones con IA.',
      );
    } finally {
      setIsAutoOrienting(false);
    }
  };

  const handleSelectOrientation = (opt: OrientationOption) => {
    setSelectedOrientationId(opt.id);
    setAutoOrientMsg(`${opt.title}: ${opt.explanation}`);
    applyOrientationToScene(opt, orientationsData?.target_object_id);
  };

  const handleSplitObjects = async () => {
    if (!meshId && !stlFile) return;
    setIsSplittingObjects(true);
    setErrorMsg(null);
    try {
      const res = await splitMeshObjects({
        printerId: selectedPrinterId,
        meshId,
        file: meshId ? null : stlFile,
      });
      setMeshId(res.mesh_id);
      const sx = Math.max(0.01, (transform.scaleX ?? transform.scalePercent) / 100);
      const sy = Math.max(0.01, (transform.scaleY ?? transform.scalePercent) / 100);
      const sz = Math.max(0.01, (transform.scaleZ ?? transform.scalePercent) / 100);
      const mappedObjs: SceneObjectTransform[] = res.scene_objects.map((o) => ({
        object_id: o.object_id,
        name: o.name,
        extruder: o.extruder,
        color_hex: o.color_hex,
        mesh_url: o.mesh_url,
        offset_x: Math.round(((transform.offsetX ?? 0) + (o.position?.[0] ?? 0) * sx) * 100) / 100,
        offset_y: Math.round(((transform.offsetY ?? 0) + (o.position?.[1] ?? 0) * sy) * 100) / 100,
        offset_z: Math.round(((o.position?.[2] ?? 0) * sz) * 100) / 100,
        rot_x: transform.rotX,
        rot_y: transform.rotY,
        rot_z: transform.rotZ,
        scale_percent: transform.scalePercent,
        scale_x: transform.scaleX ?? null,
        scale_y: transform.scaleY ?? null,
        scale_z: transform.scaleZ ?? null,
        drop_to_bed: transform.dropToBed ?? true,
        dimensions_mm: [
          Math.round(((o.dimensions_mm?.[0] ?? 0) * sx) * 100) / 100,
          Math.round(((o.dimensions_mm?.[1] ?? 0) * sy) * 100) / 100,
          Math.round(((o.dimensions_mm?.[2] ?? 0) * sz) * 100) / 100,
        ],
      }));
      setSceneObjects(mappedObjs);
      setSelectedObjectIds(mappedObjs[0]?.object_id ? [mappedObjs[0].object_id] : []);
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error dividiendo el modelo en objetos.',
      );
    } finally {
      setIsSplittingObjects(false);
    }
  };

  const handleMergeObjects = () => {
    setSceneObjects([]);
    setSelectedObjectIds([]);
  };

  const handleAutoArrange = async (instances: ModelInstanceTransform[]) => {
    if (!meshId) return;
    setIsAutoArranging(true);
    setErrorMsg(null);
    setSliceResult(null);
    setGcodeText(null);
    try {
      const res = await autoArrangeModels({
        printer_id: selectedPrinterId,
        mesh_id: meshId,
        instances,
        min_distance_mm: 6,
      });
      const act = res.instances[0];
      const nextTransform: ModelTransform = {
        ...transform,
        ...(act
          ? {
            offsetX: act.offset_x,
            offsetY: act.offset_y,
            offsetZ: act.offset_z,
          }
          : {}),
        instances: res.instances,
      };
      setTransform(nextTransform);
      setAutoOrientMsg(res.message);
      await runAnalysis(selectedPrinterId, nextTransform, { cachedMeshId: meshId });
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error al auto-ordenar instancias en cama.',
      );
    } finally {
      setIsAutoArranging(false);
    }
  };

  const handleFetchLayOnFaces = async (): Promise<LayOnFaceCandidate[]> => {
    if (!meshId && !stlFile) return [];
    const res = await fetchLayOnFaceCandidates({
      printerId: selectedPrinterId,
      meshId,
      file: meshId ? null : stlFile,
      transform,
    });
    return res.candidates;
  };

  const handleCutMesh = async ({
    cutZMm,
    tiltXDeg,
    tiltYDeg,
    keepMode,
  }: {
    cutZMm: number;
    tiltXDeg: number;
    tiltYDeg: number;
    keepMode: 'upper' | 'lower' | 'both';
  }) => {
    if (!meshId && !stlFile) return;
    setIsCuttingMesh(true);
    setErrorMsg(null);
    setSliceResult(null);
    setGcodeText(null);
    try {
      const res = await cutMeshByPlane({
        printerId: selectedPrinterId,
        meshId,
        file: meshId ? null : stlFile,
        cutZMm,
        tiltXDeg,
        tiltYDeg,
        keepMode,
        transform,
      });
      const nextFile = await fetchCachedMeshFile(res.mesh_id, `cut_${res.mesh_id}.stl`);
      setStlFile(nextFile);
      setMeshId(res.mesh_id);
      setTransform(DEFAULT_TRANSFORM);
      setAnalysis(res.analysis);
      setSupports(res.analysis.suggests_supports);
      setAdhesionType(res.analysis.suggests_raft ? 'raft' : 'none');
      setAutoOrientMsg(res.message);
      setPartExtruderMap({});
      if (res.parts_count > 1) {
        try {
          const splitRes = await splitMeshObjects({
            printerId: selectedPrinterId,
            meshId: res.mesh_id,
          });
          const mappedObjs: SceneObjectTransform[] = splitRes.scene_objects.map((o) => ({
            object_id: o.object_id,
            name: o.name,
            extruder: o.extruder,
            color_hex: o.color_hex,
            mesh_url: o.mesh_url,
            offset_x: o.position?.[0] ?? 0,
            offset_y: o.position?.[1] ?? 0,
            offset_z: o.position?.[2] ?? 0,
            rot_x: o.rotation?.[0] ?? 0,
            rot_y: o.rotation?.[1] ?? 0,
            rot_z: o.rotation?.[2] ?? 0,
            scale_percent: o.scale?.[0] ?? 100,
            scale_x: null,
            scale_y: null,
            scale_z: null,
            drop_to_bed: true,
            dimensions_mm: o.dimensions_mm ?? [0, 0, 0],
          }));
          setSceneObjects(mappedObjs);
          setSelectedObjectIds(mappedObjs.length > 0 ? [mappedObjs[0].object_id] : []);
          setMeshId(splitRes.mesh_id);
        } catch {
          setSceneObjects([]);
          setSelectedObjectIds([]);
        }
      } else {
        setSceneObjects([]);
        setSelectedObjectIds([]);
      }
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error ejecutando el corte geométrico.',
      );
    } finally {
      setIsCuttingMesh(false);
    }
  };

  const handleChangeMaterial = (nextMat: MaterialType) => {
    if (lithophaneMode && nextMat !== 'pla') {
      return;
    }
    const meta = MATERIAL_DEFAULTS[nextMat];
    setMaterial(nextMat);
    setSpoolMinTemp(meta.recMin);
    setSpoolMaxTemp(meta.recMax);
    setSupportZDistance(meta.defaultSupportZ);
    setSupportXyDistance(computeDefaultSupportXY(nextMat, nozzleDiameter));
    setAiReasoning(null);
    setAiSupportStatus(null);
  };

  const handleToggleLithophaneMode = (enabled: boolean) => {
    setLithophaneMode(enabled);
    setAiReasoning(null);
    setAiSupportStatus(null);
    if (enabled) {
      const plaMeta = MATERIAL_DEFAULTS.pla;
      setMaterial('pla');
      setSpoolMinTemp(plaMeta.recMin);
      setSpoolMaxTemp(plaMeta.recMax);
      setSupportZDistance(plaMeta.defaultSupportZ);
      setSupportXyDistance(computeDefaultSupportXY('pla', nozzleDiameter));
      setSupports(false);
      setAdhesionType('brim');
      setBrimWidthMm(8);
      setAdhesionLabel('Brim Exterior 8 mm · Gap 0.12 mm (Litofanía)');
      handleSelectDynamicProfile('litofania_hd');
    } else if (specializedProfileId.startsWith('litofania_')) {
      handleSelectDynamicProfile('estandar');
    }
  };

  const handleChangeNozzleDiameter = (nextNozzle: NozzleDiameter) => {
    setNozzleDiameter(nextNozzle);
    setSupportXyDistance(computeDefaultSupportXY(material, nextNozzle));
  };

  const skipNextAutoAuditRef = useRef(false);
  const sliceAbortRef = useRef<AbortController | null>(null);

  const runRealSlice = async (overrides?: {
    meshIdOverride?: string | null;
    transformOverride?: ModelTransform;
    supportsOverride?: boolean;
    supportTypeOverride?: SupportType;
    plateOnlyOverride?: boolean;
    zDistOverride?: number;
    xyDistOverride?: number;
    adhesionOverride?: AdhesionType;
    brimWidthOverride?: number;
    nozzleTempOverride?: number;
    bedTempOverride?: number;
    layerHeightOverride?: number | null;
    outerWallSpeedOverride?: number | null;
    flowRatioOverride?: number | null;
    infillDensityOverride?: number | null;
    fuzzySkinOverride?: boolean;
    fuzzySkinThicknessOverride?: number;
    fuzzySkinPointDistanceOverride?: number;
    aiStrategyLabelOverride?: string | null;
    profileOverrides?: Record<string, unknown>;
  }): Promise<{ res: SliceResponse; rawGcode: string }> => {
    const minBound = Math.min(spoolMinTemp, spoolMaxTemp - 5);
    const maxBound = Math.max(spoolMaxTemp, minBound + 5);
    const safeInitial = Math.min(maxBound, Math.max(minBound, nozzleTempInitial));
    const safeNormal =
      overrides?.nozzleTempOverride !== undefined
        ? overrides.nozzleTempOverride
        : Math.min(maxBound, Math.max(minBound, nozzleTemp));

    const effSupports = lithophaneMode
      ? false
      : overrides?.supportsOverride !== undefined
        ? overrides.supportsOverride
        : supports;
    const effAdhesion: AdhesionType = lithophaneMode
      ? 'brim'
      : (overrides?.adhesionOverride ?? adhesionType);
    const rawBrim =
      overrides?.brimWidthOverride !== undefined ? overrides.brimWidthOverride : brimWidthMm;
    const effBrim = lithophaneMode ? Math.max(8, Math.min(10, rawBrim)) : rawBrim;

    const effMeshId =
      overrides?.meshIdOverride !== undefined ? overrides.meshIdOverride : meshId;
    const effLh =
      overrides?.layerHeightOverride !== undefined ? overrides.layerHeightOverride : layerHeightOverride;
    const effOuterSpeed =
      overrides?.outerWallSpeedOverride !== undefined
        ? overrides.outerWallSpeedOverride
        : outerWallSpeedOverride;
    const effFlow =
      overrides?.flowRatioOverride !== undefined ? overrides.flowRatioOverride : flowRatioOverride;
    const effInfill =
      overrides?.infillDensityOverride !== undefined
        ? overrides.infillDensityOverride
        : infillDensityOverride;
    const effFuzzy =
      overrides?.fuzzySkinOverride !== undefined ? overrides.fuzzySkinOverride : fuzzySkin;
    const effFuzzyThick = overrides?.fuzzySkinThicknessOverride ?? fuzzySkinThickness;
    const effFuzzyDist = overrides?.fuzzySkinPointDistanceOverride ?? fuzzySkinPointDistance;
    const effStrategy =
      overrides?.aiStrategyLabelOverride !== undefined
        ? overrides.aiStrategyLabelOverride
        : aiStrategyLabel;

    const res = await sliceModel({
      printer_id: selectedPrinterId,
      material: lithophaneMode ? 'pla' : material,
      nozzle_temp: safeNormal,
      nozzle_temp_initial_layer: safeInitial,
      bed_temp: overrides?.bedTempOverride !== undefined ? overrides.bedTempOverride : bedTemp,
      nozzle_diameter: nozzleDiameter,
      high_speed_filament: highSpeedFilament,
      lithophane_mode: lithophaneMode,
      supports: effSupports,
      support_type: overrides?.supportTypeOverride ?? supportType,
      support_style: supportStyle,
      support_on_build_plate_only:
        overrides?.plateOnlyOverride !== undefined
          ? overrides.plateOnlyOverride
          : supportOnBuildPlateOnly,
      support_z_distance:
        overrides?.zDistOverride !== undefined ? overrides.zDistOverride : supportZDistance,
      support_xy_distance:
        overrides?.xyDistOverride !== undefined ? overrides.xyDistOverride : supportXyDistance,
      adhesion_type: effAdhesion,
      brim_width_mm: effBrim,
      ...(effLh !== null ? { layer_height_override: effLh } : {}),
      ...(effOuterSpeed !== null ? { outer_wall_speed_override: effOuterSpeed } : {}),
      ...(effFlow !== null ? { flow_ratio_override: effFlow } : {}),
      ...(effInfill !== null ? { infill_density_override: effInfill } : {}),
      fuzzy_skin: effFuzzy,
      fuzzy_skin_thickness: effFuzzyThick,
      fuzzy_skin_point_distance: effFuzzyDist,
      ...(effStrategy ? { ai_strategy_label: effStrategy } : {}),
      ...(stlFile?.name ? { model_filename: stlFile.name } : {}),
      prime_tower_mode: primeTowerEnabled ? 'ultra_save' : 'off',
      enable_prime_tower: primeTowerEnabled,
      enable_timelapse: enableTimelapse,
      auto_leveling: autoLeveling,
      quality_preset: qualityPreset,
      mesh_id: effMeshId,
      file: effMeshId ? null : stlFile,
      transform: overrides?.transformOverride ?? transform,
      layer_pauses: layerPauses,
      ...(aiQualityOverrides.length > 0 ? { quality_overrides: aiQualityOverrides } : {}),
      ...(primeTowerEnabled && primeTowerBrimOverride !== null
        ? {
            profile_overrides: {
              prime_tower_brim_width: primeTowerBrimOverride,
              ...(overrides?.profileOverrides ?? {}),
            },
          }
        : overrides?.profileOverrides && Object.keys(overrides.profileOverrides).length > 0
          ? { profile_overrides: overrides.profileOverrides }
          : {}),
      ...(supportBlockers.length > 0 ? { support_blockers: supportBlockers } : {}),
      ...(sceneObjects.length > 0 ? { scene_objects: sceneObjects } : {}),
      ...(activeProfileId === 'creator5_pro'
        ? {
          extruders_config: extrudersConfig,
          model_extruder: modelExtruder,
          support_extruder: supportExtruder,
          z_color_ranges: zColorRanges,
          part_extruder_map: partExtruderMap,
          ...(chamberTempTarget !== null ? { chamber_temp_target: chamberTempTarget } : {}),
        }
        : {}),
    }, sliceAbortRef.current?.signal);
    const rawGcode = await fetchGcodeText(res.gcode_url);
    if (res.applied_pauses && res.applied_pauses.length > 0) {
      setLayerPauses(res.applied_pauses);
    }
    return { res, rawGcode };
  };

  const syncPausesToGcode = async (nextPauses: LayerPauseItem[]) => {
    if (!sliceResult?.job_id) return;
    try {
      const res = await applyLayerPauses({
        jobId: sliceResult.job_id,
        printerId: selectedPrinterId,
        pauses: nextPauses,
      });
      setLayerPauses(res.applied_pauses);
      setGcodeText(res.gcode_text);
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error al inyectar pausas en el G-code.',
      );
    }
  };

  const handleAddLayerPause = (layer: number, zMm: number | null, note: string) => {
    const effLayer = Math.max(1, Math.round(layer));
    const next = [
      ...layerPauses.filter((p) => p.layer !== effLayer),
      { layer: effLayer, z_mm: zMm, note, source: 'manual' as const },
    ].sort((a, b) => a.layer - b.layer);
    setLayerPauses(next);
    void syncPausesToGcode(next);
  };

  const handleRemoveLayerPause = (layer: number) => {
    const next = layerPauses.filter((p) => p.layer !== layer);
    setLayerPauses(next);
    void syncPausesToGcode(next);
  };

  const refreshSavedProjects = async () => {
    setIsLoadingProjects(true);
    try {
      const [list, recents] = await Promise.all([
        fetchSavedProjects(),
        fetchRecentProjects(5).catch(() => []),
      ]);
      setSavedProjects(list);
      setRecentProjects(recents);
    } catch {
      // Silencioso si backend aún no tiene proyectos
    } finally {
      setIsLoadingProjects(false);
    }
  };

  const showProjectToast = (msg: string) => {
    setProjectToast(msg);
    window.setTimeout(() => {
      setProjectToast((cur) => (cur === msg ? null : cur));
    }, 3500);
  };

  const captureViewportThumbnail = (): string | null => {
    try {
      const canvas = document.querySelector('canvas');
      return canvas ? canvas.toDataURL('image/png') : null;
    } catch {
      return null;
    }
  };

  const saveCurrentProject = async (opts?: {
    forceNew?: boolean;
    customTitle?: string;
    overrideSlice?: SliceResponse | null;
    overrideAi?: AIAnalyzeModelResponse | null;
  }): Promise<FullProjectSummary | null> => {
    if (!stlFile && !meshId) return null;
    const effSlice = opts?.overrideSlice ?? sliceResult;
    const effAi = opts?.overrideAi ?? aiAnalysisResult;
    const targetProjectId = opts?.forceNew ? null : activeProjectId;
    const title =
      (opts?.customTitle || '').trim() ||
      effAi?.short_spanish_title?.trim() ||
      activeProjectTitle ||
      (stlFile?.name || 'Proyecto 3D').replace(/\.(stl|3mf)$/i, '');

    try {
      const saved = await saveFullProject({
        project_id: targetProjectId,
        title,
        original_filename: stlFile?.name || 'modelo.stl',
        printer_id: selectedPrinterId,
        material: lithophaneMode ? 'pla' : material,
        mesh_id: meshId,
        job_id: effSlice?.job_id ?? null,
        thumbnail_base64: captureViewportThumbnail(),
        state: {
          printer_id: selectedPrinterId,
          material: lithophaneMode ? 'pla' : material,
          nozzle_diameter: nozzleDiameter,
          high_speed_filament: highSpeedFilament,
          lithophane_mode: lithophaneMode,
          extruders_config: extrudersConfig,
          part_extruder_map: partExtruderMap,
          z_color_ranges: zColorRanges,
          transform,
          scene_objects: sceneObjects,
          selected_object_ids: selectedObjectIds,
          support_blockers: supportBlockers,
          supports,
          support_type: supportType,
          support_on_build_plate_only: supportOnBuildPlateOnly,
          support_z_distance: supportZDistance,
          support_xy_distance: supportXyDistance,
          adhesion_type: adhesionType,
          brim_width_mm: brimWidthMm,
          instances: (sceneObjects.length > 0
            ? sceneObjects.map((o, idx) => ({
                id: o.object_id,
                name: o.name,
                sourceSubmeshIndex: idx,
                position: [o.offset_x, o.offset_y, o.offset_z],
                rotation: [o.rot_x, o.rot_y, o.rot_z],
                scale: [
                  o.scale_x ?? o.scale_percent,
                  o.scale_y ?? o.scale_percent,
                  o.scale_z ?? o.scale_percent,
                ],
                drop_to_bed: o.drop_to_bed,
                overrides: o.overrides,
                assignedExtruder: o.extruder,
                supportPaintMap: o.support_paint_map,
                supportPaintMode: o.support_paint_mode,
              }))
            : (transform.instances ?? []).map((it, idx) => ({
                id: it.instance_id,
                name: `Pieza #${idx + 1}`,
                position: [it.offset_x, it.offset_y, it.offset_z],
                rotation: [it.rot_x, it.rot_y, it.rot_z],
                scale: [
                  it.scale_x ?? it.scale_percent,
                  it.scale_y ?? it.scale_percent,
                  it.scale_z ?? it.scale_percent,
                ],
                drop_to_bed: it.drop_to_bed,
                overrides: it.overrides,
                supportPaintMap: it.support_paint_map,
                supportPaintMode: it.support_paint_mode,
              }))),
          quality_preset: qualityPreset,
          ai_analysis_result: effAi ?? null,
          layer_pauses: layerPauses,
          mesh_id: meshId,
          job_id: effSlice?.job_id ?? null,
          sliced_profile_snapshot:
            effSlice?.sliced_profile_snapshot ?? slicedProfileSnapshot ?? null,
          slice_metrics: effSlice
            ? {
                estimated_time: effSlice.estimated_time,
                filament_grams: effSlice.filament_grams,
                filament_meters: effSlice.filament_meters,
              }
            : {},
        },
      });
      setActiveProjectId(saved.project_id);
      setActiveProjectTitle(saved.title);
      const recents = await fetchRecentProjects(5).catch(() => []);
      setRecentProjects(recents);
      showProjectToast(
        targetProjectId
          ? `Proyecto actualizado: ${saved.title}`
          : `Proyecto guardado: ${saved.title}`,
      );
      return saved;
    } catch {
      return null;
    }
  };

  const handleLoadFullProject = async (projectId: string) => {
    setErrorMsg(null);
    setProjectLoadState({
      active: true,
      progress: 20,
      subtitle: t.projectLoading.step1,
    });
    try {
      const proj = await fetchFullProject(projectId);
      const st = (proj.state || {}) as Record<string, unknown>;
      if (typeof proj.printer_id === 'string' && proj.printer_id) {
        setSelectedPrinterId(proj.printer_id as PrinterId);
      }
      if (typeof proj.material === 'string') {
        setMaterial(proj.material as MaterialType);
      }
      if (typeof st.nozzle_diameter === 'number') {
        setNozzleDiameter(st.nozzle_diameter as NozzleDiameter);
      }
      if (typeof st.high_speed_filament === 'boolean') {
        setHighSpeedFilament(st.high_speed_filament);
      }
      if (typeof st.lithophane_mode === 'boolean') {
        setLithophaneMode(st.lithophane_mode);
      }
      if (Array.isArray(st.extruders_config) && st.extruders_config.length === 4) {
        setExtrudersConfig(st.extruders_config as ExtruderSlotConfig[]);
      }
      if (st.part_extruder_map && typeof st.part_extruder_map === 'object') {
        setPartExtruderMap(st.part_extruder_map as Record<string, number>);
      }
      if (Array.isArray(st.z_color_ranges)) {
        setZColorRanges(st.z_color_ranges as ZColorRange[]);
      }
      if (Array.isArray(st.layer_pauses)) {
        setLayerPauses(st.layer_pauses as LayerPauseItem[]);
      }
      if (st.ai_analysis_result && typeof st.ai_analysis_result === 'object') {
        setAiAnalysisResult(st.ai_analysis_result as AIAnalyzeModelResponse);
      }
      if (st.sliced_profile_snapshot && typeof st.sliced_profile_snapshot === 'object') {
        setSlicedProfileSnapshot(st.sliced_profile_snapshot as SlicedProfileSnapshot);
      } else {
        setSlicedProfileSnapshot(null);
      }
      const nextTransform =
        st.transform && typeof st.transform === 'object'
          ? (st.transform as ModelTransform)
          : DEFAULT_TRANSFORM;
      setTransform(nextTransform);
      if (typeof st.supports === 'boolean') setSupports(st.supports);
      if (typeof st.support_type === 'string') setSupportType(st.support_type as SupportType);
      if (typeof st.support_on_build_plate_only === 'boolean') {
        setSupportOnBuildPlateOnly(st.support_on_build_plate_only);
      }
      if (typeof st.support_z_distance === 'number') setSupportZDistance(st.support_z_distance);
      if (typeof st.support_xy_distance === 'number') setSupportXyDistance(st.support_xy_distance);
      if (typeof st.adhesion_type === 'string') setAdhesionType(st.adhesion_type as AdhesionType);
      if (typeof st.brim_width_mm === 'number') setBrimWidthMm(st.brim_width_mm);
      if (Array.isArray(st.support_blockers)) {
        setSupportBlockers(st.support_blockers as SupportBlockerItem[]);
      }
      setActiveProjectId(proj.project_id);
      setActiveProjectTitle(proj.title);
      if (proj.gcode_text) {
        setGcodeText(proj.gcode_text);
      }

      if (proj.model_url) {
        setProjectLoadState({
          active: true,
          progress: 55,
          subtitle: t.projectLoading.step2,
        });
        const resp = await fetch(getProjectModelFileUrl(proj.project_id));
        if (resp.ok) {
          const blob = await resp.blob();
          const loadedFile = new File([blob], proj.original_filename || 'modelo.stl', {
            type: 'application/octet-stream',
          });
          setStlFile(loadedFile);
          const restoredMeshId =
            typeof st.mesh_id === 'string' && st.mesh_id ? st.mesh_id : null;
          let activeMid = restoredMeshId;
          if (restoredMeshId) {
            setMeshId(restoredMeshId);
            await runAnalysis(
              (proj.printer_id as PrinterId) || selectedPrinterId,
              nextTransform,
              { cachedMeshId: restoredMeshId, preserveUserSettings: true },
            );
          } else {
            await runAnalysis(
              (proj.printer_id as PrinterId) || selectedPrinterId,
              nextTransform,
              { file: loadedFile, preserveUserSettings: true },
            );
          }

          setProjectLoadState({
            active: true,
            progress: 85,
            subtitle: t.projectLoading.step3,
          });
          const savedSceneObjs = Array.isArray(st.scene_objects)
            ? (st.scene_objects as SceneObjectTransform[])
            : [];
          if (savedSceneObjs.length > 0) {
            try {
              const splitRes = await splitMeshObjects({
                printerId: (proj.printer_id as PrinterId) || selectedPrinterId,
                meshId: activeMid || undefined,
                file: activeMid ? undefined : loadedFile,
              });
              const byId = new Map(savedSceneObjs.map((o) => [o.object_id, o]));
              const restoredObjs: SceneObjectTransform[] = splitRes.scene_objects.map((fresh, idx) => {
                const savedMatch = byId.get(fresh.object_id) ?? savedSceneObjs[idx];
                if (savedMatch) {
                  return {
                    ...savedMatch,
                    mesh_url: fresh.mesh_url,
                  };
                }
                return {
                  object_id: fresh.object_id,
                  name: fresh.name,
                  extruder: fresh.extruder,
                  color_hex: fresh.color_hex,
                  mesh_url: fresh.mesh_url,
                  offset_x: fresh.position?.[0] ?? 0,
                  offset_y: fresh.position?.[1] ?? 0,
                  offset_z: fresh.position?.[2] ?? 0,
                  rot_x: fresh.rotation?.[0] ?? 0,
                  rot_y: fresh.rotation?.[1] ?? 0,
                  rot_z: fresh.rotation?.[2] ?? 0,
                  scale_percent: fresh.scale?.[0] ?? 100,
                  scale_x: null,
                  scale_y: null,
                  scale_z: null,
                  drop_to_bed: true,
                  dimensions_mm: fresh.dimensions_mm ?? [0, 0, 0],
                };
              });
              setSceneObjects(restoredObjs);
              setMeshId(splitRes.mesh_id);
              const savedSel = Array.isArray(st.selected_object_ids)
                ? (st.selected_object_ids as string[])
                : [];
              setSelectedObjectIds(
                savedSel.length > 0
                  ? savedSel
                  : restoredObjs.length > 0
                    ? [restoredObjs[0].object_id]
                    : [],
              );
            } catch {
              setSceneObjects(savedSceneObjs);
            }
          } else {
            setSceneObjects([]);
            setSelectedObjectIds([]);
          }
        }
      }
      setProjectLoadState({
        active: true,
        progress: 100,
        subtitle: t.projectLoading.step4,
      });
      showProjectToast(`Proyecto abierto: ${proj.title}`);
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error al abrir el proyecto guardado.',
      );
    } finally {
      setProjectLoadState((prev) => ({ ...prev, active: false }));
    }
  };

  const handleOpenProjectNewWindow = (projectId: string) => {
    const pyApi = (
      window as unknown as {
        pywebview?: { api?: { open_new_window?: (pid?: string | null) => void } };
      }
    ).pywebview?.api;
    if (pyApi?.open_new_window) {
      pyApi.open_new_window(projectId);
    } else {
      const wsid = Math.random().toString(36).slice(2, 10);
      window.open(
        `/?window_session_id=${wsid}&project_id=${encodeURIComponent(projectId)}`,
        '_blank',
      );
    }
  };

  const handleDeleteFullProject = async (projectId: string) => {
    try {
      await deleteFullProject(projectId);
      setRecentProjects((prev) => prev.filter((p) => p.project_id !== projectId));
      if (activeProjectId === projectId) {
        setActiveProjectId(null);
        setActiveProjectTitle(null);
      }
    } catch {
      // silencioso
    }
  };

  useEffect(() => {
    (window as unknown as { __nikkHasModel?: boolean }).__nikkHasModel = Boolean(
      stlFile || meshId,
    );
    const fullTitle = activeProjectTitle
      ? `Nikk Slicer — ${activeProjectTitle}`
      : 'Nikk Slicer';
    document.title = fullTitle;
    const pyApi = (
      window as unknown as {
        pywebview?: { api?: { set_window_title?: (t: string) => void } };
      }
    ).pywebview?.api;
    pyApi?.set_window_title?.(fullTitle);
  }, [stlFile, meshId, activeProjectTitle]);

  useEffect(() => {
    if (typeof BroadcastChannel === 'undefined') return;
    const ch = new BroadcastChannel('nikk_slicer_windows');
    const shortTitle =
      activeProjectTitle ||
      (stlFile?.name ? stlFile.name.replace(/\.(stl|3mf)$/i, '') : 'Sin proyecto');

    const announce = () => {
      const payload = {
        type: 'announce',
        windowId: windowSessionId,
        title: shortTitle,
        color: windowAccent.hex,
        updatedAt: Date.now(),
      };
      setOpenWindows((prev) => ({
        ...prev,
        [windowSessionId]: {
          windowId: windowSessionId,
          title: shortTitle,
          color: windowAccent.hex,
          updatedAt: Date.now(),
        },
      }));
      ch.postMessage(payload);
    };

    ch.onmessage = (ev) => {
      const data = ev.data as {
        type?: string;
        windowId?: string;
        targetWindowId?: string;
        title?: string;
        color?: string;
        updatedAt?: number;
      };
      if (!data?.type) return;
      if (data.type === 'announce' && data.windowId) {
        setOpenWindows((prev) => ({
          ...prev,
          [data.windowId!]: {
            windowId: data.windowId!,
            title: data.title || 'Proyecto 3D',
            color: data.color || '#22d3ee',
            updatedAt: Date.now(),
          },
        }));
      } else if (data.type === 'ping') {
        announce();
      } else if (data.type === 'bye' && data.windowId) {
        setOpenWindows((prev) => {
          const next = { ...prev };
          delete next[data.windowId!];
          return next;
        });
      } else if (data.type === 'focus' && data.targetWindowId === windowSessionId) {
        window.focus();
      }
    };

    announce();
    ch.postMessage({ type: 'ping' });
    const interval = window.setInterval(() => {
      announce();
      const now = Date.now();
      setOpenWindows((prev) => {
        const next: typeof prev = {};
        for (const [k, v] of Object.entries(prev)) {
          if (k === windowSessionId || now - v.updatedAt < 8000) {
            next[k] = v;
          }
        }
        return next;
      });
    }, 2500);

    const onUnload = () => {
      ch.postMessage({ type: 'bye', windowId: windowSessionId });
    };
    window.addEventListener('beforeunload', onUnload);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('beforeunload', onUnload);
      ch.postMessage({ type: 'bye', windowId: windowSessionId });
      ch.close();
    };
  }, [windowSessionId, windowAccent.hex, activeProjectTitle, stlFile?.name]);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const pid = params.get('project_id');
    if (pid) {
      suppressRestorePromptRef.current = true;
      void handleLoadFullProject(pid);
    }
    void fetchRecentProjects(5)
      .then((list) => setRecentProjects(list))
      .catch(() => {});
    void fetchSystemEnvironment()
      .then((env) => {
        if (!env.has_primary_slicer) {
          setSystemSetupOpen(true);
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const onOpenProjects = () => {
      setExternalProjectsOpen(true);
    };
    const onSaveProject = () => {
      void saveCurrentProject();
    };
    const onSaveProjectAs = () => {
      const suggested =
        activeProjectTitle ||
        aiAnalysisResult?.short_spanish_title ||
        (stlFile?.name || 'Proyecto 3D').replace(/\.(stl|3mf)$/i, '');
      const custom = window.prompt('Guardar proyecto como:', suggested);
      if (custom && custom.trim()) {
        void saveCurrentProject({ forceNew: true, customTitle: custom.trim() });
      }
    };
    const onCloseProject = () => {
      analyzeSeqRef.current += 1;
      setStlFile(null);
      setMeshId(null);
      setAnalysis(null);
      setIsAnalyzing(false);
      setActiveProjectId(null);
      setActiveProjectTitle(null);
      setSceneObjects([]);
      setSelectedObjectIds([]);
      setTransform(DEFAULT_TRANSFORM);
      setIsSlicing(false);
      setSliceResult(null);
      setSlicedProfileSnapshot(null);
      setProfileDrawerOpen(false);
      setGcodeText(null);
      setInitialSliceSnapshot(null);
      setSupportBlockers([]);
      setLayerPauses([]);
      setZColorRanges([]);
      setPartExtruderMap({});
      setAutoOrientMsg(null);
      setIsAutoOrienting(false);
      setIsAutoArranging(false);
      setIsCuttingMesh(false);
      setIsSplittingObjects(false);
      setOrientationsData(null);
      setSelectedOrientationId(null);
      setIsOptimizingAI(false);
      setAiReasoning(null);
      setAiProvider(null);
      setIsOptimizingSupportAI(false);
      setAiSupportStatus(null);
      setIsAnalyzingAI(false);
      setAiAnalysisResult(null);
      setAiQualityOverrides([]);
      setIsOptimizingSliceAI(false);
      setAiOptimizeComparison(null);
      setLayerHeightOverride(null);
      setOuterWallSpeedOverride(null);
      setFlowRatioOverride(null);
      setInfillDensityOverride(null);
      setFuzzySkin(false);
      setFuzzySkinThickness(0.25);
      setFuzzySkinPointDistance(0.4);
      setAiStrategyLabel(null);
      setSupports(false);
      setSupportType('tree(auto)');
      setSupportStyle('default');
      setSupportOnBuildPlateOnly(true);
      setAdhesionType(lithophaneMode ? 'brim' : 'none');
      setAdhesionLabel(null);
      setPrimeTowerEnabled(false);
      setPrimeTowerReason(null);
      setPrimeTowerBrimOverride(null);
      setErrorMsg(null);
      setSendPrintMsg(null);
      setUploadActionMode(null);
      setProjectToast(null);
      setExternalProjectsOpen(false);
      setQuoteCalculatorOpen(false);
      setPendingRestoreSession(null);
      setActiveTab('wizard');
      resetSessionHistory();
      void clearLastSession().catch(() => {});
    };
    const onOpenSpecific = (ev: Event) => {
      const detail = (ev as CustomEvent<{ projectId?: string }>).detail;
      if (detail?.projectId) {
        void handleLoadFullProject(detail.projectId);
      }
    };
    const onKeyDown = (ev: KeyboardEvent) => {
      if (!(ev.metaKey || ev.ctrlKey)) return;
      const k = ev.key.toLowerCase();
      if (k === 's') {
        ev.preventDefault();
        if (ev.shiftKey) {
          onSaveProjectAs();
        } else {
          onSaveProject();
        }
      } else if (k === 'o') {
        ev.preventDefault();
        onOpenProjects();
      } else if (
        k === 'w' &&
        Boolean((window as unknown as { pywebview?: unknown }).pywebview)
      ) {
        ev.preventDefault();
        onCloseProject();
      }
    };

    window.addEventListener('nikk:menu-open-projects', onOpenProjects);
    window.addEventListener('nikk:menu-save-project', onSaveProject);
    window.addEventListener('nikk:menu-save-project-as', onSaveProjectAs);
    window.addEventListener('nikk:menu-close-project', onCloseProject);
    window.addEventListener('nikk:open-project', onOpenSpecific);
    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('nikk:menu-open-projects', onOpenProjects);
      window.removeEventListener('nikk:menu-save-project', onSaveProject);
      window.removeEventListener('nikk:menu-save-project-as', onSaveProjectAs);
      window.removeEventListener('nikk:menu-close-project', onCloseProject);
      window.removeEventListener('nikk:open-project', onOpenSpecific);
      window.removeEventListener('keydown', onKeyDown);
    };
  });

  const handleSelectDynamicProfile = (
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
  ) => {
    const effLh = typeof layerHeightHintMm === 'number' ? layerHeightHintMm : null;
    if (
      id === 'estandar' ||
      id === 'mecanico_resistente' ||
      id === 'alta_velocidad' ||
      id === 'rapidez_extrema'
    ) {
      setSpecializedProfileId('none');
      setQualityPreset(id);
      setLayerHeightOverride(effLh);
      setOuterWallSpeedOverride(speedHintMmS ?? null);
      setInfillDensityOverride(id === 'mecanico_resistente' ? 25 : null);
      setFuzzySkin(false);
      setAiStrategyLabel(
        effLh !== null ? `${id === 'mecanico_resistente' ? 'Mecánico / Estructural' : 'Estándar'} (${effLh.toFixed(2)} mm)` : null,
      );
      return;
    }

    setQualityPreset('estandar');
    setSpecializedProfileId(id);
    if (id === 'detalle_fino') {
      setLayerHeightOverride(effLh ?? 0.12);
      setOuterWallSpeedOverride(speedHintMmS ?? 55);
      setInfillDensityOverride(15);
      setFuzzySkin(false);
      setAiStrategyLabel(`Detalle Fino (${(effLh ?? 0.12).toFixed(2)} mm)`);
    } else if (id === 'detalle_optimo') {
      setLayerHeightOverride(effLh ?? 0.16);
      setOuterWallSpeedOverride(speedHintMmS ?? null);
      setInfillDensityOverride(15);
      setFuzzySkin(false);
      setAiStrategyLabel(`Detalle Óptimo (${(effLh ?? 0.16).toFixed(2)} mm)`);
    } else if (id === 'rapido_funcional') {
      setLayerHeightOverride(effLh ?? 0.24);
      setOuterWallSpeedOverride(speedHintMmS ?? null);
      setInfillDensityOverride(12);
      setFuzzySkin(false);
      setAiStrategyLabel(`Rápido Funcional (${(effLh ?? 0.24).toFixed(2)} mm)`);
    } else if (id === 'piel_difusa') {
      setLayerHeightOverride(effLh ?? 0.2);
      setOuterWallSpeedOverride(speedHintMmS ?? null);
      setInfillDensityOverride(12);
      setFuzzySkin(true);
      setFuzzySkinPointDistance(0.15);
      setFuzzySkinThickness(0.4);
      setAiStrategyLabel(`Piel Difusa / Textura (${(effLh ?? 0.2).toFixed(2)} mm)`);
    } else if (id === 'litofania_ultra') {
      setLayerHeightOverride(effLh ?? 0.08);
      setOuterWallSpeedOverride(speedHintMmS ?? 45);
      setInfillDensityOverride(100);
      setFuzzySkin(false);
      setSupports(false);
      setAiStrategyLabel(`Litofanía Ultra HD (${(effLh ?? 0.08).toFixed(2)} mm)`);
    } else if (id === 'litofania_hd') {
      setLayerHeightOverride(effLh ?? 0.12);
      setOuterWallSpeedOverride(speedHintMmS ?? 50);
      setInfillDensityOverride(100);
      setFuzzySkin(false);
      setSupports(false);
      setAiStrategyLabel(`Litofanía HD (${(effLh ?? 0.12).toFixed(2)} mm)`);
    } else if (id === 'litofania_vertical') {
      setLayerHeightOverride(effLh ?? 0.12);
      setOuterWallSpeedOverride(speedHintMmS ?? 48);
      setInfillDensityOverride(100);
      setFuzzySkin(false);
      setSupports(false);
      setAdhesionType('brim');
      setBrimWidthMm(10);
      setAiStrategyLabel(`Litofanía Vertical Estable (${(effLh ?? 0.12).toFixed(2)} mm)`);
    }
  };

  const handleAnalyzeModelAI = async (
    overrideSlice?: SliceResponse | null,
  ): Promise<AIAnalyzeModelResponse | null> => {
    const effSlice = overrideSlice ?? sliceResult;
    // Primera instrucción síncrona para respuesta visual instantánea (0 ms)
    setIsAnalyzingAI(true);
    if ((!meshId && !stlFile) || !effSlice || !analysis) {
      setIsAnalyzingAI(false);
      return null;
    }
    setErrorMsg(null);
    setSendPrintMsg(null);
    try {
      const res = await requestAIAnalyzeModel({
        printer_id: selectedPrinterId,
        material: lithophaneMode ? 'pla' : material,
        filename: stlFile?.name || 'modelo.stl',
        nozzle_diameter: nozzleDiameter,
        high_speed_filament: highSpeedFilament,
        lithophane_mode: lithophaneMode,
        dimensions_mm: analysis.dimensions_mm,
        volume_cm3:
          (analysis.dimensions_mm.x * analysis.dimensions_mm.y * analysis.dimensions_mm.z) / 1000,
        base_contact_area_mm2: analysis.base_contact_area_mm2,
        overhang_ratio: analysis.overhang_ratio,
        parts_count: analysis.multimaterial_parts?.length ?? 1,
        is_multicolor: Boolean(analysis.is_multicolor),
        detected_extruder_count: analysis.detected_extruder_count ?? 1,
        has_supports: Boolean(supports),
        layer_height: layerHeightOverride ?? undefined,
        color_list: extrudersConfig.map((e) => e.color_hex),
        hero_face_detected:
          Boolean(analysis.is_multicolor) ||
          /robot|char|fig|head|bust|mini|toy|personaje|figura|sheep|oveja/i.test(
            stlFile?.name || '',
          ),
        current_slice_metrics: {
          estimated_time: effSlice.estimated_time,
          estimated_time_seconds: effSlice.estimated_time_seconds,
          filament_grams: effSlice.filament_grams,
          support_weight_g: effSlice.support_weight_g ?? 0,
          support_percentage: effSlice.support_percentage ?? 0,
        },
      });
      setAiAnalysisResult(res);
      if (res.short_spanish_title && !activeProjectTitle) {
        setActiveProjectTitle(res.short_spanish_title);
      }
      if (res.model_category === 'lithophane_flat') {
        if (material !== 'pla') setMaterial('pla');
        if (!lithophaneMode) handleToggleLithophaneMode(true);
      }
      return res;
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Error analizando el modelo con IA.');
      return null;
    } finally {
      setIsAnalyzingAI(false);
    }
  };

  const handleOptimizeSliceWithAI = async (
    presetId: string,
    userNotes = '',
    targetLayerHeight?: number,
  ) => {
    if ((!meshId && !stlFile) || !sliceResult || !analysis) return;
    setIsOptimizingSliceAI(true);
    setErrorMsg(null);
    setSendPrintMsg(null);

    const baselineSnap = initialSliceSnapshot ?? {
      sliceResult,
      gcodeText,
      transform: { ...transform },
      analysis,
      supports,
      supportType,
      supportOnBuildPlateOnly,
      supportZDistance,
      supportXyDistance,
      adhesionType,
      brimWidthMm,
      nozzleTemp,
      bedTemp,
      layerHeightOverride,
      outerWallSpeedOverride,
      flowRatioOverride,
      infillDensityOverride,
      fuzzySkin,
      aiStrategyLabel,
    };
    if (!initialSliceSnapshot) {
      setInitialSliceSnapshot(baselineSnap);
    }

    try {
      const opt: AIOptimizeSliceResponse = await requestAIOptimizeSlice({
        printer_id: selectedPrinterId,
        material: lithophaneMode ? 'pla' : material,
        filename: stlFile?.name || 'modelo.stl',
        nozzle_diameter: nozzleDiameter,
        high_speed_filament: highSpeedFilament,
        lithophane_mode: lithophaneMode,
        preset_id: presetId,
        ...(typeof targetLayerHeight === 'number' ? { target_layer_height: targetLayerHeight } : {}),
        user_notes: userNotes,
        mesh_id: meshId,
        scale_percent: transform.scalePercent,
        rot_x: transform.rotX,
        rot_y: transform.rotY,
        rot_z: transform.rotZ,
        dimensions_mm: analysis.dimensions_mm,
        overhang_ratio: analysis.overhang_ratio,
        base_contact_area_mm2: analysis.base_contact_area_mm2,
        current_support_config: {
          enabled: supports,
          support_type: supportType,
          placement: supportOnBuildPlateOnly ? 'buildplate' : 'everywhere',
          support_top_z_distance: supportZDistance,
          support_object_xy_distance: supportXyDistance,
        },
        current_slice_metrics: {
          estimated_time: sliceResult.estimated_time,
          filament_grams: sliceResult.filament_grams,
          support_weight_g: sliceResult.support_weight_g ?? 0,
        },
      });

      const nextTransform: ModelTransform = opt.apply_rotation
        ? {
            ...transform,
            rotX: opt.rot_x,
            rotY: opt.rot_y,
            rotZ: opt.rot_z,
          }
        : { ...transform };

      const effSup = lithophaneMode ? false : opt.supports_required;
      const effAdh: AdhesionType = lithophaneMode ? 'brim' : opt.adhesion_type;

      setTransform(nextTransform);
      setSupports(effSup);
      setSupportType(opt.support_type);
      setSupportOnBuildPlateOnly(opt.support_on_build_plate_only);
      setSupportZDistance(opt.support_z_distance);
      setSupportXyDistance(opt.support_xy_distance);
      setAdhesionType(effAdh);
      setBrimWidthMm(opt.brim_width_mm);
      if (opt.nozzle_temp) setNozzleTemp(opt.nozzle_temp);
      setLayerHeightOverride(opt.layer_height);
      setOuterWallSpeedOverride(opt.outer_wall_speed ?? null);
      setFlowRatioOverride(opt.flow_ratio ?? null);
      setInfillDensityOverride(opt.infill_density ?? null);
      setFuzzySkin(opt.fuzzy_skin);
      setFuzzySkinThickness(opt.fuzzy_skin_thickness);
      setFuzzySkinPointDistance(opt.fuzzy_skin_point_distance);
      setAiStrategyLabel(opt.strategy_label);

      const { res, rawGcode } = await runRealSlice({
        transformOverride: nextTransform,
        supportsOverride: effSup,
        supportTypeOverride: opt.support_type,
        plateOnlyOverride: opt.support_on_build_plate_only,
        zDistOverride: opt.support_z_distance,
        xyDistOverride: opt.support_xy_distance,
        adhesionOverride: effAdh,
        brimWidthOverride: opt.brim_width_mm,
        nozzleTempOverride: opt.nozzle_temp ?? undefined,
        layerHeightOverride: opt.layer_height,
        outerWallSpeedOverride: opt.outer_wall_speed ?? null,
        flowRatioOverride: opt.flow_ratio ?? null,
        infillDensityOverride: opt.infill_density ?? null,
        fuzzySkinOverride: opt.fuzzy_skin,
        fuzzySkinThicknessOverride: opt.fuzzy_skin_thickness,
        fuzzySkinPointDistanceOverride: opt.fuzzy_skin_point_distance,
        aiStrategyLabelOverride: opt.strategy_label,
      });

      setSliceResult(res);
      setGcodeText(rawGcode);
      setAiOptimizeComparison({
        strategyLabel: opt.strategy_label,
        explanation: opt.explanation,
        before: {
          time: baselineSnap.sliceResult.estimated_time,
          grams: baselineSnap.sliceResult.filament_grams,
          supportGrams: baselineSnap.sliceResult.support_weight_g ?? 0,
          rot: `${baselineSnap.transform.rotX.toFixed(0)}°/${baselineSnap.transform.rotY.toFixed(0)}°/${baselineSnap.transform.rotZ.toFixed(0)}°`,
        },
        after: {
          time: res.estimated_time,
          grams: res.filament_grams,
          supportGrams: res.support_weight_g ?? 0,
          rot: `${nextTransform.rotX.toFixed(0)}°/${nextTransform.rotY.toFixed(0)}°/${nextTransform.rotZ.toFixed(0)}°`,
          layerHeight: opt.layer_height,
          fuzzySkin: opt.fuzzy_skin,
        },
      });
      void refreshSavedProjects();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Error optimizando laminado con IA.');
    } finally {
      setIsOptimizingSliceAI(false);
    }
  };

  const handleRollbackToInitialSlice = () => {
    if (!initialSliceSnapshot) return;
    setSliceResult(initialSliceSnapshot.sliceResult);
    setGcodeText(initialSliceSnapshot.gcodeText);
    setTransform(initialSliceSnapshot.transform);
    setAnalysis(initialSliceSnapshot.analysis);
    setSupports(initialSliceSnapshot.supports);
    setSupportType(initialSliceSnapshot.supportType);
    setSupportOnBuildPlateOnly(initialSliceSnapshot.supportOnBuildPlateOnly);
    setSupportZDistance(initialSliceSnapshot.supportZDistance);
    setSupportXyDistance(initialSliceSnapshot.supportXyDistance);
    setAdhesionType(initialSliceSnapshot.adhesionType);
    setBrimWidthMm(initialSliceSnapshot.brimWidthMm);
    setNozzleTemp(initialSliceSnapshot.nozzleTemp);
    setBedTemp(initialSliceSnapshot.bedTemp);
    setLayerHeightOverride(initialSliceSnapshot.layerHeightOverride);
    setOuterWallSpeedOverride(initialSliceSnapshot.outerWallSpeedOverride);
    setFlowRatioOverride(initialSliceSnapshot.flowRatioOverride);
    setInfillDensityOverride(initialSliceSnapshot.infillDensityOverride);
    setFuzzySkin(initialSliceSnapshot.fuzzySkin);
    setAiStrategyLabel(initialSliceSnapshot.aiStrategyLabel);
    setAiOptimizeComparison(null);
    setSendPrintMsg('Restaurado al laminado inicial.');
  };

  const handleRollbackToUnsliced = () => {
    setSliceResult(null);
    setGcodeText(null);
    setTransform(DEFAULT_TRANSFORM);
    setLayerHeightOverride(null);
    setOuterWallSpeedOverride(null);
    setFlowRatioOverride(null);
    setInfillDensityOverride(null);
    setFuzzySkin(false);
    setAiStrategyLabel(null);
    setAiAnalysisResult(null);
    setAiOptimizeComparison(null);
    setInitialSliceSnapshot(null);
    setSendPrintMsg('Modelo restaurado al estado inicial sin laminar.');
  };

  const handleLoadSavedProject = (proj: SavedProjectRecord) => {
    if (proj.printer_id) setSelectedPrinterId(proj.printer_id);
    if (proj.material) setMaterial(proj.material);
    if (proj.nozzle_diameter) setNozzleDiameter(proj.nozzle_diameter as NozzleDiameter);
    if (proj.quality_preset) setQualityPreset(proj.quality_preset);
    if (proj.transform) {
      setTransform({
        ...DEFAULT_TRANSFORM,
        scalePercent: proj.transform.scale_percent ?? 100,
        rotX: proj.transform.rot_x ?? 0,
        rotY: proj.transform.rot_y ?? 0,
        rotZ: proj.transform.rot_z ?? 0,
      });
    }
    const p = proj.params || {};
    if (typeof p.nozzle_temp === 'number') setNozzleTemp(p.nozzle_temp);
    if (typeof p.bed_temp === 'number') setBedTemp(p.bed_temp);
    if (typeof p.chamber_temp_target === 'number') setChamberTempTarget(p.chamber_temp_target);
    setLayerHeightOverride(typeof p.layer_height === 'number' ? p.layer_height : null);
    setOuterWallSpeedOverride(typeof p.outer_wall_speed === 'number' ? p.outer_wall_speed : null);
    setFlowRatioOverride(typeof p.flow_ratio === 'number' ? p.flow_ratio : null);
    setInfillDensityOverride(typeof p.infill_density === 'number' ? p.infill_density : null);
    setFuzzySkin(Boolean(p.fuzzy_skin));
    if (typeof p.supports === 'boolean') setSupports(p.supports);
    if (typeof p.support_type === 'string') setSupportType(p.support_type as SupportType);
    if (typeof p.support_z_distance === 'number') setSupportZDistance(p.support_z_distance);
    if (typeof p.support_xy_distance === 'number') setSupportXyDistance(p.support_xy_distance);
    if (typeof p.adhesion_type === 'string') setAdhesionType(p.adhesion_type as AdhesionType);
    if (typeof p.brim_width_mm === 'number') setBrimWidthMm(p.brim_width_mm);
    setSendPrintMsg(`Parámetros del proyecto '${proj.model_filename}' cargados.`);
  };

  const handleApplyDefectCorrection = async (
    proj: SavedProjectRecord,
    corrected: Record<string, unknown>,
  ) => {
    handleLoadSavedProject(proj);
    const lh = typeof corrected.layer_height_override === 'number' ? corrected.layer_height_override : null;
    const spd = typeof corrected.outer_wall_speed_override === 'number' ? corrected.outer_wall_speed_override : null;
    const flw = typeof corrected.flow_ratio_override === 'number' ? corrected.flow_ratio_override : null;
    const inf = typeof corrected.infill_density_override === 'number' ? corrected.infill_density_override : null;
    const nTemp = typeof corrected.nozzle_temp === 'number' ? corrected.nozzle_temp : undefined;
    const bTemp = typeof corrected.bed_temp === 'number' ? corrected.bed_temp : undefined;
    const sup = typeof corrected.supports === 'boolean' ? corrected.supports : undefined;
    const supType = typeof corrected.support_type === 'string' ? (corrected.support_type as SupportType) : undefined;
    const zDist = typeof corrected.support_z_distance === 'number' ? corrected.support_z_distance : undefined;
    const xyDist = typeof corrected.support_xy_distance === 'number' ? corrected.support_xy_distance : undefined;
    const adh = typeof corrected.adhesion_type === 'string' ? (corrected.adhesion_type as AdhesionType) : undefined;
    const brimW = typeof corrected.brim_width_mm === 'number' ? corrected.brim_width_mm : undefined;
    const fz = typeof corrected.fuzzy_skin === 'boolean' ? corrected.fuzzy_skin : undefined;

    if (lh !== null) setLayerHeightOverride(lh);
    if (spd !== null) setOuterWallSpeedOverride(spd);
    if (flw !== null) setFlowRatioOverride(flw);
    if (inf !== null) setInfillDensityOverride(inf);
    if (nTemp !== undefined) setNozzleTemp(nTemp);
    if (bTemp !== undefined) setBedTemp(bTemp);
    if (sup !== undefined) setSupports(sup);
    if (supType !== undefined) setSupportType(supType);
    if (zDist !== undefined) setSupportZDistance(zDist);
    if (xyDist !== undefined) setSupportXyDistance(xyDist);
    if (adh !== undefined) setAdhesionType(adh);
    if (brimW !== undefined) setBrimWidthMm(brimW);
    if (fz !== undefined) setFuzzySkin(fz);

    if (!stlFile && !meshId) return;
    setIsSlicing(true);
    setErrorMsg(null);
    try {
      const { res, rawGcode } = await runRealSlice({
        layerHeightOverride: lh,
        outerWallSpeedOverride: spd,
        flowRatioOverride: flw,
        infillDensityOverride: inf,
        nozzleTempOverride: nTemp,
        bedTempOverride: bTemp,
        supportsOverride: sup,
        supportTypeOverride: supType,
        zDistOverride: zDist,
        xyDistOverride: xyDist,
        adhesionOverride: adh,
        brimWidthOverride: brimW,
        fuzzySkinOverride: fz,
        aiStrategyLabelOverride: 'Corrección Defecto IA',
      });
      setSliceResult(res);
      setGcodeText(rawGcode);
      setSendPrintMsg('Perfil corregido aplicado y re-laminado con éxito.');
      void refreshSavedProjects();
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Error re-laminando tras corrección.');
    } finally {
      setIsSlicing(false);
    }
  };

  const handleAISupportOrient = async () => {
    if ((!meshId && !stlFile) || !sliceResult) return;
    setIsOptimizingSupportAI(true);
    setErrorMsg(null);
    setSendPrintMsg(null);

    // 1. Snapshot completo del laminado baseline real actual
    const baselineSlice = sliceResult;
    const baselineGcodeText = gcodeText;
    const baselineMeshId = meshId;
    const baselineTransform = { ...transform };
    const baselineAnalysis = analysis;
    const baselineSupports = supports;
    const baselineSupportType = supportType;
    const baselinePlateOnly = supportOnBuildPlateOnly;
    const baselineZDist = supportZDistance;
    const baselineXyDist = supportXyDistance;
    const baselineAdhesion = adhesionType;
    const baselineBrimWidth = brimWidthMm;
    const baselineAdhesionLabel = adhesionLabel;
    const baselineAutoOrientMsg = autoOrientMsg;
    const baselineAiSupportStatus = aiSupportStatus;

    const sanitizeAngle = (deg: number): number => {
      if (!Number.isFinite(deg)) return 0;
      const mod = ((deg % 360) + 360) % 360;
      if (mod < 0.01 || Math.abs(mod - 360) < 0.01 || Math.abs(deg) < 0.01) return 0;
      return Number(deg.toFixed(2));
    };

    try {
      // 2. Obtener propuesta IA con métricas reales del baseline
      const aiRes = await requestAISupportOrient({
        printerId: selectedPrinterId,
        material: lithophaneMode ? 'pla' : material,
        nozzleDiameter,
        highSpeedFilament,
        lithophaneMode,
        meshId: baselineMeshId,
        file: baselineMeshId ? null : stlFile,
        scalePercent: baselineTransform.scalePercent,
        rotX: baselineTransform.rotX,
        rotY: baselineTransform.rotY,
        rotZ: baselineTransform.rotZ,
        currentSupportConfig: {
          enabled: baselineSupports,
          support_type: baselineSupportType,
          placement: baselinePlateOnly ? 'buildplate' : 'everywhere',
          support_top_z_distance: baselineZDist,
          support_object_xy_distance: baselineXyDist,
        },
        currentSliceMetrics: {
          estimated_time_str: baselineSlice.estimated_time,
          estimated_time_seconds:
            baselineSlice.estimated_time_seconds ||
            parseTimeStrToSeconds(baselineSlice.estimated_time),
          filament_weight_g: baselineSlice.filament_grams,
          filament_length_m: baselineSlice.filament_meters,
          support_time_seconds: baselineSlice.support_time_seconds ?? 0,
          support_weight_g: baselineSlice.support_weight_g ?? 0,
          support_percentage: baselineSlice.support_percentage ?? 0,
        },
      });

      const nextTransform: ModelTransform =
        aiRes.apply_rotation !== false
          ? {
            ...DEFAULT_TRANSFORM,
            scalePercent: aiRes.scale_percent,
            rotX: sanitizeAngle(aiRes.rot_x),
            rotY: sanitizeAngle(aiRes.rot_y),
            rotZ: sanitizeAngle(aiRes.rot_z),
          }
          : {
            ...baselineTransform,
            scalePercent: aiRes.scale_percent,
            rotX: sanitizeAngle(baselineTransform.rotX),
            rotY: sanitizeAngle(baselineTransform.rotY),
            rotZ: sanitizeAngle(baselineTransform.rotZ),
          };

      const nextXy =
        aiRes.support_xy_distance ?? computeDefaultSupportXY(material, nozzleDiameter);
      const nextBrim =
        typeof aiRes.brim_width_mm === 'number' ? aiRes.brim_width_mm : baselineBrimWidth;

      const effSupReq = lithophaneMode ? false : aiRes.supports_required;
      const effAdh: AdhesionType = lithophaneMode ? 'brim' : aiRes.adhesion_type;
      const effBrimW = lithophaneMode
        ? Math.max(8, Math.min(10, nextBrim || 8))
        : nextBrim;

      // Aplicar propuesta en el visor y controles
      skipNextAutoAuditRef.current = true;
      setMeshId(aiRes.mesh_id);
      setTransform(nextTransform);
      setAnalysis(aiRes.analysis);
      setSupports(effSupReq);
      setSupportType(aiRes.support_type);
      setSupportOnBuildPlateOnly(aiRes.support_on_build_plate_only);
      setSupportZDistance(aiRes.support_z_distance);
      setSupportXyDistance(nextXy);
      setAdhesionType(effAdh);
      setBrimWidthMm(effBrimW);
      if (aiRes.adhesion_label) setAdhesionLabel(aiRes.adhesion_label);

      const sameRotation =
        Math.abs(nextTransform.rotX - baselineTransform.rotX) < 0.5 &&
        Math.abs(nextTransform.rotY - baselineTransform.rotY) < 0.5 &&
        Math.abs(nextTransform.rotZ - baselineTransform.rotZ) < 0.5 &&
        Math.abs(nextTransform.scalePercent - baselineTransform.scalePercent) < 0.2;
      const sameParams =
        sameRotation &&
        aiRes.supports_required === baselineSupports &&
        aiRes.support_type === baselineSupportType &&
        aiRes.support_on_build_plate_only === baselinePlateOnly &&
        aiRes.adhesion_type === baselineAdhesion &&
        Math.abs(aiRes.support_z_distance - baselineZDist) < 0.01 &&
        Math.abs(nextXy - baselineXyDist) < 0.01;

      const baseSec =
        baselineSlice.estimated_time_seconds ||
        parseTimeStrToSeconds(baselineSlice.estimated_time);
      const baseGrams = baselineSlice.filament_grams;

      if (sameParams) {
        setAiSupportStatus({
          ...aiRes,
          badge_label: `Tu Orientación Actual Ya Es la Más Rápida (${baselineSlice.estimated_time})`,
          estimated_savings_summary: `Corte verificado: ${baselineSlice.estimated_time} (${baseGrams} g)`,
          reasoning:
            aiRes.reasoning ||
            'La posición y parámetros actuales ofrecen el menor tiempo de impresión y menor gasto de filamento sin comprometer estabilidad.',
        });
        setAutoOrientMsg(
          `Tu Orientación Actual Ya Es la Más Rápida (${baselineSlice.estimated_time})`,
        );
        return;
      }

      // 3. Re-laminar automáticamente con el motor real
      const { res: newSlice, rawGcode: newGcodeText } = await runRealSlice({
        meshIdOverride: aiRes.mesh_id,
        transformOverride: nextTransform,
        supportsOverride: aiRes.supports_required,
        supportTypeOverride: aiRes.support_type,
        plateOnlyOverride: aiRes.support_on_build_plate_only,
        zDistOverride: aiRes.support_z_distance,
        xyDistOverride: nextXy,
        adhesionOverride: aiRes.adhesion_type,
        brimWidthOverride: nextBrim,
      });

      const newSec =
        newSlice.estimated_time_seconds || parseTimeStrToSeconds(newSlice.estimated_time);
      const newGrams = newSlice.filament_grams;
      const timeDiff = newSec - baseSec;
      const gramsDiff = Number((newGrams - baseGrams).toFixed(2));
      const comparisonLine = `Antes: ${baselineSlice.estimated_time} (${baseGrams} g) → Ahora: ${newSlice.estimated_time} (${newGrams} g)`;

      const overhangPct = (aiRes.analysis.overhang_ratio || 0) * 100;
      const baseArea = aiRes.analysis.base_contact_area_mm2 || 0;
      const prevOverhangPct = (baselineAnalysis?.overhang_ratio ?? aiRes.analysis.overhang_ratio) * 100;
      const prevBaseArea = baselineAnalysis?.base_contact_area_mm2 ?? baseArea;
      const addedMandatorySupports =
        !baselineSupports && aiRes.supports_required && overhangPct > 15;
      const addedMandatoryAdhesion =
        baselineAdhesion === 'none' &&
        aiRes.adhesion_type !== 'none' &&
        (baseArea < 60 || prevBaseArea < 60 || baseArea < 350);
      const needsSafetySupport = addedMandatorySupports || addedMandatoryAdhesion;

      // 4. Decisión real Antes vs. Después
      if (timeDiff < -5 || (timeDiff <= 10 && gramsDiff < -0.1)) {
        // Caso A: Mejora real verificada por el slicer
        setSliceResult(newSlice);
        setGcodeText(newGcodeText);
        const savedParts: string[] = [];
        if (timeDiff < 0) savedParts.push(formatSecondsDiff(Math.abs(timeDiff)));
        if (gramsDiff < 0) savedParts.push(`${Math.abs(gramsDiff).toFixed(2)} g`);
        const title =
          timeDiff < -5
            ? `Optimización Aplicada · Ahorro Real -${formatSecondsDiff(Math.abs(timeDiff))}`
            : `Optimización Aplicada · Ahorro ${Math.abs(gramsDiff).toFixed(2)} g`;
        const supDesc = aiRes.supports_required
          ? `soportes ${aiRes.support_type === 'tree(auto)' ? 'en árbol' : 'normales'} (Z=${aiRes.support_z_distance.toFixed(2)} mm / XY=${nextXy.toFixed(2)} mm)`
          : 'puentes optimizados sin soportes';
        const adhDesc =
          aiRes.adhesion_type === 'brim'
            ? `y brim de ${Math.round(nextBrim)} mm`
            : aiRes.adhesion_type === 'raft'
              ? 'y balsa mínima'
              : 'y sin balsa adicional';
        setAiSupportStatus({
          ...aiRes,
          badge_label: title,
          estimated_savings_summary: `${comparisonLine}${savedParts.length ? ` · Ahorro de ${savedParts.join(' y ')}` : ''}`,
          reasoning: `Se re-laminó con ${supDesc} ${adhDesc}. ${aiRes.reasoning}`,
        });
        setAutoOrientMsg(`${title} · ${comparisonLine}`);
      } else if (needsSafetySupport) {
        // Caso B: Sube tiempo/material por seguridad obligatoria (voladizos críticos >15% o base <60 mm²)
        setSliceResult(newSlice);
        setGcodeText(newGcodeText);
        const extraTimeTxt = timeDiff > 0 ? ` (+${formatSecondsDiff(timeDiff)})` : '';
        const supLabel =
          aiRes.support_type === 'tree(auto)' ? 'soportes en árbol' : 'soportes normales';
        const adhLabel =
          aiRes.adhesion_type === 'brim'
            ? ` y brim de ${Math.round(nextBrim)} mm`
            : aiRes.adhesion_type === 'raft'
              ? ' y balsa mínima'
              : '';
        const title = `Soportes y Adherencia Activados por Seguridad${extraTimeTxt}`;
        setAiSupportStatus({
          ...aiRes,
          badge_status: 'SOPORTES_OBLIGATORIOS',
          badge_label: title,
          estimated_savings_summary: comparisonLine,
          reasoning: `El tiempo cambió de ${baselineSlice.estimated_time} a ${newSlice.estimated_time}${extraTimeTxt} porque se activaron ${supLabel}${adhLabel} (Z=${aiRes.support_z_distance.toFixed(2)} mm / XY=${nextXy.toFixed(2)} mm), indispensables para sostener voladizos críticos del ${overhangPct.toFixed(1)}% y evitar que la pieza se despegue.`,
        });
        setAutoOrientMsg(`${title} · ${comparisonLine}`);
      } else if (overhangPct >= prevOverhangPct - 1.5) {
        // Caso C: Empeora tiempo/material sin aportar seguridad ni reducir voladizos -> REVERSIÓN AUTOMÁTICA
        skipNextAutoAuditRef.current = true;
        setMeshId(baselineMeshId);
        setTransform(baselineTransform);
        setAnalysis(baselineAnalysis);
        setSupports(baselineSupports);
        setSupportType(baselineSupportType);
        setSupportOnBuildPlateOnly(baselinePlateOnly);
        setSupportZDistance(baselineZDist);
        setSupportXyDistance(baselineXyDist);
        setAdhesionType(baselineAdhesion);
        setBrimWidthMm(baselineBrimWidth);
        setAdhesionLabel(baselineAdhesionLabel);
        setSliceResult(baselineSlice);
        setGcodeText(baselineGcodeText);
        const title = `Tu Orientación Actual Ya Es la Más Rápida (${baselineSlice.estimated_time})`;
        setAiSupportStatus({
          ...aiRes,
          rot_x: baselineTransform.rotX,
          rot_y: baselineTransform.rotY,
          rot_z: baselineTransform.rotZ,
          scale_percent: baselineTransform.scalePercent,
          apply_rotation: false,
          badge_status: baselineSupports ? 'SOPORTES_OBLIGATORIOS' : 'SIN_SOPORTES',
          badge_label: title,
          estimated_savings_summary: `Mantenido: ${baselineSlice.estimated_time} (${baseGrams} g) · Alternativa descartada: ${newSlice.estimated_time} (${newGrams} g)`,
          reasoning: `Se probó una orientación alternativa (tardaba ${newSlice.estimated_time} y gastaba ${newGrams} g frente a ${baselineSlice.estimated_time} y ${baseGrams} g actual). Se mantuvo tu configuración original porque ya es más rápida y gasta menos material.`,
        });
        setAutoOrientMsg(baselineAutoOrientMsg ?? title);
      } else {
        // Caso intermedio: redujo voladizos notablemente
        setSliceResult(newSlice);
        setGcodeText(newGcodeText);
        setAiSupportStatus({
          ...aiRes,
          badge_label: 'Configuración Ajustada para Reducir Voladizos',
          estimated_savings_summary: comparisonLine,
        });
        setAutoOrientMsg(`Voladizos reducidos a ${overhangPct.toFixed(1)}% · ${comparisonLine}`);
      }
    } catch (err: unknown) {
      // Revertir ante error en re-laminado para no dejar estado inconsistente
      skipNextAutoAuditRef.current = true;
      setMeshId(baselineMeshId);
      setTransform(baselineTransform);
      setAnalysis(baselineAnalysis);
      setSupports(baselineSupports);
      setSupportType(baselineSupportType);
      setSupportOnBuildPlateOnly(baselinePlateOnly);
      setSupportZDistance(baselineZDist);
      setSupportXyDistance(baselineXyDist);
      setAdhesionType(baselineAdhesion);
      setBrimWidthMm(baselineBrimWidth);
      setAdhesionLabel(baselineAdhesionLabel);
      setSliceResult(baselineSlice);
      setGcodeText(baselineGcodeText);
      setAiSupportStatus(baselineAiSupportStatus);
      setAutoOrientMsg(baselineAutoOrientMsg);
      setErrorMsg(
        err instanceof Error
          ? err.message
          : 'Error analizando y re-laminando con DeepSeek.',
      );
    } finally {
      setIsOptimizingSupportAI(false);
    }
  };

  // Auditoría automática con DeepSeek (debounce 600 ms) SOLO cuando hay un modelo cargado (meshId != null)
  const aiAuditSeqRef = useRef(0);
  useEffect(() => {
    if (!meshId || !analysis) {
      setIsOptimizingAI(false);
      setAiReasoning(null);
      setAiProvider(null);
      return;
    }
    if (skipNextAutoAuditRef.current) {
      skipNextAutoAuditRef.current = false;
      return;
    }

    const seq = ++aiAuditSeqRef.current;
    const timer = window.setTimeout(() => {
      setIsOptimizingAI(true);
      fetchAIRecommendation({
        printer_id: selectedPrinterId,
        material: lithophaneMode ? 'pla' : material,
        dimensions_mm: analysis.dimensions_mm,
        overhang_ratio: analysis.overhang_ratio,
        base_contact_area_mm2: analysis.base_contact_area_mm2,
        is_watertight: analysis.is_watertight,
        fits_in_volume: analysis.fits_in_volume,
        nozzle_diameter: nozzleDiameter,
        high_speed_filament: highSpeedFilament,
        lithophane_mode: lithophaneMode,
        multimaterial_parts_count: analysis.multimaterial_parts?.length ?? 0,
        detected_extruder_count: analysis.detected_extruder_count ?? 1,
        is_multicolor: Boolean(analysis.is_multicolor),
        extruder_colors: extrudersConfig.map((s) => s.color_hex),
        extruders_config: activeProfileId === 'creator5_pro' ? extrudersConfig : undefined,
        extruder_triangle_percentages: analysis.extruder_triangle_percentages,
      })
        .then((rec) => {
          if (seq !== aiAuditSeqRef.current) return;
          setSupports(lithophaneMode ? false : rec.supports);
          setSupportType(rec.support_type);
          setSupportOnBuildPlateOnly(rec.support_on_build_plate_only);
          setSupportZDistance(rec.support_z_distance);
          setSupportXyDistance(
            rec.support_xy_distance ?? computeDefaultSupportXY(material, nozzleDiameter),
          );
          setAdhesionType(lithophaneMode ? 'brim' : rec.adhesion_type);
          if (typeof rec.brim_width_mm === 'number') {
            setBrimWidthMm(
              lithophaneMode ? Math.max(8, Math.min(10, rec.brim_width_mm)) : rec.brim_width_mm,
            );
          }
          setAdhesionLabel(rec.adhesion_label || null);
          if (typeof rec.prime_tower_enabled === 'boolean') {
            setPrimeTowerEnabled(rec.prime_tower_enabled);
          }
          setPrimeTowerReason(rec.prime_tower_reason || null);
          setAiReasoning(rec.reasoning);
          setAiProvider(rec.provider);
        })
        .catch(() => {
          // Silencioso en auditoría de fondo para no interrumpir flujo manual
        })
        .finally(() => {
          if (seq === aiAuditSeqRef.current) {
            setIsOptimizingAI(false);
          }
        });
    }, 600);

    return () => {
      window.clearTimeout(timer);
    };
  }, [
    meshId,
    analysis,
    selectedPrinterId,
    material,
    nozzleDiameter,
    highSpeedFilament,
    lithophaneMode,
    spoolMinTemp,
    spoolMaxTemp,
  ]);

  const handleSlice = async (
    profileOverrides?: Record<string, unknown>,
    directOverrides?: Parameters<typeof runRealSlice>[0],
  ) => {
    if (!stlFile && !meshId) return;
    sliceAbortRef.current?.abort();
    const ctrl = new AbortController();
    sliceAbortRef.current = ctrl;
    setIsSlicing(true);
    setErrorMsg(null);
    setSendPrintMsg(null);

    try {
      const mergedOverrides =
        profileOverrides && Object.keys(profileOverrides).length > 0
          ? { ...(directOverrides ?? {}), profileOverrides }
          : directOverrides;
      const { res, rawGcode } = await runRealSlice(mergedOverrides);
      setSliceResult(res);
      if (res.sliced_profile_snapshot) {
        setSlicedProfileSnapshot(res.sliced_profile_snapshot);
      }
      setGcodeText(rawGcode);
      if (!aiAnalysisResult) {
        const aiRes = await handleAnalyzeModelAI(res);
        await saveCurrentProject({ overrideSlice: res, overrideAi: aiRes });
      } else {
        await saveCurrentProject({ overrideSlice: res });
      }
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error ejecutando el laminado.',
      );
    } finally {
      if (sliceAbortRef.current === ctrl) {
        sliceAbortRef.current = null;
      }
      setIsSlicing(false);
    }
  };

  const handleCancelSlice = () => {
    sliceAbortRef.current?.abort();
    sliceAbortRef.current = null;
    setIsSlicing(false);
    setErrorMsg('Laminado cancelado por el usuario.');
  };

  const handleSendToPrinter = async (
    mode: 'network' | 'usb_serial' | 'sd_volume',
    sdPath?: string,
    startPrint = true,
    overrideAutoLeveling?: boolean,
    customFilename?: string,
  ) => {
    if (!sliceResult) return;
    setUploadActionMode(startPrint ? 'upload_and_print' : 'upload_only');
    setSendPrintMsg(null);
    setErrorMsg(null);
    try {
      const res = await uploadJobToPrinter(selectedPrinterId, {
        job_id: sliceResult.job_id,
        start_print: startPrint,
        mode,
        sd_volume_path: sdPath,
        enable_timelapse: enableTimelapse,
        auto_leveling:
          overrideAutoLeveling !== undefined ? overrideAutoLeveling : autoLeveling,
        custom_filename: customFilename,
      });
      setSendPrintMsg(res.message);
      void saveCurrentProject({ overrideSlice: sliceResult });
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error enviando G-code a la impresora.',
      );
    } finally {
      setUploadActionMode(null);
    }
  };

  const configuredSdVolume =
    printersConfig?.printers[selectedPrinterId]?.sd_volume_path ??
    Object.values(printersConfig?.printers ?? {}).find(
      (p) => p.profile_id === 'ender3_s1_pro',
    )?.sd_volume_path ??
    '';

  const handleSelectStlRef = useRef(handleSelectStl);
  handleSelectStlRef.current = handleSelectStl;

  const handleSliceRef = useRef(handleSlice);
  handleSliceRef.current = handleSlice;

  // Sincronización en vivo del estado abierto hacia MCP (/api/live/state)
  useEffect(() => {
    const timer = window.setTimeout(() => {
      void fetch('/api/live/state', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model_filename: stlFile?.name ?? null,
          mesh_id: meshId,
          job_id: sliceResult?.job_id ?? null,
          printer_id: selectedPrinterId,
          material,
          quality_preset: qualityPreset,
          layer_height_override: layerHeightOverride,
          infill_density_override: infillDensityOverride,
          outer_wall_speed_override: outerWallSpeedOverride,
          flow_ratio_override: flowRatioOverride,
          nozzle_temp: nozzleTemp,
          bed_temp: bedTemp,
          supports,
          adhesion_type: adhesionType,
          brim_width_mm: brimWidthMm,
          part_extruder_map: partExtruderMap,
          slice_metrics: sliceResult
            ? {
                estimated_time: sliceResult.estimated_time,
                filament_grams: sliceResult.filament_grams,
                filament_meters: sliceResult.filament_meters,
              }
            : null,
          sliced_profile_snapshot: sliceResult?.sliced_profile_snapshot ?? slicedProfileSnapshot,
          updated_at: new Date().toISOString(),
        }),
      }).catch(() => {});
    }, 400);
    return () => window.clearTimeout(timer);
  }, [
    stlFile?.name,
    meshId,
    sliceResult,
    slicedProfileSnapshot,
    selectedPrinterId,
    material,
    qualityPreset,
    layerHeightOverride,
    infillDensityOverride,
    outerWallSpeedOverride,
    flowRatioOverride,
    nozzleTemp,
    bedTemp,
    supports,
    adhesionType,
    brimWidthMm,
    partExtruderMap,
  ]);

  // Polling de comandos en vivo desde MCP (/api/live/commands/poll)
  useEffect(() => {
    const id = window.setInterval(async () => {
      try {
        const resp = await fetch('/api/live/commands/poll');
        if (!resp.ok) return;
        const data = (await resp.json()) as {
          commands?: Array<{
            id: string;
            action: string;
            params?: Record<string, unknown>;
            reslice?: boolean;
          }>;
        };
        const cmds = data.commands ?? [];
        if (cmds.length === 0) return;

        for (const cmd of cmds) {
          if (cmd.action !== 'update_profile_and_reslice') continue;
          const p = cmd.params ?? {};
          const direct: Parameters<typeof runRealSlice>[0] = {};

          if (typeof p.layer_height_mm === 'number') {
            setLayerHeightOverride(p.layer_height_mm);
            direct.layerHeightOverride = p.layer_height_mm;
          }
          if (typeof p.infill_density === 'number') {
            setInfillDensityOverride(p.infill_density);
            direct.infillDensityOverride = p.infill_density;
          }
          if (typeof p.outer_wall_speed === 'number') {
            setOuterWallSpeedOverride(p.outer_wall_speed);
            direct.outerWallSpeedOverride = p.outer_wall_speed;
          }
          if (typeof p.flow_ratio === 'number') {
            setFlowRatioOverride(p.flow_ratio);
            direct.flowRatioOverride = p.flow_ratio;
          }
          if (typeof p.nozzle_temp === 'number') {
            setNozzleTemp(p.nozzle_temp);
            direct.nozzleTempOverride = p.nozzle_temp;
          }
          if (typeof p.bed_temp === 'number') {
            setBedTemp(p.bed_temp);
            direct.bedTempOverride = p.bed_temp;
          }
          if (typeof p.supports === 'boolean') {
            setSupports(p.supports);
            direct.supportsOverride = p.supports;
          }
          if (typeof p.lithophane_mode === 'boolean') {
            setLithophaneMode(p.lithophane_mode);
          }
          if (p.adhesion_type === 'none' || p.adhesion_type === 'brim' || p.adhesion_type === 'raft') {
            setAdhesionType(p.adhesion_type);
            direct.adhesionOverride = p.adhesion_type;
          }
          if (typeof p.brim_width_mm === 'number') {
            setBrimWidthMm(p.brim_width_mm);
            direct.brimWidthOverride = p.brim_width_mm;
          }
          if (p.part_extruder_map && typeof p.part_extruder_map === 'object') {
            setPartExtruderMap(p.part_extruder_map as Record<string, number>);
          }

          const profOv =
            p.profile_overrides && typeof p.profile_overrides === 'object'
              ? (p.profile_overrides as Record<string, unknown>)
              : undefined;

          showProjectToast(
            cmd.reslice !== false
              ? 'Perfil actualizado vía MCP — re-laminando en vivo...'
              : 'Perfil actualizado vía MCP.',
          );

          if (cmd.reslice !== false) {
            void handleSliceRef.current(profOv, direct);
          }
        }
      } catch {
        // Silencioso si backend reinicia
      }
    }, 1500);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    const hasFiles = (e: DragEvent) =>
      Array.from(e.dataTransfer?.types ?? []).includes('Files');

    const onDragEnter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragCounterRef.current += 1;
      setIsDraggingFile(true);
    };

    const onDragOver = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      if (e.dataTransfer) {
        e.dataTransfer.dropEffect = 'copy';
      }
    };

    const onDragLeave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragCounterRef.current = Math.max(0, dragCounterRef.current - 1);
      if (dragCounterRef.current === 0) {
        setIsDraggingFile(false);
      }
    };

    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      dragCounterRef.current = 0;
      setIsDraggingFile(false);

      const files = Array.from(e.dataTransfer?.files ?? []);
      if (files.length === 0) return;

      const valid = files.find((f) => /\.(stl|3mf)$/i.test(f.name));
      if (!valid) {
        setErrorMsg('Formato no compatible: solo se admiten archivos .STL y .3MF.');
        return;
      }

      setActiveTab('wizard');
      handleSelectStlRef.current(valid);
    };

    window.addEventListener('dragenter', onDragEnter);
    window.addEventListener('dragover', onDragOver);
    window.addEventListener('dragleave', onDragLeave);
    window.addEventListener('drop', onDrop);
    return () => {
      window.removeEventListener('dragenter', onDragEnter);
      window.removeEventListener('dragover', onDragOver);
      window.removeEventListener('dragleave', onDragLeave);
      window.removeEventListener('drop', onDrop);
    };
  }, []);

  useEffect(() => {
    const consumePendingMacFile = async () => {
      const api = (
        window as unknown as {
          pywebview?: {
            api?: {
              has_pending_open_file?: () => Promise<boolean>;
              get_pending_open_file?: () => Promise<{ name: string; path: string } | null>;
            };
          };
        }
      ).pywebview?.api;
      if (!api?.get_pending_open_file) return;
      try {
        if (api.has_pending_open_file) {
          const hasFile = await api.has_pending_open_file();
          if (hasFile) {
            suppressRestorePromptRef.current = true;
            setPendingRestoreSession(null);
          }
        }
        const pending = await api.get_pending_open_file();
        if (!pending?.path || !pending?.name) return;
        suppressRestorePromptRef.current = true;
        setPendingRestoreSession(null);
        setIsLoadingExternalFile(pending.name);
        const resp = await fetch(
          `/api/desktop/open-file?path=${encodeURIComponent(pending.path)}`,
        );
        if (!resp.ok) {
          throw new Error(`No se pudo abrir ${pending.name}`);
        }
        const blob = await resp.blob();
        const file = new File([blob], pending.name);
        setActiveTab('wizard');
        handleSelectStlRef.current(file);
      } catch {
        // Ignorar si pywebview aún no está listo
      } finally {
        setIsLoadingExternalFile(null);
      }
    };

    const onOpenEvent = () => {
      void consumePendingMacFile();
    };
    window.addEventListener('nikk-open-pending-file', onOpenEvent);
    window.addEventListener('pywebviewready', onOpenEvent);
    void consumePendingMacFile();
    return () => {
      window.removeEventListener('nikk-open-pending-file', onOpenEvent);
      window.removeEventListener('pywebviewready', onOpenEvent);
    };
  }, []);

  const [isExportingSelection, setIsExportingSelection] = useState(false);
  const [projectLoadState, setProjectLoadState] = useState<{
    active: boolean;
    progress: number;
    subtitle: string;
  }>({ active: false, progress: 0, subtitle: '' });

  const handleExportSelection = async (opts: {
    format: 'stl' | '3mf' | 'obj';
    applyTransforms: boolean;
    centerOnBed: boolean;
    exportAllPlate: boolean;
  }) => {
    if (!meshId) return;
    setIsExportingSelection(true);
    setErrorMsg(null);
    try {
      const selSet = new Set(selectedObjectIds);
      const targetSceneObjs =
        sceneObjects.length > 0
          ? opts.exportAllPlate
            ? sceneObjects
            : sceneObjects.filter((o) => selSet.has(o.object_id))
          : [];
      const effSceneObjs =
        targetSceneObjs.length > 0 ? targetSceneObjs : sceneObjects;
      const baseName =
        !opts.exportAllPlate && effSceneObjs.length === 1
          ? effSceneObjs[0].name
          : (stlFile?.name || 'modelo').replace(/\.(stl|3mf|obj)$/i, '');
      const effInstances =
        effSceneObjs.length === 0
          ? (transform.instances && transform.instances.length > 0
              ? transform.instances
              : [
                  {
                    instance_id: 'inst_1',
                    offset_x: transform.offsetX ?? 0,
                    offset_y: transform.offsetY ?? 0,
                    offset_z: transform.offsetZ ?? 0,
                    scale_percent: transform.scalePercent ?? 100,
                    scale_x: transform.scaleX ?? null,
                    scale_y: transform.scaleY ?? null,
                    scale_z: transform.scaleZ ?? null,
                    rot_x: transform.rotX ?? 0,
                    rot_y: transform.rotY ?? 0,
                    rot_z: transform.rotZ ?? 0,
                    drop_to_bed: transform.dropToBed ?? true,
                  },
                ])
          : [];
      const exportPayload = {
        mesh_id: meshId,
        printer_id: selectedPrinterId,
        format: opts.format,
        apply_transforms: opts.applyTransforms,
        center_on_bed: opts.centerOnBed,
        export_all_plate: opts.exportAllPlate,
        scene_objects: effSceneObjs,
        instances: effInstances,
        part_extruder_map: partExtruderMap,
        filename_base: baseName,
      };
      const cleanSuggestedBase = (baseName || 'modelo').replace(/\.(stl|3mf|obj)$/i, '') || 'modelo';
      const suggestedFilename = `${cleanSuggestedBase}.${opts.format}`;
      const pySavePost = (
        window as unknown as {
          pywebview?: {
            api?: {
              save_post_file?: (
                url: string,
                payloadJson: string,
                suggestedName: string,
                fileTypes?: string[],
              ) => Promise<{ saved?: boolean; cancelled?: boolean; path?: string; error?: string }>;
            };
          };
        }
      ).pywebview?.api?.save_post_file;

      if (pySavePost) {
        const fileTypes =
          opts.format === 'stl'
            ? ['STL Binary (*.stl)', 'All files (*.*)']
            : opts.format === 'obj'
              ? ['Wavefront OBJ (*.obj)', 'All files (*.*)']
              : ['3MF Project (*.3mf)', 'All files (*.*)'];
        const saveRes = await pySavePost(
          `${API_BASE_URL}/export-selection`,
          JSON.stringify(exportPayload),
          suggestedFilename,
          fileTypes,
        );
        if (saveRes?.error) {
          throw new Error(saveRes.error);
        }
        if (saveRes?.saved && saveRes.path) {
          setAutoOrientMsg(`Exportado en: ${saveRes.path}`);
        }
        return;
      }

      const { blob, filename } = await exportSelection(exportPayload);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      setAutoOrientMsg(`Exportado: ${filename}`);
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error al exportar la selección.',
      );
    } finally {
      setIsExportingSelection(false);
    }
  };

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-950 text-slate-100">
      <GlobalProcessingOverlay
        active={projectLoadState.active}
        mode="project_load"
        printerName={activeProjectTitle || stlFile?.name || 'Nikk Slicer'}
        controlledProgress={projectLoadState.progress}
        controlledSubtitle={projectLoadState.subtitle}
      />
      {isLoadingExternalFile && (
        <div className="fixed inset-0 z-[9995] flex flex-col items-center justify-center bg-slate-950/90 backdrop-blur-md">
          <div className="h-12 w-12 animate-spin rounded-full border-4 border-cyan-400/25 border-t-cyan-400" />
          <p className="mt-4 text-sm font-semibold text-white">
            Abriendo {isLoadingExternalFile}...
          </p>
          <p className="mt-1 text-xs text-slate-400">
            Cargando modelo 3D en Nikk Slicer
          </p>
        </div>
      )}
      {isDraggingFile && (
        <div className="pointer-events-none fixed inset-4 z-[9990] flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-cyan-400 bg-slate-950/75 backdrop-blur-sm">
          <Box className="mb-3 h-12 w-12 text-cyan-400" />
          <p className="text-base font-bold text-white">
            Suelta tu modelo .STL o .3MF para abrirlo en Nikk Slicer
          </p>
          <p className="mt-1 text-xs text-cyan-200/80">
            Se cargará automáticamente en el Laminador
          </p>
        </div>
      )}
      {/* Cabecera con acento de color por ventana, pestañas de proyectos abiertos y navegación */}
      <header
        style={{
          borderTop: `2px solid ${windowAccent.hex}`,
          backgroundImage: `linear-gradient(90deg, ${windowAccent.hex}1a 0%, rgba(15, 23, 42, 0.72) 45%, rgba(15, 23, 42, 0.72) 100%)`,
        }}
        className="z-20 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 bg-slate-900/70 px-6 py-2.5 backdrop-blur"
      >
        <div className="flex flex-wrap items-center gap-3">
          <img
            src="/nikk-logo.jpg"
            alt="Nikk Slider Logo"
            style={{ boxShadow: `0 0 0 1px ${windowAccent.hex}80` }}
            className="h-10 w-10 rounded-xl object-cover shadow-md"
          />
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-base font-bold tracking-tight text-slate-100">
                Nikk Slider
              </h1>
              <span
                style={{
                  borderColor: `${windowAccent.hex}66`,
                  backgroundColor: `${windowAccent.hex}1f`,
                  color: windowAccent.hex,
                }}
                className="rounded-full border px-2 py-0.5 text-[10px] font-semibold"
              >
                {activeProjectTitle || windowAccent.name}
              </span>
              {(stlFile || meshId || activeProjectId) && (
                <button
                  type="button"
                  onClick={() =>
                    window.dispatchEvent(new CustomEvent('nikk:menu-close-project'))
                  }
                  title={t.header.closeProjectTitle}
                  className="flex items-center gap-1 rounded-full border border-rose-500/40 bg-rose-500/10 px-2 py-0.5 text-[10px] font-semibold text-rose-200 transition hover:border-rose-400 hover:bg-rose-500/20"
                >
                  <X className="h-3 w-3" />
                  <span>{t.header.closeProject}</span>
                </button>
              )}
            </div>
            <p className="text-[11px] text-slate-400">
              Laminador Unificado · Granja FDM de {printers.length || 6} Impresoras
            </p>
          </div>

          {/* Conmutador rápido de ventanas/proyectos abiertos */}
          <div className="flex flex-wrap items-center gap-1 rounded-xl border border-slate-800 bg-slate-950/80 p-1">
            {Object.values(openWindows).map((winInfo) => {
              const isCurrent = winInfo.windowId === windowSessionId;
              return (
                <button
                  key={winInfo.windowId}
                  type="button"
                  onClick={() => {
                    if (isCurrent) return;
                    const pyApi = (
                      window as unknown as {
                        pywebview?: {
                          api?: { focus_window_by_id?: (id: string) => void };
                        };
                      }
                    ).pywebview?.api;
                    pyApi?.focus_window_by_id?.(winInfo.windowId);
                    if (typeof BroadcastChannel !== 'undefined') {
                      const ch = new BroadcastChannel('nikk_slicer_windows');
                      ch.postMessage({ type: 'focus', targetWindowId: winInfo.windowId });
                      ch.close();
                    }
                  }}
                  title={isCurrent ? 'Ventana actual' : `Cambiar a: ${winInfo.title}`}
                  className={`flex max-w-[160px] items-center gap-1.5 rounded-lg px-2 py-1 text-[11px] font-medium transition ${
                    isCurrent
                      ? 'bg-slate-800 text-white shadow-sm'
                      : 'text-slate-400 hover:bg-slate-900 hover:text-slate-200'
                  }`}
                >
                  <span
                    className="h-2 w-2 shrink-0 rounded-full"
                    style={{ backgroundColor: winInfo.color }}
                  />
                  <span className="truncate">{winInfo.title}</span>
                </button>
              );
            })}
            <button
              type="button"
              onClick={() => {
                const pyApi = (
                  window as unknown as {
                    pywebview?: { api?: { open_new_window?: (pid?: string | null) => void } };
                  }
                ).pywebview?.api;
                if (pyApi?.open_new_window) {
                  pyApi.open_new_window(null);
                } else {
                  const wsid = Math.random().toString(36).slice(2, 10);
                  window.open(`/?window_session_id=${wsid}`, '_blank');
                }
              }}
              title="Nueva ventana independiente (Cmd+N)"
              className="flex h-6 w-6 items-center justify-center rounded-lg border border-slate-700/70 bg-slate-900 text-slate-300 hover:border-cyan-500/60 hover:text-cyan-200"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <nav className="flex items-center gap-1 rounded-xl border border-slate-800 bg-slate-950/90 p-1">
          <button
            type="button"
            onClick={() => setActiveTab('wizard')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${activeTab === 'wizard'
              ? 'bg-cyan-500/20 text-cyan-200'
              : 'text-slate-400 hover:text-slate-200'
              }`}
          >
            <Sliders className="h-3.5 w-3.5" />
            {t.header.wizard}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('monitor')}
            className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition ${activeTab === 'monitor'
              ? 'bg-emerald-500/20 text-emerald-200'
              : 'text-slate-400 hover:text-slate-200'
              }`}
          >
            <Activity className="h-3.5 w-3.5" />
            {t.header.liveMonitor} ({printers.length || 6} {t.header.machines})
          </button>
        </nav>

        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1 rounded-xl border border-slate-800 bg-slate-950 p-1">
            <button
              type="button"
              onClick={() => undoSession()}
              disabled={!canUndo}
              title={`Deshacer (Ctrl+Z / Cmd+Z)${undoCount > 0 ? ` · ${undoCount}` : ''}`}
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-200 transition hover:bg-slate-800 hover:text-cyan-300 disabled:cursor-not-allowed disabled:opacity-35"
            >
              <Undo2 className="h-3.5 w-3.5" />
              {undoCount > 0 && <span className="font-mono text-[10px] text-cyan-300">{undoCount}</span>}
            </button>
            <button
              type="button"
              onClick={() => redoSession()}
              disabled={!canRedo}
              title={`Rehacer (Ctrl+R / Cmd+Y)${redoCount > 0 ? ` · ${redoCount}` : ''}`}
              className="flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-slate-200 transition hover:bg-slate-800 hover:text-emerald-300 disabled:cursor-not-allowed disabled:opacity-35"
            >
              <Redo2 className="h-3.5 w-3.5" />
              {redoCount > 0 && <span className="font-mono text-[10px] text-emerald-300">{redoCount}</span>}
            </button>
          </div>
          <div className="hidden items-center gap-2 rounded-full border border-slate-800 bg-slate-950 px-3 py-1 text-xs text-slate-300 sm:flex">
            <Cpu className="h-3.5 w-3.5 text-emerald-400" />
            <span className="font-mono text-emerald-400">127.0.0.1:8000</span>
          </div>
          <button
            type="button"
            onClick={() => setQuoteCalculatorOpen(true)}
            title={t.header.quoteTitle}
            className="flex items-center gap-1.5 rounded-xl border border-amber-500/40 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-200 hover:border-amber-400"
          >
            <Calculator className="h-3.5 w-3.5 text-amber-400" />
            {t.header.quote}
          </button>
          <button
            type="button"
            onClick={() => setJournalOpen(true)}
            title={t.header.journalTitle}
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-amber-500/60"
          >
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
            {t.header.journal}
          </button>
          <button
            type="button"
            onClick={() => setSystemSetupOpen(true)}
            title={t.header.envMcpTitle}
            className="flex items-center gap-1.5 rounded-xl border border-emerald-500/40 bg-emerald-500/10 px-3 py-1.5 text-xs font-medium text-emerald-200 hover:border-emerald-400"
          >
            <Server className="h-3.5 w-3.5 text-emerald-400" />
            {t.header.envMcp}
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            title={t.header.settingsTitle}
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-cyan-500/60"
          >
            <Settings className="h-3.5 w-3.5 text-cyan-400" />
            {t.header.settings}
          </button>
          <button
            type="button"
            onClick={toggleLang}
            title={t.header.languageTitle}
            className="flex items-center gap-1 rounded-xl border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-cyan-500/60 hover:text-cyan-200"
          >
            <Globe className="h-3.5 w-3.5 text-cyan-400" />
            <span>{lang === 'es' ? 'ES | EN' : 'EN | ES'}</span>
          </button>
        </div>
      </header>

      {/* Contenido principal según pestaña activa */}
      {activeTab === 'wizard' ? (
        <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden p-4 lg:grid-cols-[420px_1fr] lg:grid-rows-[minmax(0,1fr)]">
          <SlicerWizard
            printers={printers}
            volumetricLimits={volumetricLimits}
            highSpeedVolumetricLimits={highSpeedVolumetricLimits}
            selectedPrinterId={selectedPrinterId}
            onSelectPrinter={handleSelectPrinter}
            onOpenAddPrinter={() => setAddPrinterOpen(true)}
            onDeletePrinter={(id) => {
              void deleteUserPrinter(id).then(() => refreshCatalog());
            }}
            stlFile={stlFile}
            onSelectStl={handleSelectStl}
            analysis={analysis}
            isAnalyzing={isAnalyzing}
            material={material}
            onChangeMaterial={handleChangeMaterial}
            nozzleDiameter={nozzleDiameter}
            onChangeNozzleDiameter={handleChangeNozzleDiameter}
            highSpeedFilament={highSpeedFilament}
            onToggleHighSpeedFilament={setHighSpeedFilament}
            lithophaneMode={lithophaneMode}
            onToggleLithophaneMode={handleToggleLithophaneMode}
            spoolMinTemp={spoolMinTemp}
            onChangeSpoolMinTemp={setSpoolMinTemp}
            spoolMaxTemp={spoolMaxTemp}
            onChangeSpoolMaxTemp={setSpoolMaxTemp}
            nozzleTempInitial={nozzleTempInitial}
            onChangeNozzleTempInitial={setNozzleTempInitial}
            nozzleTemp={nozzleTemp}
            onChangeNozzleTemp={setNozzleTemp}
            bedTemp={bedTemp}
            onChangeBedTemp={setBedTemp}
            supports={supports}
            onToggleSupports={setSupports}
            supportType={supportType}
            onChangeSupportType={setSupportType}
            supportStyle={supportStyle}
            onChangeSupportStyle={setSupportStyle}
            supportOnBuildPlateOnly={supportOnBuildPlateOnly}
            onChangeSupportOnBuildPlateOnly={setSupportOnBuildPlateOnly}
            supportZDistance={supportZDistance}
            onChangeSupportZDistance={setSupportZDistance}
            supportXyDistance={supportXyDistance}
            onChangeSupportXyDistance={setSupportXyDistance}
            adhesionType={adhesionType}
            onChangeAdhesionType={setAdhesionType}
            brimWidthMm={brimWidthMm}
            onChangeBrimWidthMm={setBrimWidthMm}
            adhesionLabel={adhesionLabel}
            primeTowerEnabled={primeTowerEnabled}
            onTogglePrimeTower={(en) => {
              setPrimeTowerEnabled(en);
              setPrimeTowerReason(
                en
                  ? 'Activada (≥45 mm) + Anclaje Reforzado + Purga en Relleno (manual)'
                  : 'Torre de Purga: Desactivada (Ahorro 4 cabezales · manual)',
              );
            }}
            primeTowerReason={primeTowerReason}
            primeTowerBrimWidthMm={primeTowerBrimOverride}
            onChangePrimeTowerBrimWidthMm={setPrimeTowerBrimOverride}
            qualityPreset={qualityPreset}
            onChangePreset={setQualityPreset}
            specializedProfileId={specializedProfileId}
            onSelectDynamicProfile={handleSelectDynamicProfile}
            isOptimizingAI={isOptimizingAI}
            aiReasoning={aiReasoning}
            aiProvider={aiProvider}
            onAISupportOrient={handleAISupportOrient}
            isOptimizingSupportAI={isOptimizingSupportAI}
            aiSupportStatus={aiSupportStatus}
            onAnalyzeModelAI={() => {
              void handleAnalyzeModelAI();
            }}
            isAnalyzingAI={isAnalyzingAI}
            aiAnalysisResult={aiAnalysisResult}
            aiQualityOverrides={aiQualityOverrides}
            onToggleAiQualityOverride={(ovId: string) => {
              setAiQualityOverrides((prev) =>
                prev.includes(ovId) ? prev.filter((x) => x !== ovId) : [...prev, ovId],
              );
            }}
            onClearAiQualityOverrides={() => setAiQualityOverrides([])}
            onOptimizeSliceWithAI={handleOptimizeSliceWithAI}
            isOptimizingSliceAI={isOptimizingSliceAI}
            aiOptimizeComparison={aiOptimizeComparison}
            canRollbackInitialSlice={Boolean(initialSliceSnapshot)}
            onRollbackToInitialSlice={handleRollbackToInitialSlice}
            onRollbackToUnsliced={handleRollbackToUnsliced}
            savedProjects={savedProjects}
            isLoadingProjects={isLoadingProjects}
            onRefreshSavedProjects={refreshSavedProjects}
            onLoadSavedProject={handleLoadSavedProject}
            onApplyDefectCorrection={handleApplyDefectCorrection}
            onSlice={() => void handleSlice()}
            onCancelSlice={handleCancelSlice}
            isSlicing={isSlicing}
            sliceResult={sliceResult}
            slicedProfileSnapshot={sliceResult?.sliced_profile_snapshot ?? slicedProfileSnapshot}
            infillDensityOverride={infillDensityOverride}
            onChangeInfillDensityOverride={setInfillDensityOverride}
            profileDrawerOpen={profileDrawerOpen}
            onSetProfileDrawerOpen={setProfileDrawerOpen}
            onApplyProfileAndReslice={(ov) => handleSlice(ov)}
            errorMsg={errorMsg}
            detectedVolumes={printersConfig?.detected_volumes ?? []}
            configuredSdVolume={configuredSdVolume}
            enableTimelapse={enableTimelapse}
            onToggleEnableTimelapse={setEnableTimelapse}
            autoLeveling={autoLeveling}
            onToggleAutoLeveling={setAutoLeveling}
            onSendToPrinter={handleSendToPrinter}
            uploadActionMode={uploadActionMode}
            sendPrintMsg={sendPrintMsg}
            extrudersConfig={extrudersConfig}
            onChangeExtrudersConfig={setExtrudersConfig}
            modelExtruder={modelExtruder}
            onChangeModelExtruder={setModelExtruder}
            supportExtruder={supportExtruder}
            onChangeSupportExtruder={setSupportExtruder}
            zColorRanges={zColorRanges}
            onChangeZColorRanges={setZColorRanges}
            partExtruderMap={partExtruderMap}
            onChangePartExtruderMap={setPartExtruderMap}
            chamberTempTarget={chamberTempTarget}
            onChangeChamberTempTarget={setChamberTempTarget}
            layerPauses={layerPauses}
            onAddLayerPause={handleAddLayerPause}
            onRemoveLayerPause={handleRemoveLayerPause}
            recentProjects={recentProjects}
            onLoadFullProject={handleLoadFullProject}
            onOpenProjectNewWindow={handleOpenProjectNewWindow}
            onDeleteFullProject={handleDeleteFullProject}
            externalProjectsOpen={externalProjectsOpen}
            onChangeExternalProjectsOpen={setExternalProjectsOpen}
            sceneObjects={sceneObjects}
            selectedObjectIds={selectedObjectIds}
            onSelectObjects={setSelectedObjectIds}
            onChangeSceneObjects={setSceneObjects}
            instances={transform.instances}
            onChangeInstances={(next) =>
              handleChangeTransform({ ...transform, instances: next })
            }
          />

          <Viewport3D
            printer={activePrinter}
            stlFile={stlFile}
            meshId={meshId}
            fitsInVolume={analysis ? analysis.fits_in_volume : true}
            recommendedScalePercent={analysis?.recommended_scale_percent ?? 100}
            transform={transform}
            onChangeTransform={handleChangeTransform}
            onAutoOrient={handleAutoOrient}
            isAutoOrienting={isAutoOrienting}
            autoOrientMessage={autoOrientMsg}
            orientationsData={orientationsData}
            selectedOrientationId={selectedOrientationId}
            onSelectOrientation={handleSelectOrientation}
            onCloseOrientations={() => setOrientationsData(null)}
            onAutoArrange={handleAutoArrange}
            isAutoArranging={isAutoArranging}
            hasSlicedProfile={Boolean(sliceResult?.sliced_profile_snapshot ?? slicedProfileSnapshot)}
            onOpenProfileInspector={() => setProfileDrawerOpen(true)}
            supportBlockers={supportBlockers}
            onChangeSupportBlockers={setSupportBlockers}
            onFetchLayOnFaces={handleFetchLayOnFaces}
            onCutMesh={handleCutMesh}
            isCuttingMesh={isCuttingMesh}
            layerPauses={layerPauses}
            onAddLayerPause={handleAddLayerPause}
            onRemoveLayerPause={handleRemoveLayerPause}
            sceneObjects={sceneObjects}
            selectedObjectIds={selectedObjectIds}
            onSelectObjects={setSelectedObjectIds}
            onChangeSceneObjects={setSceneObjects}
            onSplitObjects={handleSplitObjects}
            onMergeObjects={handleMergeObjects}
            isSplittingObjects={isSplittingObjects}
            extruderColors={
              activeProfileId === 'creator5_pro'
                ? [0, 1, 2, 3].map((zoneIdx) => {
                    const mappedSlot = partExtruderMap[`zone_${zoneIdx}`] ?? zoneIdx;
                    return (
                      extrudersConfig[mappedSlot]?.color_hex ??
                      extrudersConfig[zoneIdx]?.color_hex ??
                      '#ffffff'
                    );
                  })
                : undefined
            }
            multimaterialParts={analysis?.multimaterial_parts}
            partExtruderMap={partExtruderMap}
            gcodeText={gcodeText}
            isAnalyzing={isAnalyzing}
            onExportSelection={handleExportSelection}
            isExporting={isExportingSelection}
            onOpenProjects={() => setExternalProjectsOpen(true)}
          />
        </main>
      ) : (
        <main className="min-h-0 flex-1 overflow-hidden">
          <FarmDashboard />
        </main>
      )}

      <footer className="z-10 flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-slate-800/70 bg-slate-900/75 px-6 py-1.5 text-[11px] text-slate-400">
        <span className="font-medium text-slate-300">
          Nikk Slider · Control y Laminado FDM
        </span>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span>
            Creador:{' '}
            <strong className="font-semibold text-cyan-300">
              Niklauss Mauricio Quintero
            </strong>
          </span>
          <a
            href="mailto:niklaussmauricio@gmal.com"
            className="text-slate-300 underline-offset-2 hover:text-cyan-300 hover:underline"
          >
            niklaussmauricio@gmal.com
          </a>
          <a
            href="https://wa.me/573187244914"
            target="_blank"
            rel="noreferrer"
            className="font-mono text-emerald-300 underline-offset-2 hover:underline"
          >
            WhatsApp: 3187244914
          </a>
        </div>
      </footer>

      <PrinterSettingsModal
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        machineProfiles={machineProfiles}
        onOpenAddCatalog={() => setAddPrinterOpen(true)}
        onSaved={(cfg) => {
          setPrintersConfig(cfg);
          void refreshCatalog();
        }}
      />

      <AddPrinterModal
        open={addPrinterOpen}
        onClose={() => setAddPrinterOpen(false)}
        onAdded={(newPrinterId) => {
          void refreshCatalog().then(() => {
            handleSelectPrinter(newPrinterId);
          });
        }}
      />

      <ErrorJournalModal
        open={journalOpen}
        onClose={() => setJournalOpen(false)}
      />

      <SystemSetupModal
        open={systemSetupOpen}
        onClose={() => setSystemSetupOpen(false)}
      />

      <QuoteCalculatorModal
        open={quoteCalculatorOpen}
        onClose={() => setQuoteCalculatorOpen(false)}
        initialData={{
          modelName: stlFile?.name,
          printerProfileId: activeProfileId,
          printerName: activePrinter?.display_name || selectedPrinterId,
          material,
          ...(sliceResult
            ? (() => {
                const hMatch = /(\d+)\s*h/i.exec(sliceResult.estimated_time || '');
                const mMatch = /(\d+)\s*m/i.exec(sliceResult.estimated_time || '');
                return {
                  hours: hMatch ? Number(hMatch[1]) : 0,
                  minutes: mMatch ? Number(mMatch[1]) : 0,
                  grams: sliceResult.filament_grams,
                };
              })()
            : {}),
        }}
      />

      {pendingRestoreSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md space-y-3 rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-slate-100">
                {t.startup.title}
              </h2>
              <p className="text-xs text-slate-400">
                {t.startup.subtitle}
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="truncate font-semibold text-cyan-200" title={pendingRestoreSession.file_name}>
                {pendingRestoreSession.file_name}
              </p>
              <p className="mt-0.5 font-mono text-[10px] text-slate-400">
                {t.startup.printerLabel} {pendingRestoreSession.printer_id || selectedPrinterId}
                {pendingRestoreSession.saved_at
                  ? ` · ${new Date(pendingRestoreSession.saved_at).toLocaleString()}`
                  : ''}
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2 pt-1">
              <button
                type="button"
                disabled={isRestoringSession}
                onClick={() => {
                  setPendingRestoreSession(null);
                  void clearLastSession().catch(() => {});
                  setExternalProjectsOpen(true);
                }}
                className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-cyan-200 hover:border-cyan-500/60 hover:bg-slate-800 disabled:opacity-40"
              >
                <FolderOpen className="h-3.5 w-3.5 text-cyan-400" />
                {t.startup.openProject}
              </button>
              <button
                type="button"
                disabled={isRestoringSession}
                onClick={() => {
                  setPendingRestoreSession(null);
                  void clearLastSession().catch(() => {});
                }}
                className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-40"
              >
                {t.startup.newProject}
              </button>
              <button
                type="button"
                disabled={isRestoringSession}
                onClick={async () => {
                  const sess = pendingRestoreSession;
                  setIsRestoringSession(true);
                  setProjectLoadState({
                    active: true,
                    progress: 20,
                    subtitle: t.projectLoading.step1,
                  });
                  try {
                    const targetPrinter = sess.printer_id || selectedPrinterId;
                    if (sess.printer_id) {
                      setSelectedPrinterId(sess.printer_id);
                    }
                    const nextTx = sess.transform ?? DEFAULT_TRANSFORM;
                    setTransform(nextTx);
                    if (sess.part_extruder_map) setPartExtruderMap(sess.part_extruder_map);
                    if (sess.z_color_ranges) setZColorRanges(sess.z_color_ranges);
                    if (typeof sess.supports === 'boolean') setSupports(sess.supports);
                    if (sess.support_type) setSupportType(sess.support_type);
                    if (typeof sess.support_on_build_plate_only === 'boolean') {
                      setSupportOnBuildPlateOnly(sess.support_on_build_plate_only);
                    }
                    if (typeof sess.support_z_distance === 'number') {
                      setSupportZDistance(sess.support_z_distance);
                    }
                    if (typeof sess.support_xy_distance === 'number') {
                      setSupportXyDistance(sess.support_xy_distance);
                    }
                    if (sess.adhesion_type) setAdhesionType(sess.adhesion_type);
                    if (typeof sess.brim_width_mm === 'number') {
                      setBrimWidthMm(sess.brim_width_mm);
                    }

                    setProjectLoadState({
                      active: true,
                      progress: 55,
                      subtitle: t.projectLoading.step2,
                    });
                    const restoredFile = await fetchCachedMeshFile(sess.mesh_id, sess.file_name);
                    setStlFile(restoredFile);
                    setMeshId(sess.mesh_id);
                    setSliceResult(null);
                    setGcodeText(null);
                    setPendingRestoreSession(null);
                    await runAnalysis(targetPrinter, nextTx, {
                      cachedMeshId: sess.mesh_id,
                      preserveUserSettings: true,
                    });
                    setProjectLoadState({
                      active: true,
                      progress: 85,
                      subtitle: t.projectLoading.step3,
                    });
                    if (sess.part_extruder_map) setPartExtruderMap(sess.part_extruder_map);
                    if (Array.isArray(sess.support_blockers)) setSupportBlockers(sess.support_blockers);
                    if (Array.isArray(sess.scene_objects) && sess.scene_objects.length > 0) {
                      setSceneObjects(sess.scene_objects);
                      if (Array.isArray(sess.selected_object_ids)) {
                        setSelectedObjectIds(sess.selected_object_ids);
                      }
                    }
                    setProjectLoadState({
                      active: true,
                      progress: 100,
                      subtitle: t.projectLoading.step4,
                    });
                  } catch (err: unknown) {
                    setPendingRestoreSession(null);
                    setErrorMsg(
                      err instanceof Error
                        ? `No se pudo restaurar el último modelo: ${err.message}`
                        : 'No se pudo restaurar el último modelo.',
                    );
                  } finally {
                    setIsRestoringSession(false);
                    setProjectLoadState((prev) => ({ ...prev, active: false }));
                  }
                }}
                className="rounded-xl bg-cyan-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50"
              >
                {isRestoringSession ? '...' : t.startup.openLastProject}
              </button>
            </div>
          </div>
        </div>
      )}
      {projectToast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-xl border border-emerald-500/45 bg-slate-900/95 px-3.5 py-2 text-xs font-semibold text-emerald-200 shadow-2xl backdrop-blur">
          {projectToast}
        </div>
      )}
    </div>
  );
}

export default App;
