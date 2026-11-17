import { useCallback, useEffect, useState } from 'react';
import {
  Archive,
  Camera,
  CameraOff,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  Download,
  Fan,
  FileText,
  Film,
  Flame,
  FolderOpen,
  Gauge,
  History,
  Layers,
  Lightbulb,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Sparkles,
  Square,
  Thermometer,
  Trash2,
  Wifi,
  WifiOff,
} from 'lucide-react';
import {
  controlPrinter,
  deleteStoredFile,
  fetchPrinterFiles,
  fetchPrinterTelemetrySession,
  fetchPrinterTimelapses,
  fetchPrintersStatus,
  generatePrinterCompendium,
  printStoredFile,
  requestAITelemetryDiagnosis,
  togglePrinterLight,
  type AITelemetryDiagnosisResponse,
  type PostPrintCompendium,
  type PrinterId,
  type PrinterLiveStatus,
  type PrinterStoredFile,
  type PrinterTelemetrySessionResponse,
  type PrinterTimelapseFile,
} from '../services/api';

function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || seconds < 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function stateBadge(state: string, online: boolean): { label: string; cls: string } {
  const st = state.toLowerCase();
  if (!online && st !== 'sd_ready') {
    return { label: 'Offline', cls: 'border-slate-700 bg-slate-800/80 text-slate-400' };
  }
  if (st === 'printing') {
    return { label: 'Imprimiendo', cls: 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300' };
  }
  if (st === 'paused') {
    return { label: 'En Pausa', cls: 'border-amber-500/50 bg-amber-500/15 text-amber-300' };
  }
  if (st === 'sd_ready') {
    return { label: 'SD Lista', cls: 'border-cyan-500/50 bg-cyan-500/15 text-cyan-300' };
  }
  if (st === 'lan_mode_required' || st === 'access_code_mismatch') {
    return {
      label: st === 'access_code_mismatch' ? 'Access Code' : 'Modo LAN',
      cls: 'border-amber-500/50 bg-amber-500/15 text-amber-300',
    };
  }
  if (st === 'error') {
    return { label: 'Error', cls: 'border-rose-500/50 bg-rose-500/15 text-rose-300' };
  }
  return { label: 'En Línea', cls: 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200' };
}

function CameraStreamBox({ url, name }: { url: string; name: string }) {
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
  }, [url]);

  if (!url || failed) {
    return (
      <div className="flex h-36 flex-col items-center justify-center rounded-xl border border-slate-800 bg-slate-950/80 text-center">
        <CameraOff className="mb-1.5 h-5 w-5 text-slate-600" />
        <p className="text-[11px] font-medium text-slate-500">
          {url ? 'Cámara MJPEG sin señal' : 'Sin URL de cámara configurada'}
        </p>
      </div>
    );
  }

  return (
    <div className="relative h-36 overflow-hidden rounded-xl border border-slate-800 bg-slate-950">
      <img
        src={url}
        alt={`Cámara ${name}`}
        onError={() => setFailed(true)}
        className="h-full w-full object-cover"
      />
      <span className="absolute left-2 top-2 flex items-center gap-1 rounded-md bg-slate-950/80 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300 backdrop-blur">
        <Camera className="h-3 w-3" />
        EN VIVO
      </span>
    </div>
  );
}

export function FarmDashboard() {
  const [statuses, setStatuses] = useState<PrinterLiveStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [globalError, setGlobalError] = useState<string | null>(null);

  // Estado aislado ESTRICTAMENTE por instancia `printer_id`
  const [actionLoadingById, setActionLoadingById] = useState<Record<string, string | null>>({});
  const [feedbackById, setFeedbackById] = useState<Record<string, string | null>>({});

  // Archivos en memoria por máquina
  const [filesOpenById, setFilesOpenById] = useState<Record<string, boolean>>({});
  const [filesById, setFilesById] = useState<Record<string, PrinterStoredFile[]>>({});
  const [confirmDeleteById, setConfirmDeleteById] = useState<Record<string, string | null>>({});
  const [confirmPrintById, setConfirmPrintById] = useState<Record<string, string | null>>({});
  const [enableTimelapseForFile, setEnableTimelapseForFile] = useState<boolean>(() => {
    try {
      return window.localStorage.getItem('nikk_slider_file_timelapse_v1') === 'true';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(
        'nikk_slider_file_timelapse_v1',
        String(enableTimelapseForFile),
      );
    } catch {
      // Ignorar errores de almacenamiento local
    }
  }, [enableTimelapseForFile]);

  // Timelapses por máquina
  const [timelapseOpenById, setTimelapseOpenById] = useState<Record<string, boolean>>({});
  const [timelapsesById, setTimelapsesById] = useState<
    Record<string, { videos: PrinterTimelapseFile[]; message: string }>
  >({});
  const [activeVideoById, setActiveVideoById] = useState<Record<string, string | null>>({});

  // Diagnóstico IA en vivo + Grabación continua + Compendios post-impresión
  const [aiDiagById, setAiDiagById] = useState<
    Record<string, AITelemetryDiagnosisResponse | null>
  >({});
  const [telemetrySessionById, setTelemetrySessionById] = useState<
    Record<string, PrinterTelemetrySessionResponse | null>
  >({});
  const [partialCompendiumById, setPartialCompendiumById] = useState<
    Record<string, PostPrintCompendium | null>
  >({});
  const [historyOpenById, setHistoryOpenById] = useState<Record<string, boolean>>({});
  const [archivedCompendiumIds, setArchivedCompendiumIds] = useState<string[]>(() => {
    try {
      const raw = window.localStorage.getItem('slicerhub_archived_compendiums_v1');
      const parsed = raw ? (JSON.parse(raw) as unknown) : [];
      return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string') : [];
    } catch {
      return [];
    }
  });

  const archiveCompendium = (compId: string) => {
    setArchivedCompendiumIds((prev) => {
      if (prev.includes(compId)) return prev;
      const next = [compId, ...prev].slice(0, 100);
      try {
        window.localStorage.setItem('slicerhub_archived_compendiums_v1', JSON.stringify(next));
      } catch {
        // Ignorar errores de cuota
      }
      return next;
    });
  };

  const setPrinterActionBusy = (printerId: PrinterId, action: string | null) => {
    setActionLoadingById((prev) => ({ ...prev, [printerId]: action }));
  };

  const setPrinterFeedback = (printerId: PrinterId, msg: string | null) => {
    setFeedbackById((prev) => ({ ...prev, [printerId]: msg }));
  };

  const loadStatus = useCallback(async () => {
    try {
      const list = await fetchPrintersStatus();
      setStatuses(list);
      setGlobalError(null);

      // Refrescar sesión de grabación continua y último compendio para máquinas habilitadas
      const onlineIds = list.filter((s) => s.online).map((s) => s.printer_id);
      if (onlineIds.length > 0) {
        const sessEntries = await Promise.all(
          onlineIds.map(async (pid) => {
            try {
              const sess = await fetchPrinterTelemetrySession(pid);
              return [pid, sess] as const;
            } catch {
              return [pid, null] as const;
            }
          }),
        );
        setTelemetrySessionById((prev) => {
          const next = { ...prev };
          for (const [pid, sess] of sessEntries) {
            if (sess) next[pid] = sess;
          }
          return next;
        });
      }
    } catch (err: unknown) {
      setGlobalError(err instanceof Error ? err.message : 'Error consultando la granja.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadStatus();
    const timer = window.setInterval(() => {
      void loadStatus();
    }, 3000);
    return () => window.clearInterval(timer);
  }, [loadStatus]);

  const handleControl = async (
    printerId: PrinterId,
    action: 'pause' | 'resume' | 'cancel',
  ) => {
    setPrinterActionBusy(printerId, action);
    setPrinterFeedback(printerId, null);
    try {
      const res = await controlPrinter(printerId, action);
      setPrinterFeedback(printerId, res.message);
      await loadStatus();
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : `Error ejecutando ${action}.`,
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  const handleToggleLight = async (printerId: PrinterId, currentOn?: boolean) => {
    setPrinterActionBusy(printerId, 'light');
    setPrinterFeedback(printerId, null);
    try {
      const target = currentOn === undefined ? undefined : !currentOn;
      const res = await togglePrinterLight(printerId, target);
      setPrinterFeedback(printerId, res.message);
      setStatuses((prev) =>
        prev.map((item) =>
          item.printer_id === printerId ? { ...item, light_on: res.light_on } : item,
        ),
      );
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : 'Error conmutando luz LED.',
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  const loadFilesForPrinter = async (printerId: PrinterId) => {
    setPrinterActionBusy(printerId, 'files_list');
    try {
      const res = await fetchPrinterFiles(printerId);
      setFilesById((prev) => ({ ...prev, [printerId]: res.files }));
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : 'Error listando archivos en memoria.',
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  const handleToggleFilesAccordion = async (printerId: PrinterId) => {
    const nextOpen = !filesOpenById[printerId];
    setFilesOpenById((prev) => ({ ...prev, [printerId]: nextOpen }));
    if (nextOpen) {
      await loadFilesForPrinter(printerId);
    }
  };

  const handlePrintStoredFile = async (
    printerId: PrinterId,
    filename: string,
    autoLeveling = false,
  ) => {
    setPrinterActionBusy(printerId, `print:${filename}`);
    setPrinterFeedback(printerId, null);
    setConfirmPrintById((prev) => ({ ...prev, [printerId]: null }));
    try {
      const res = await printStoredFile(
        printerId,
        filename,
        enableTimelapseForFile,
        autoLeveling,
      );
      setPrinterFeedback(printerId, res.message);
      await loadStatus();
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : `Error iniciando '${filename}'.`,
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  const handleDeleteStoredFile = async (printerId: PrinterId, filename: string) => {
    setPrinterActionBusy(printerId, `delete:${filename}`);
    setPrinterFeedback(printerId, null);
    try {
      const res = await deleteStoredFile(printerId, filename);
      setConfirmDeleteById((prev) => ({ ...prev, [printerId]: null }));
      setPrinterFeedback(printerId, res.message);
      await loadFilesForPrinter(printerId);
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : `Error eliminando '${filename}'.`,
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  const loadTimelapsesForPrinter = async (printerId: PrinterId) => {
    setPrinterActionBusy(printerId, 'timelapses');
    try {
      const res = await fetchPrinterTimelapses(printerId);
      setTimelapsesById((prev) => ({
        ...prev,
        [printerId]: { videos: res.timelapses, message: res.message },
      }));
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : 'Error consultando timelapses.',
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  const handleToggleTimelapsesAccordion = async (printerId: PrinterId) => {
    const nextOpen = !timelapseOpenById[printerId];
    setTimelapseOpenById((prev) => ({ ...prev, [printerId]: nextOpen }));
    if (nextOpen) {
      await loadTimelapsesForPrinter(printerId);
    }
  };

  const handleAIDiagnosis = async (printerId: PrinterId) => {
    setPrinterActionBusy(printerId, 'ai_telemetry');
    setPrinterFeedback(printerId, null);
    try {
      const res = await requestAITelemetryDiagnosis(printerId);
      setAiDiagById((prev) => ({ ...prev, [printerId]: res }));
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : 'Error analizando telemetría con IA.',
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  const handleGenerateCompendium = async (printerId: PrinterId) => {
    setPrinterActionBusy(printerId, 'ai_compendium');
    setPrinterFeedback(printerId, null);
    try {
      const comp = await generatePrinterCompendium(printerId);
      setPartialCompendiumById((prev) => ({ ...prev, [printerId]: comp }));
      const refreshed = await fetchPrinterTelemetrySession(printerId);
      setTelemetrySessionById((prev) => ({ ...prev, [printerId]: refreshed }));
    } catch (err: unknown) {
      setPrinterFeedback(
        printerId,
        err instanceof Error ? err.message : 'Error generando compendio acumulado.',
      );
    } finally {
      setPrinterActionBusy(printerId, null);
    }
  };

  return (
    <div className="flex h-full flex-col gap-4 overflow-y-auto p-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-800 bg-slate-900/75 px-4 py-3">
        <div>
          <h2 className="text-sm font-bold text-slate-100">
            Monitor en Vivo · Granja de {statuses.length || 6} Impresoras
          </h2>
          <p className="text-[11px] text-slate-400">
            Control aislado por máquina · Archivos remotos, Luz LED, Timelapse y Telemetría IA (refresco cada 3 s)
          </p>
        </div>

        <div className="flex items-center gap-3">
          {globalError && (
            <span className="rounded-lg border border-rose-500/40 bg-rose-500/15 px-2.5 py-1 text-xs text-rose-200">
              {globalError}
            </span>
          )}
          <button
            type="button"
            onClick={() => void loadStatus()}
            className="flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-950 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-cyan-500/60"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            Actualizar
          </button>
        </div>
      </div>

      {loading && statuses.length === 0 ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-5 w-5 animate-spin text-cyan-400" />
          Consultando las máquinas de la granja...
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {statuses.map((st) => {
            const pid = st.printer_id;
            const badge = stateBadge(st.state, st.online);
            const busyAction = actionLoadingById[pid] ?? null;
            const cardBusy = busyAction !== null;
            const cardFeedback = feedbackById[pid];
            const lowerState = st.state.toLowerCase();
            const isPaused = st.online && lowerState === 'paused';
            const isActivePrint =
              st.online && ['printing', 'heating', 'busy'].includes(lowerState);
            const isWorking = isActivePrint || isPaused;
            const isNetworkPrinter = st.protocol !== 'marlin_serial';
            const filesOpen = Boolean(filesOpenById[pid]);
            const filesList = filesById[pid] ?? [];
            const confirmDeleteName = confirmDeleteById[pid] ?? null;
            const confirmPrintName = confirmPrintById[pid] ?? null;
            const timelapseOpen = Boolean(timelapseOpenById[pid]);
            const timelapseInfo = timelapsesById[pid];
            const activeVideoUrl = activeVideoById[pid] ?? null;
            const aiDiag = aiDiagById[pid] ?? null;

            const protoLabel =
              st.protocol === 'moonraker'
                ? 'Moonraker API'
                : st.protocol === 'flashforge_lan'
                  ? 'FlashForge LAN'
                  : 'Marlin USB / SD';

            return (
              <article
                key={pid}
                className="flex flex-col justify-between gap-3 rounded-2xl border border-slate-800 bg-slate-900/75 p-4 shadow-lg"
              >
                <div className="space-y-2.5">
                  {/* Cabecera tarjeta */}
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <div className="flex items-center gap-2">
                        <Cpu className="h-4 w-4 text-cyan-400" />
                        <h3 className="text-sm font-bold text-slate-100">
                          {st.display_name}
                        </h3>
                      </div>
                      <p className="mt-0.5 pl-6 text-[11px] text-slate-400">
                        {protoLabel}
                        {st.ip ? ` · ${st.ip}${st.port ? `:${st.port}` : ''}` : ''}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {isNetworkPrinter && (
                        <button
                          type="button"
                          disabled={!st.online || cardBusy}
                          onClick={() => void handleToggleLight(pid, st.light_on)}
                          title={st.light_on ? 'Apagar Luz LED' : 'Encender Luz LED'}
                          className={`flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition disabled:opacity-40 ${
                            st.light_on
                              ? 'border-amber-400/60 bg-amber-400/20 text-amber-200'
                              : 'border-slate-700 bg-slate-800/80 text-slate-300 hover:border-amber-500/40'
                          }`}
                        >
                          {busyAction === 'light' ? (
                            <Loader2 className="h-3 w-3 animate-spin" />
                          ) : (
                            <Lightbulb
                              className={`h-3 w-3 ${st.light_on ? 'fill-amber-300 text-amber-300' : ''}`}
                            />
                          )}
                          {st.light_on ? 'Luz ON' : 'Luz OFF'}
                        </button>
                      )}
                      <span
                        className={`flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold ${badge.cls}`}
                      >
                        {st.online ? (
                          <Wifi className="h-3 w-3" />
                        ) : (
                          <WifiOff className="h-3 w-3" />
                        )}
                        {badge.label}
                      </span>
                    </div>
                  </div>

                  {/* Cámara MJPEG */}
                  <CameraStreamBox url={st.camera_url} name={st.display_name} />

                  {/* Temperaturas principales */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-2.5">
                      <div className="flex items-center justify-between text-[11px] text-slate-400">
                        <span className="flex items-center gap-1">
                          <Flame className="h-3.5 w-3.5 text-orange-400" />
                          Boquilla
                        </span>
                        <span className="font-mono font-semibold text-orange-300">
                          {st.nozzle_temp !== null ? `${st.nozzle_temp}°` : '—'} /{' '}
                          {st.nozzle_target !== null ? `${st.nozzle_target}°` : '—'}
                        </span>
                      </div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full bg-orange-500 transition-all"
                          style={{
                            width: `${Math.min(100, ((st.nozzle_temp ?? 0) / Math.max(st.nozzle_target || 220, 1)) * 100)}%`,
                          }}
                        />
                      </div>
                    </div>

                    <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-2.5">
                      <div className="flex items-center justify-between text-[11px] text-slate-400">
                        <span className="flex items-center gap-1">
                          <Thermometer className="h-3.5 w-3.5 text-cyan-400" />
                          Cama
                        </span>
                        <span className="font-mono font-semibold text-cyan-300">
                          {st.bed_temp !== null ? `${st.bed_temp}°` : '—'} /{' '}
                          {st.bed_target !== null ? `${st.bed_target}°` : '—'}
                        </span>
                      </div>
                      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full bg-cyan-500 transition-all"
                          style={{
                            width: `${Math.min(100, ((st.bed_temp ?? 0) / Math.max(st.bed_target || 60, 1)) * 100)}%`,
                          }}
                        />
                      </div>
                    </div>
                  </div>

                  {/* Progreso de impresión */}
                  <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-2.5">
                    <div className="mb-1 flex items-center justify-between text-[11px]">
                      <span className="truncate font-medium text-slate-300">
                        {st.current_file || st.message}
                      </span>
                      <span className="ml-2 shrink-0 font-mono font-bold text-emerald-300">
                        {st.progress_percent.toFixed(1)}%
                        {st.eta_seconds !== null
                          ? ` · ETA ${formatDuration(st.eta_seconds)}`
                          : ''}
                      </span>
                    </div>
                    <div className="h-2 overflow-hidden rounded-full bg-slate-800">
                      <div
                        className="h-full bg-gradient-to-r from-cyan-500 to-emerald-400 transition-all"
                        style={{ width: `${Math.min(100, st.progress_percent)}%` }}
                      />
                    </div>
                  </div>

                  {/* Telemetría avanzada en vivo */}
                  {st.online && (
                    <div className="grid grid-cols-3 gap-1.5 rounded-xl border border-slate-800/80 bg-slate-950/75 p-2 text-[10px]">
                      <div className="flex flex-col">
                        <span className="flex items-center gap-1 text-slate-400">
                          <Layers className="h-3 w-3 text-cyan-400" />
                          Capa
                        </span>
                        <span className="font-mono font-semibold text-slate-200">
                          {st.total_layers
                            ? `${st.current_layer ?? 0} / ${st.total_layers}`
                            : st.current_layer !== null && st.current_layer !== undefined
                              ? `${st.current_layer}`
                              : '—'}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="flex items-center gap-1 text-slate-400">
                          <Gauge className="h-3 w-3 text-emerald-400" />
                          Vel / Flujo
                        </span>
                        <span className="font-mono font-semibold text-slate-200">
                          {st.print_speed_mms ?? 0} mm/s · {Math.round(st.flow_factor_percent ?? 100)}%
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="flex items-center gap-1 text-slate-400">
                          <Fan className="h-3 w-3 text-sky-400" />
                          Fan / Factor
                        </span>
                        <span className="font-mono font-semibold text-slate-200">
                          {Math.round(st.fan_speed_percent ?? 0)}% · {Math.round(st.speed_factor_percent ?? 100)}%
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="flex items-center gap-1 text-slate-400">
                          <Clock className="h-3 w-3 text-amber-400" />
                          Transcurrido
                        </span>
                        <span className="font-mono font-semibold text-slate-200">
                          {formatDuration(st.elapsed_seconds)}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-slate-400">MCU / Placa</span>
                        <span className="font-mono font-semibold text-slate-200">
                          {st.chamber_temp !== null && st.chamber_temp !== undefined
                            ? `Cám ${st.chamber_temp}°`
                            : st.mcu_temp !== null && st.mcu_temp !== undefined
                              ? `${st.mcu_temp}° / ${st.host_temp ?? '—'}°`
                              : '—'}
                        </span>
                      </div>
                      <div className="flex flex-col">
                        <span className="text-slate-400">Filamento</span>
                        <span className="font-mono font-semibold text-slate-200">
                          {(st.filament_used_g ?? 0).toFixed(1)}g /{' '}
                          {((st.filament_used_mm ?? 0) / 1000).toFixed(2)}m
                        </span>
                      </div>
                    </div>
                  )}

                  {/* Grabación continua + Diagnóstico IA + Compendio Post-Impresión */}
                  {st.online && (() => {
                    const tSession = telemetrySessionById[pid] ?? null;
                    const activeSess = tSession?.active_session ?? null;
                    const recMinutes = activeSess
                      ? Math.max(1, Math.round(activeSess.duration_recorded_seconds / 60))
                      : 0;
                    const activeComp = isWorking
                      ? partialCompendiumById[pid] ?? activeSess?.compendium ?? null
                      : null;
                    const finalComp = tSession?.last_compendium ?? null;
                    const displayComp =
                      activeComp ??
                      (finalComp && !archivedCompendiumIds.includes(finalComp.compendium_id)
                        ? finalComp
                        : null);
                    const historyList = tSession?.history ?? [];
                    const historyOpen = Boolean(historyOpenById[pid]);

                    return (
                      <div className="space-y-1.5">
                        {isWorking && (
                          <>
                            <div className="flex items-center justify-between gap-2 rounded-lg border border-emerald-500/30 bg-emerald-950/25 px-2.5 py-1 text-[10px]">
                              <span className="flex items-center gap-1.5 font-semibold text-emerald-300">
                                <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
                                Grabando telemetría completa
                              </span>
                              <span className="font-mono text-emerald-200">
                                {activeSess ? `${activeSess.samples_count} muestras · ${recMinutes} min` : 'Iniciando...'}
                              </span>
                            </div>

                            <div className="grid grid-cols-2 gap-1.5">
                              <button
                                type="button"
                                disabled={cardBusy}
                                onClick={() => void handleAIDiagnosis(pid)}
                                title="Diagnóstico rápido del instante actual con DeepSeek IA"
                                className="flex items-center justify-center gap-1 rounded-xl border border-purple-500/40 bg-purple-500/15 py-1.5 text-[10px] font-semibold text-purple-200 transition hover:bg-purple-500/25 disabled:cursor-not-allowed disabled:opacity-40"
                              >
                                {busyAction === 'ai_telemetry' ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <Sparkles className="h-3 w-3 text-purple-300" />
                                )}
                                Analizar Instante Actual
                              </button>
                              <button
                                type="button"
                                disabled={cardBusy || !activeSess}
                                onClick={() => void handleGenerateCompendium(pid)}
                                title="Generar compendio acumulado de toda la sesión hasta ahora"
                                className="flex items-center justify-center gap-1 rounded-xl border border-cyan-500/40 bg-cyan-500/15 py-1.5 text-[10px] font-semibold text-cyan-200 transition hover:bg-cyan-500/25 disabled:cursor-not-allowed disabled:opacity-40"
                              >
                                {busyAction === 'ai_compendium' ? (
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                ) : (
                                  <FileText className="h-3 w-3 text-cyan-300" />
                                )}
                                Ver Compendio Acumulado
                              </button>
                            </div>
                          </>
                        )}

                        {aiDiag && isWorking && (
                          <div className="space-y-1 rounded-xl border border-purple-500/35 bg-purple-950/30 p-2 text-[10px]">
                            <div className="flex items-center justify-between gap-1">
                              <span
                                className={`rounded-full px-2 py-0.5 font-bold ${
                                  aiDiag.status_badge === 'OPTIMO'
                                    ? 'bg-emerald-500/20 text-emerald-300'
                                    : aiDiag.status_badge === 'ATENCION'
                                      ? 'bg-amber-500/20 text-amber-300'
                                      : 'bg-rose-500/20 text-rose-300'
                                }`}
                              >
                                {aiDiag.status_badge}
                              </span>
                              <span className="font-mono text-[9px] text-purple-300">
                                {aiDiag.provider}
                              </span>
                            </div>
                            <p className="font-medium text-slate-200">{aiDiag.summary}</p>
                            <ul className="list-disc space-y-0.5 pl-4 text-slate-300">
                              {aiDiag.recommendations.map((rec, rIdx) => (
                                <li key={rIdx}>{rec}</li>
                              ))}
                            </ul>
                          </div>
                        )}

                        {/* Tarjeta Persistente de Compendio Final / Acumulado */}
                        {displayComp && (
                          <div className="space-y-1.5 rounded-xl border border-cyan-500/35 bg-slate-950/85 p-2.5 text-[10px]">
                            <div className="flex items-center justify-between gap-1.5">
                              <span className="font-bold text-cyan-200">
                                {displayComp.is_partial
                                  ? 'Compendio IA Acumulado (En Curso)'
                                  : 'Compendio Final IA de la Última Impresión'}
                              </span>
                              <div className="flex items-center gap-1">
                                <span
                                  className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${
                                    displayComp.rating === 'EXCELENTE'
                                      ? 'bg-emerald-500/20 text-emerald-300'
                                      : displayComp.rating === 'BUENA_CON_MEJORAS'
                                        ? 'bg-amber-500/20 text-amber-300'
                                        : 'bg-rose-500/20 text-rose-300'
                                  }`}
                                >
                                  {displayComp.rating}
                                </span>
                                <span className="font-mono text-[9px] text-purple-300">
                                  {displayComp.provider}
                                </span>
                              </div>
                            </div>

                            <div className="flex flex-wrap items-center justify-between gap-1 text-[9px] text-slate-400">
                              <span className="truncate font-mono text-slate-200">
                                {displayComp.filename} ({displayComp.detected_material})
                              </span>
                              <span className="font-mono">
                                {displayComp.stats.samples_count} muestras ·{' '}
                                {formatDuration(
                                  displayComp.stats.real_elapsed_seconds ??
                                    displayComp.stats.duration_recorded_seconds,
                                )}
                              </span>
                            </div>

                            <div className="grid grid-cols-4 gap-1 rounded-lg border border-slate-800 bg-slate-900/70 p-1.5 font-mono text-[9px]">
                              <div>
                                <div className="text-slate-500">Boquilla</div>
                                <div className="text-orange-300">
                                  {displayComp.stats.overall.nozzle_min ?? '—'}/
                                  {displayComp.stats.overall.nozzle_avg ?? '—'}/
                                  {displayComp.stats.overall.nozzle_max ?? '—'}°
                                </div>
                              </div>
                              <div>
                                <div className="text-slate-500">Cama</div>
                                <div className="text-amber-300">
                                  {displayComp.stats.overall.bed_min ?? '—'}/
                                  {displayComp.stats.overall.bed_avg ?? '—'}/
                                  {displayComp.stats.overall.bed_max ?? '—'}°
                                </div>
                              </div>
                              <div>
                                <div className="text-slate-500">MCU</div>
                                <div className="text-cyan-300">
                                  {displayComp.stats.overall.mcu_avg ?? '—'}° (máx{' '}
                                  {displayComp.stats.overall.mcu_max ?? '—'}°)
                                </div>
                              </div>
                              <div>
                                <div className="text-slate-500">Vel. prom</div>
                                <div className="text-emerald-300">
                                  {displayComp.stats.overall.speed_avg ?? '—'} mm/s
                                </div>
                              </div>
                            </div>

                            <p className="leading-snug text-slate-200">
                              {displayComp.executive_summary}
                            </p>

                            <ul className="list-disc space-y-0.5 pl-4 text-slate-300">
                              {displayComp.improvements.map((imp, idx) => (
                                <li key={idx}>{imp}</li>
                              ))}
                            </ul>

                            <div className="flex items-center justify-between gap-2 pt-0.5">
                              {historyList.length > 0 ? (
                                <button
                                  type="button"
                                  onClick={() =>
                                    setHistoryOpenById((prev) => ({
                                      ...prev,
                                      [pid]: !prev[pid],
                                    }))
                                  }
                                  className="inline-flex items-center gap-1 text-[9px] font-semibold text-cyan-300 hover:text-cyan-200"
                                >
                                  <History className="h-3 w-3" />
                                  Historial ({historyList.length})
                                </button>
                              ) : (
                                <span />
                              )}
                              {!displayComp.is_partial && (
                                <button
                                  type="button"
                                  onClick={() => archiveCompendium(displayComp.compendium_id)}
                                  className="inline-flex items-center gap-1 rounded border border-slate-700 bg-slate-900 px-2 py-0.5 text-[9px] text-slate-300 hover:bg-slate-800"
                                >
                                  <Archive className="h-2.5 w-2.5" />
                                  Archivar
                                </button>
                              )}
                            </div>
                          </div>
                        )}

                        {!displayComp && historyList.length > 0 && !isWorking && (
                          <button
                            type="button"
                            onClick={() =>
                              setHistoryOpenById((prev) => ({
                                ...prev,
                                [pid]: !prev[pid],
                              }))
                            }
                            className="flex w-full items-center justify-center gap-1 rounded-lg border border-slate-800 bg-slate-950/60 py-1 text-[10px] text-cyan-300 hover:bg-slate-900"
                          >
                            <History className="h-3 w-3" />
                            Consultar historial de compendios ({historyList.length})
                          </button>
                        )}

                        {historyOpen && historyList.length > 0 && (
                          <div className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950/80 p-1.5 text-[9px]">
                            {historyList.map((hc) => (
                              <div
                                key={hc.compendium_id}
                                className="rounded border border-slate-800/80 bg-slate-900/70 p-1.5"
                              >
                                <div className="flex items-center justify-between gap-1 font-semibold text-slate-200">
                                  <span className="truncate">{hc.filename}</span>
                                  <span className="font-mono text-cyan-300">{hc.rating}</span>
                                </div>
                                <p className="mt-0.5 text-slate-400">{hc.executive_summary}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    );
                  })()}

                  {/* Acordeón Archivos en Memoria */}
                  {isNetworkPrinter && (
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60">
                      <button
                        type="button"
                        disabled={!st.online}
                        onClick={() => void handleToggleFilesAccordion(pid)}
                        className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold text-slate-200 disabled:opacity-40"
                      >
                        <span className="flex items-center gap-1.5">
                          <FolderOpen className="h-3.5 w-3.5 text-cyan-400" />
                          Archivos en Memoria ({filesList.length})
                        </span>
                        {filesOpen ? (
                          <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                        )}
                      </button>

                      {filesOpen && (
                        <div className="space-y-1.5 border-t border-slate-800 px-2.5 py-2">
                          <div className="flex items-center justify-between text-[10px] text-slate-400">
                            <span>Almacenamiento de {st.display_name}</span>
                            <button
                              type="button"
                              disabled={cardBusy}
                              onClick={() => void loadFilesForPrinter(pid)}
                              className="flex items-center gap-1 text-cyan-300 hover:underline disabled:opacity-40"
                            >
                              <RefreshCw
                                className={`h-3 w-3 ${busyAction === 'files_list' ? 'animate-spin' : ''}`}
                              />
                              Recargar
                            </button>
                          </div>

                          {filesList.length === 0 ? (
                            <p className="py-1 text-center text-[10px] text-slate-500">
                              {busyAction === 'files_list'
                                ? 'Consultando memoria...'
                                : 'Sin archivos en memoria.'}
                            </p>
                          ) : (
                            <div className="max-h-40 space-y-1 overflow-y-auto pr-0.5">
                              {filesList.map((f) => {
                                const isConfirmingDelete = confirmDeleteName === f.filename;
                                const isConfirmingPrint = confirmPrintName === f.filename;
                                return (
                                  <div
                                    key={f.filename}
                                    className="space-y-1 rounded-lg border border-slate-800 bg-slate-900/90 px-2 py-1 text-[10px]"
                                  >
                                    <div className="flex items-center justify-between gap-1.5">
                                      <div className="min-w-0 flex-1">
                                        <p
                                          className="truncate font-medium text-slate-200"
                                          title={f.filename}
                                        >
                                          {f.filename}
                                        </p>
                                        <p className="font-mono text-[9px] text-slate-400">
                                          {f.size_mb > 0 ? `${f.size_mb.toFixed(1)} MB` : '3MF/GCode'}
                                          {f.estimated_time_sec
                                            ? ` · ${formatDuration(f.estimated_time_sec)}`
                                            : ''}
                                          {f.filament_grams ? ` · ${f.filament_grams}g` : ''}
                                        </p>
                                      </div>
                                      <div className="flex shrink-0 items-center gap-1">
                                        <button
                                          type="button"
                                          disabled={cardBusy}
                                          onClick={() =>
                                            setConfirmPrintById((prev) => ({
                                              ...prev,
                                              [pid]: isConfirmingPrint ? null : f.filename,
                                            }))
                                          }
                                          className="rounded border border-emerald-500/40 bg-emerald-500/15 px-1.5 py-0.5 font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-40"
                                          title="Imprimir este archivo"
                                        >
                                          {busyAction === `print:${f.filename}` ? (
                                            <Loader2 className="h-3 w-3 animate-spin" />
                                          ) : (
                                            'Imprimir'
                                          )}
                                        </button>
                                        {isConfirmingDelete ? (
                                          <>
                                            <button
                                              type="button"
                                              disabled={cardBusy}
                                              onClick={() =>
                                                void handleDeleteStoredFile(pid, f.filename)
                                              }
                                              className="rounded border border-rose-500 bg-rose-500/30 px-1.5 py-0.5 font-bold text-rose-100 hover:bg-rose-500/45 disabled:opacity-40"
                                            >
                                              Confirmar
                                            </button>
                                            <button
                                              type="button"
                                              onClick={() =>
                                                setConfirmDeleteById((prev) => ({
                                                  ...prev,
                                                  [pid]: null,
                                                }))
                                              }
                                              className="rounded border border-slate-700 bg-slate-800 px-1 py-0.5 text-slate-300"
                                            >
                                              No
                                            </button>
                                          </>
                                        ) : (
                                          <button
                                            type="button"
                                            disabled={cardBusy}
                                            onClick={() =>
                                              setConfirmDeleteById((prev) => ({
                                                ...prev,
                                                [pid]: f.filename,
                                              }))
                                            }
                                            className="rounded border border-rose-500/30 bg-rose-500/10 p-1 text-rose-300 hover:bg-rose-500/25 disabled:opacity-40"
                                            title="Eliminar archivo de memoria"
                                          >
                                            <Trash2 className="h-3 w-3" />
                                          </button>
                                        )}
                                      </div>
                                    </div>
                                    {isConfirmingPrint && (
                                      <div className="space-y-1.5 rounded-lg border border-amber-500/40 bg-slate-950/90 p-1.5 text-[9px]">
                                        <p className="font-semibold text-amber-200">
                                          ¿Ejecutar nivelación/calibración antes de imprimir?
                                        </p>
                                        <label className="flex cursor-pointer items-center justify-between rounded border border-slate-800 bg-slate-900/90 px-2 py-1 text-[9px] text-slate-200">
                                          <span className="flex items-center gap-1 font-medium">
                                            <Film className="h-3 w-3 text-purple-400" />
                                            Grabar Timelapse
                                          </span>
                                          <input
                                            type="checkbox"
                                            checked={enableTimelapseForFile}
                                            onChange={(e) =>
                                              setEnableTimelapseForFile(e.target.checked)
                                            }
                                            className="h-3 w-3 accent-purple-500"
                                          />
                                        </label>
                                        <div className="grid grid-cols-2 gap-1">
                                          <button
                                            type="button"
                                            disabled={cardBusy}
                                            onClick={() =>
                                              void handlePrintStoredFile(pid, f.filename, false)
                                            }
                                            className="rounded border border-cyan-500/50 bg-cyan-500/20 px-1.5 py-1 font-semibold text-cyan-100 hover:bg-cyan-500/30"
                                          >
                                            Imprimir directo (Sin calibrar)
                                          </button>
                                          <button
                                            type="button"
                                            disabled={cardBusy}
                                            onClick={() =>
                                              void handlePrintStoredFile(pid, f.filename, true)
                                            }
                                            className="rounded border border-emerald-500/50 bg-emerald-500/20 px-1.5 py-1 font-semibold text-emerald-100 hover:bg-emerald-500/30"
                                          >
                                            Calibrar e Imprimir
                                          </button>
                                        </div>
                                      </div>
                                    )}
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Acordeón Timelapses (.mp4) */}
                  {isNetworkPrinter && (
                    <div className="rounded-xl border border-slate-800 bg-slate-950/60">
                      <button
                        type="button"
                        disabled={!st.online}
                        onClick={() => void handleToggleTimelapsesAccordion(pid)}
                        className="flex w-full items-center justify-between px-3 py-2 text-[11px] font-semibold text-slate-200 disabled:opacity-40"
                      >
                        <span className="flex items-center gap-1.5">
                          <Film className="h-3.5 w-3.5 text-purple-400" />
                          Timelapses (.mp4)
                          {timelapseInfo ? ` (${timelapseInfo.videos.length})` : ''}
                        </span>
                        {timelapseOpen ? (
                          <ChevronUp className="h-3.5 w-3.5 text-slate-400" />
                        ) : (
                          <ChevronDown className="h-3.5 w-3.5 text-slate-400" />
                        )}
                      </button>

                      {timelapseOpen && (
                        <div className="space-y-1.5 border-t border-slate-800 px-2.5 py-2 text-[10px]">
                          {timelapseInfo?.message && (
                            <p className="text-slate-400">{timelapseInfo.message}</p>
                          )}
                          {timelapseInfo?.videos.map((v) => (
                            <div
                              key={v.filename}
                              className="space-y-1 rounded-lg border border-slate-800 bg-slate-900/90 p-1.5"
                            >
                              <div className="flex items-center justify-between gap-1.5">
                                <span className="truncate font-medium text-slate-200">
                                  {v.filename} ({v.size_mb.toFixed(1)} MB)
                                </span>
                                <div className="flex shrink-0 items-center gap-1">
                                  <button
                                    type="button"
                                    onClick={() =>
                                      setActiveVideoById((prev) => ({
                                        ...prev,
                                        [pid]:
                                          prev[pid] === v.download_url ? null : v.download_url,
                                      }))
                                    }
                                    className="rounded border border-purple-500/40 bg-purple-500/15 px-1.5 py-0.5 text-purple-200 hover:bg-purple-500/25"
                                  >
                                    {activeVideoUrl === v.download_url ? 'Ocultar' : 'Ver'}
                                  </button>
                                  <a
                                    href={v.download_url}
                                    download={v.filename}
                                    target="_blank"
                                    rel="noreferrer"
                                    className="rounded border border-cyan-500/40 bg-cyan-500/15 p-1 text-cyan-200 hover:bg-cyan-500/25"
                                    title="Descargar video MP4"
                                  >
                                    <Download className="h-3 w-3" />
                                  </a>
                                </div>
                              </div>
                              {activeVideoUrl === v.download_url && (
                                <video
                                  src={v.download_url}
                                  controls
                                  className="w-full rounded-lg border border-slate-800 bg-black"
                                />
                              )}
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}

                  {/* Feedback exclusivo de esta tarjeta */}
                  {cardFeedback && (
                    <p className="rounded-lg border border-cyan-500/35 bg-cyan-500/10 px-2.5 py-1 text-[10px] text-cyan-200">
                      {cardFeedback}
                    </p>
                  )}
                </div>

                {/* Botones de control aislados y condicionados al estado activo */}
                <div className="grid grid-cols-3 gap-2 pt-1">
                  <button
                    type="button"
                    disabled={!isActivePrint || cardBusy}
                    onClick={() => void handleControl(pid, 'pause')}
                    className="flex items-center justify-center gap-1 rounded-xl border border-amber-500/40 bg-amber-500/10 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/20 disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    {busyAction === 'pause' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Pause className="h-3.5 w-3.5" />
                    )}
                    Pausar
                  </button>
                  <button
                    type="button"
                    disabled={!isPaused || cardBusy}
                    onClick={() => void handleControl(pid, 'resume')}
                    className="flex items-center justify-center gap-1 rounded-xl border border-emerald-500/40 bg-emerald-500/10 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    {busyAction === 'resume' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                    Reanudar
                  </button>
                  <button
                    type="button"
                    disabled={!isWorking || cardBusy}
                    onClick={() => void handleControl(pid, 'cancel')}
                    className="flex items-center justify-center gap-1 rounded-xl border border-rose-500/40 bg-rose-500/10 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20 disabled:cursor-not-allowed disabled:opacity-35"
                  >
                    {busyAction === 'cancel' ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Square className="h-3.5 w-3.5" />
                    )}
                    Cancelar
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
    </div>
  );
}
