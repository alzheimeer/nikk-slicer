import { useEffect, useRef, useState } from 'react';
import { Activity, AlertTriangle, Cpu, Settings, Sliders } from 'lucide-react';
import { ErrorJournalModal } from './components/ErrorJournalModal';
import {
  analyzeMesh,
  autoArrangeModels,
  autoOrientMesh,
  clearLastSession,
  cutMeshByPlane,
  fetchAIRecommendation,
  fetchCachedMeshFile,
  fetchCatalog,
  fetchGcodeText,
  fetchLayOnFaceCandidates,
  fetchPrintersConfig,
  fetchUserPrefs,
  requestAISupportOrient,
  saveUserPrefs,
  sliceModel,
  uploadJobToPrinter,
  type AISupportOrientResponse,
  type AdhesionType,
  type ExtruderSlotConfig,
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
  type QualityPreset,
  type SliceResponse,
  type SupportType,
  type ZColorRange,
} from './services/api';
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
import { Viewport3D } from './components/Viewport3D';

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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [journalOpen, setJournalOpen] = useState(false);

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

  const [stlFile, setStlFile] = useState<File | null>(null);
  const [meshId, setMeshId] = useState<string | null>(null);
  const [transform, setTransform] = useState<ModelTransform>(DEFAULT_TRANSFORM);
  const [analysis, setAnalysis] = useState<MeshAnalysisResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [isAutoOrienting, setIsAutoOrienting] = useState(false);
  const [isAutoArranging, setIsAutoArranging] = useState(false);
  const [isCuttingMesh, setIsCuttingMesh] = useState(false);
  const [autoOrientMsg, setAutoOrientMsg] = useState<string | null>(null);

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
  const [enableTimelapse, setEnableTimelapse] = useState<boolean>(false);
  const [autoLeveling, setAutoLeveling] = useState<boolean>(
    Boolean(initialPrefs.autoLeveling),
  );
  const [qualityPreset, setQualityPreset] = useState<QualityPreset>(
    initialPrefs.qualityPreset || 'estandar',
  );

  const [isOptimizingAI, setIsOptimizingAI] = useState(false);
  const [aiReasoning, setAiReasoning] = useState<string | null>(null);
  const [aiProvider, setAiProvider] = useState<string | null>(null);
  const [isOptimizingSupportAI, setIsOptimizingSupportAI] = useState(false);
  const [aiSupportStatus, setAiSupportStatus] =
    useState<AISupportOrientResponse | null>(null);

  const [isSlicing, setIsSlicing] = useState(false);
  const [sliceResult, setSliceResult] = useState<SliceResponse | null>(null);
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
  const [partExtruderMap, setPartExtruderMap] = useState<Record<string, number>>({});
  const [chamberTempTarget, setChamberTempTarget] = useState<number | null>(null);
  const [pendingRestoreSession, setPendingRestoreSession] =
    useState<LastSessionData | null>(null);
  const [isRestoringSession, setIsRestoringSession] = useState(false);

  const analyzeSeqRef = useRef(0);
  const prefsLoadedRef = useRef(false);
  const lastSupportSyncKeyRef = useRef<string>('');

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
        if (typeof p.spoolMinTemp === 'number') setSpoolMinTemp(p.spoolMinTemp);
        if (typeof p.spoolMaxTemp === 'number') setSpoolMaxTemp(p.spoolMaxTemp);
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
    const auto = computeAutoTemperatures(
      activeProfileId,
      material,
      spoolMinTemp,
      spoolMaxTemp,
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
    options: { file?: File; cachedMeshId?: string },
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
      setSupports(res.suggests_supports);
      setAdhesionType(res.suggests_raft ? 'raft' : 'none');

      // Al cargar un archivo .3mf nuevo, inicializar mapeo de partes y zonas de color hacia T0..T3
      // SIN sobrescribir los colores físicos reales configurados en los carretes T0..T3
      if (options.file) {
        const nextMap: Record<string, number> = {};
        if (res.multimaterial_parts && res.multimaterial_parts.length > 0) {
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

  const handleAutoOrient = async () => {
    if (!meshId && !stlFile) return;
    setIsAutoOrienting(true);
    setErrorMsg(null);
    setSliceResult(null);
    setSendPrintMsg(null);
    setGcodeText(null);
    const seq = ++analyzeSeqRef.current;
    try {
      const res = await autoOrientMesh({
        printerId: selectedPrinterId,
        meshId,
        file: meshId ? null : stlFile,
        scalePercent: 100,
      });
      if (seq !== analyzeSeqRef.current) return;
      setMeshId(res.mesh_id);
      setTransform({
        scalePercent: 100,
        rotX: res.rot_x,
        rotY: res.rot_y,
        rotZ: res.rot_z,
      });
      setAnalysis(res.analysis);
      setSupports(res.analysis.suggests_supports);
      setAdhesionType(res.analysis.suggests_raft ? 'raft' : 'none');
      setAutoOrientMsg(res.message);
    } catch (err: unknown) {
      setErrorMsg(
        err instanceof Error ? err.message : 'Error al auto-orientar el STL.',
      );
    } finally {
      setIsAutoOrienting(false);
    }
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
  }): Promise<{ res: SliceResponse; rawGcode: string }> => {
    const minBound = Math.min(spoolMinTemp, spoolMaxTemp - 5);
    const maxBound = Math.max(spoolMaxTemp, minBound + 5);
    const safeInitial = Math.min(maxBound, Math.max(minBound, nozzleTempInitial));
    const safeNormal = Math.min(maxBound, Math.max(minBound, nozzleTemp));

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
    const res = await sliceModel({
      printer_id: selectedPrinterId,
      material: lithophaneMode ? 'pla' : material,
      nozzle_temp: safeNormal,
      nozzle_temp_initial_layer: safeInitial,
      bed_temp: bedTemp,
      nozzle_diameter: nozzleDiameter,
      high_speed_filament: highSpeedFilament,
      lithophane_mode: lithophaneMode,
      supports: effSupports,
      support_type: overrides?.supportTypeOverride ?? supportType,
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
      prime_tower_mode: primeTowerEnabled ? 'ultra_save' : 'off',
      enable_prime_tower: primeTowerEnabled,
      enable_timelapse: enableTimelapse,
      auto_leveling: autoLeveling,
      quality_preset: qualityPreset,
      mesh_id: effMeshId,
      file: effMeshId ? null : stlFile,
      transform: overrides?.transformOverride ?? transform,
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
    return { res, rawGcode };
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

  const handleSlice = async () => {
    if (!stlFile && !meshId) return;
    sliceAbortRef.current?.abort();
    const ctrl = new AbortController();
    sliceAbortRef.current = ctrl;
    setIsSlicing(true);
    setErrorMsg(null);
    setSendPrintMsg(null);

    try {
      const { res, rawGcode } = await runRealSlice();
      setSliceResult(res);
      setGcodeText(rawGcode);
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

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-slate-950 text-slate-100">
      {/* Cabecera con pestañas Wizard / Monitor y botón de configuración */}
      <header className="z-20 flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-slate-800/80 bg-slate-900/70 px-6 py-2.5 backdrop-blur">
        <div className="flex items-center gap-3">
          <img
            src="/nikk-logo.jpg"
            alt="Nikk Slider Logo"
            className="h-10 w-10 rounded-xl object-cover ring-1 ring-cyan-500/45 shadow-md shadow-cyan-500/15"
          />
          <div>
            <h1 className="text-base font-bold tracking-tight text-slate-100">
              Nikk Slider
            </h1>
            <p className="text-[11px] text-slate-400">
              Laminador Unificado · Granja FDM de {printers.length || 6} Impresoras
            </p>
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
            Laminador (Wizard)
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
            Monitor en Vivo ({printers.length || 6} Máquinas)
          </button>
        </nav>

        <div className="flex items-center gap-2">
          <div className="hidden items-center gap-2 rounded-full border border-slate-800 bg-slate-950 px-3 py-1 text-xs text-slate-300 sm:flex">
            <Cpu className="h-3.5 w-3.5 text-emerald-400" />
            <span className="font-mono text-emerald-400">127.0.0.1:8000</span>
          </div>
          <button
            type="button"
            onClick={() => setJournalOpen(true)}
            title="Consultar bitácora de errores y fallos"
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-amber-500/60"
          >
            <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />
            Bitácora
          </button>
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            title="Configurar IPs, puertos USB/SD y API Keys de IA"
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-cyan-500/60"
          >
            <Settings className="h-3.5 w-3.5 text-cyan-400" />
            Hardware e IA
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
                  ? 'Activada Ultra-Ahorro 20mm + Purga en Relleno (manual)'
                  : 'Torre de Purga: Desactivada (Ahorro 4 cabezales · manual)',
              );
            }}
            primeTowerReason={primeTowerReason}
            qualityPreset={qualityPreset}
            onChangePreset={setQualityPreset}
            isOptimizingAI={isOptimizingAI}
            aiReasoning={aiReasoning}
            aiProvider={aiProvider}
            onAISupportOrient={handleAISupportOrient}
            isOptimizingSupportAI={isOptimizingSupportAI}
            aiSupportStatus={aiSupportStatus}
            onSlice={handleSlice}
            onCancelSlice={handleCancelSlice}
            isSlicing={isSlicing}
            sliceResult={sliceResult}
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
            onAutoArrange={handleAutoArrange}
            isAutoArranging={isAutoArranging}
            onFetchLayOnFaces={handleFetchLayOnFaces}
            onCutMesh={handleCutMesh}
            isCuttingMesh={isCuttingMesh}
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
        onSaved={(cfg) => {
          setPrintersConfig(cfg);
          void refreshCatalog();
        }}
      />

      <ErrorJournalModal
        open={journalOpen}
        onClose={() => setJournalOpen(false)}
      />

      {pendingRestoreSession && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md space-y-3 rounded-2xl border border-slate-800 bg-slate-900 p-5 shadow-2xl">
            <div className="space-y-1">
              <h2 className="text-sm font-semibold text-slate-100">
                ¿Continuar con el último proyecto?
              </h2>
              <p className="text-xs text-slate-400">
                Se encontró tu sesión anterior guardada antes de cerrar:
              </p>
            </div>
            <div className="rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-xs">
              <p className="truncate font-semibold text-cyan-200" title={pendingRestoreSession.file_name}>
                {pendingRestoreSession.file_name}
              </p>
              <p className="mt-0.5 font-mono text-[10px] text-slate-400">
                Impresora: {pendingRestoreSession.printer_id || selectedPrinterId}
                {pendingRestoreSession.saved_at
                  ? ` · ${new Date(pendingRestoreSession.saved_at).toLocaleString()}`
                  : ''}
              </p>
            </div>
            <div className="flex items-center justify-end gap-2 pt-1">
              <button
                type="button"
                disabled={isRestoringSession}
                onClick={() => {
                  setPendingRestoreSession(null);
                  void clearLastSession().catch(() => {});
                }}
                className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800 disabled:opacity-40"
              >
                Proyecto nuevo
              </button>
              <button
                type="button"
                disabled={isRestoringSession}
                onClick={async () => {
                  const sess = pendingRestoreSession;
                  setIsRestoringSession(true);
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

                    const restoredFile = await fetchCachedMeshFile(sess.mesh_id, sess.file_name);
                    setStlFile(restoredFile);
                    setMeshId(sess.mesh_id);
                    setSliceResult(null);
                    setGcodeText(null);
                    setPendingRestoreSession(null);
                    await runAnalysis(targetPrinter, nextTx, {
                      cachedMeshId: sess.mesh_id,
                    });
                    if (sess.part_extruder_map) setPartExtruderMap(sess.part_extruder_map);
                  } catch (err: unknown) {
                    setPendingRestoreSession(null);
                    setErrorMsg(
                      err instanceof Error
                        ? `No se pudo restaurar el último modelo: ${err.message}`
                        : 'No se pudo restaurar el último modelo.',
                    );
                  } finally {
                    setIsRestoringSession(false);
                  }
                }}
                className="rounded-xl bg-cyan-500 px-3.5 py-1.5 text-xs font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50"
              >
                {isRestoringSession ? 'Abriendo...' : 'Abrir último proyecto'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
