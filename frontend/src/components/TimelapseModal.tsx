import { useEffect, useState } from 'react';
import {
  Download,
  Film,
  FolderOpen,
  Loader2,
  Play,
  RefreshCw,
  Trash2,
  Video,
  X,
} from 'lucide-react';
import {
  deleteLocalTimelapse,
  fetchLocalTimelapses,
  getLocalTimelapseMediaUrl,
  type LocalTimelapseCompleted,
  type LocalTimelapsesResponse,
} from '../services/api';

interface TimelapseModalProps {
  open: boolean;
  onClose: () => void;
  onActiveCountChange?: (count: number) => void;
}

function formatDuration(seconds?: number): string {
  const s = Math.max(0, Math.round(seconds ?? 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

export function TimelapseModal({
  open,
  onClose,
  onActiveCountChange,
}: TimelapseModalProps) {
  const [data, setData] = useState<LocalTimelapsesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewItem, setPreviewItem] = useState<LocalTimelapseCompleted | null>(
    null,
  );
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const loadTimelapses = async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const res = await fetchLocalTimelapses();
      setData(res);
      onActiveCountChange?.(res.active.length);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : 'Error consultando timelapses.',
      );
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    void loadTimelapses(false);
    const timer = window.setInterval(() => {
      void loadTimelapses(true);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [open]);

  const handleDownload = async (
    item: LocalTimelapseCompleted,
    fmt: 'mp4' | 'avi' | 'webp',
  ) => {
    const url = getLocalTimelapseMediaUrl(item.session_id, fmt);
    const base = (item.filename || item.session_id)
      .replace(/\.(3mf|gcode)$/i, '')
      .replace(/[^A-Za-z0-9_.-]+/g, '_');
    const suggested = `${base}_timelapse.${fmt}`;
    const pySave = (
      window as unknown as {
        pywebview?: {
          api?: {
            save_file?: (u: string, name: string) => Promise<unknown>;
          };
        };
      }
    ).pywebview?.api?.save_file;
    if (pySave) {
      await pySave(url, suggested);
      return;
    }
    const a = document.createElement('a');
    a.href = url;
    a.download = suggested;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  const handleDelete = async (sessionId: string) => {
    setDeletingId(sessionId);
    try {
      await deleteLocalTimelapse(sessionId);
      if (previewItem?.session_id === sessionId) {
        setPreviewItem(null);
      }
      await loadTimelapses(true);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : 'No se pudo eliminar el timelapse.',
      );
    } finally {
      setDeletingId(null);
    }
  };

  if (!open) return null;

  const active = data?.active ?? [];
  const completed = data?.completed ?? [];
  const armed = data?.armed_printers ?? [];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
      <div className="flex max-h-[88vh] w-full max-w-4xl flex-col rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl border border-cyan-500/40 bg-cyan-500/15">
              <Video className="h-4 w-4 text-cyan-400" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white">
                Timelapses Locales
              </h2>
              <p className="text-[11px] text-slate-400">
                {active.length} en proceso · {completed.length} disponibles para ver
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void loadTimelapses(false)}
              disabled={loading}
              className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-xs font-medium text-slate-200 hover:bg-slate-700 disabled:opacity-50"
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`}
              />
              Actualizar
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-700 bg-slate-800 p-1.5 text-slate-300 hover:bg-slate-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {error && (
            <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
              {error}
            </div>
          )}

          {/* Reproductor inline si hay un timelapse seleccionado */}
          {previewItem && (
            <div className="space-y-2.5 rounded-xl border border-cyan-500/40 bg-slate-950 p-3">
              <div className="flex items-center justify-between gap-2">
                <div>
                  <p className="text-xs font-bold text-white">
                    {previewItem.filename || previewItem.session_id}
                  </p>
                  <p className="text-[11px] text-slate-400">
                    {previewItem.printer_name || previewItem.printer_id} ·{' '}
                    {previewItem.frame_count ?? 0} fotogramas ·{' '}
                    {formatDuration(previewItem.duration_seconds)}
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setPreviewItem(null)}
                  className="rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-[11px] text-slate-300 hover:bg-slate-700"
                >
                  Cerrar vista
                </button>
              </div>
              <div className="flex max-h-80 items-center justify-center overflow-hidden rounded-lg bg-black">
                {previewItem.has_mp4 ? (
                  <video
                    src={getLocalTimelapseMediaUrl(previewItem.session_id, 'mp4')}
                    controls
                    autoPlay
                    loop
                    className="max-h-80 w-auto object-contain"
                  />
                ) : (
                  <img
                    src={getLocalTimelapseMediaUrl(previewItem.session_id, 'webp')}
                    alt={previewItem.filename || 'Timelapse'}
                    className="max-h-80 w-auto object-contain"
                  />
                )}
              </div>
            </div>
          )}

          {/* Sección 1: En Proceso */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-amber-300">
                <span
                  className={`h-2 w-2 rounded-full ${
                    active.length > 0
                      ? 'animate-pulse bg-rose-500'
                      : 'bg-slate-600'
                  }`}
                />
                En proceso ({active.length})
              </h3>
              {armed.length > 0 && (
                <span className="text-[10px] text-slate-400">
                  Armadas para grabar al imprimir: {armed.join(', ')}
                </span>
              )}
            </div>

            {active.length === 0 ? (
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-3 text-xs text-slate-400">
                No hay grabaciones activas en este momento. Se inicia automáticamente al comenzar una impresión si{' '}
                <strong className="text-slate-200">Grabar Timelapse</strong> está activado.
              </div>
            ) : (
              <div className="space-y-2">
                {active.map((sess) => (
                  <div
                    key={sess.session_id}
                    className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/35 bg-amber-500/10 px-4 py-3 text-xs"
                  >
                    <div className="min-w-0 space-y-0.5">
                      <div className="flex items-center gap-2">
                        <Loader2 className="h-3.5 w-3.5 animate-spin text-amber-400" />
                        <span className="truncate font-bold text-white">
                          {sess.filename || sess.session_id}
                        </span>
                      </div>
                      <p className="text-[11px] text-amber-200/80">
                        {sess.printer_name || sess.printer_id} · Capa{' '}
                        {sess.last_layer ?? 0} ·{' '}
                        <strong className="text-white">
                          {sess.frame_count ?? 0} fotogramas
                        </strong>{' '}
                        capturados
                      </p>
                    </div>
                    <span className="rounded-lg border border-rose-500/40 bg-rose-500/15 px-2.5 py-1 text-[10px] font-semibold text-rose-200">
                      REC en vivo
                    </span>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Sección 2: Disponibles para ver */}
          <section className="space-y-2">
            <h3 className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-emerald-300">
              <Film className="h-3.5 w-3.5 text-emerald-400" />
              Disponibles para ver ({completed.length})
            </h3>

            {completed.length === 0 ? (
              <div className="rounded-xl border border-slate-800 bg-slate-950/60 px-4 py-6 text-center text-xs text-slate-400">
                Aún no hay timelapses finalizados en esta máquina. Al terminar una impresión aparecerán aquí listos para reproducir y descargar.
              </div>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {completed.map((item) => (
                  <div
                    key={item.session_id}
                    className="flex flex-col justify-between gap-2.5 rounded-xl border border-slate-800 bg-slate-950/80 p-3 text-xs"
                  >
                    <div className="flex gap-3">
                      <button
                        type="button"
                        onClick={() => setPreviewItem(item)}
                        className="group relative h-16 w-24 shrink-0 overflow-hidden rounded-lg border border-slate-700 bg-black"
                        title="Reproducir timelapse"
                      >
                        <img
                          src={getLocalTimelapseMediaUrl(item.session_id, 'thumb')}
                          alt={item.filename || 'Timelapse'}
                          className="h-full w-full object-cover opacity-85 transition group-hover:opacity-100"
                        />
                        <div className="absolute inset-0 flex items-center justify-center bg-black/30">
                          <Play className="h-5 w-5 text-white drop-shadow" />
                        </div>
                      </button>
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <p className="truncate font-bold text-slate-100">
                          {item.filename || item.session_id}
                        </p>
                        <p className="truncate text-[11px] text-cyan-300">
                          {item.printer_name || item.printer_id}
                        </p>
                        <p className="text-[10px] text-slate-400">
                          {item.frame_count ?? 0} frames ·{' '}
                          {formatDuration(item.duration_seconds)} ·{' '}
                          {item.completed_iso
                            ? new Date(item.completed_iso).toLocaleString()
                            : ''}
                        </p>
                      </div>
                    </div>

                    <div className="flex flex-wrap items-center justify-between gap-1.5 border-t border-slate-800/80 pt-2">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <button
                          type="button"
                          onClick={() => setPreviewItem(item)}
                          className="flex items-center gap-1 rounded-lg border border-cyan-500/45 bg-cyan-500/15 px-2.5 py-1 text-[10px] font-semibold text-cyan-100 hover:bg-cyan-500/25"
                        >
                          <Play className="h-3 w-3" />
                          Ver
                        </button>
                        {item.has_mp4 && (
                          <button
                            type="button"
                            onClick={() => void handleDownload(item, 'mp4')}
                            className="flex items-center gap-1 rounded-lg border border-emerald-500/45 bg-emerald-500/15 px-2 py-1 text-[10px] font-semibold text-emerald-100 hover:bg-emerald-500/25"
                          >
                            <Download className="h-3 w-3" />
                            .MP4
                          </button>
                        )}
                        {item.has_avi && (
                          <button
                            type="button"
                            onClick={() => void handleDownload(item, 'avi')}
                            className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] font-semibold text-slate-200 hover:bg-slate-700"
                          >
                            <Download className="h-3 w-3" />
                            .AVI
                          </button>
                        )}
                        {item.has_webp && (
                          <button
                            type="button"
                            onClick={() => void handleDownload(item, 'webp')}
                            className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2 py-1 text-[10px] font-semibold text-slate-200 hover:bg-slate-700"
                          >
                            <Download className="h-3 w-3" />
                            .WEBP
                          </button>
                        )}
                      </div>
                      <button
                        type="button"
                        disabled={deletingId === item.session_id}
                        onClick={() => void handleDelete(item.session_id)}
                        title="Eliminar timelapse"
                        className="rounded-lg border border-slate-700 bg-slate-900 p-1 text-slate-400 hover:border-rose-500/50 hover:text-rose-300 disabled:opacity-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-800 bg-slate-950/70 px-5 py-2.5 text-[10px] text-slate-400">
          <div className="flex items-center gap-1.5">
            <FolderOpen className="h-3.5 w-3.5 text-cyan-400" />
            <span>Carpeta permanente:</span>
            <code className="rounded bg-slate-900 px-1.5 py-0.5 font-mono text-slate-200">
              {data?.storage_dir || '~/.nikk_slicer/timelapses'}
            </code>
          </div>
          <span>Compatible con macOS y Windows</span>
        </div>
      </div>
    </div>
  );
}
