import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Copy, RefreshCw, Trash2, X } from 'lucide-react';
import {
  clearErrorJournal,
  fetchErrorJournal,
  type ErrorJournalEntry,
} from '../services/api';

interface ErrorJournalModalProps {
  open: boolean;
  onClose: () => void;
}

export function ErrorJournalModal({ open, onClose }: ErrorJournalModalProps) {
  const [entries, setEntries] = useState<ErrorJournalEntry[]>([]);
  const [logPath, setLogPath] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const loadJournal = useCallback(async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const data = await fetchErrorJournal(80);
      setEntries(data.entries);
      setLogPath(data.log_path);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Error consultando bitácora.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void loadJournal();
    }
  }, [open, loadJournal]);

  if (!open) return null;

  const handleClear = async () => {
    setLoading(true);
    try {
      await clearErrorJournal();
      setEntries([]);
    } catch (err: unknown) {
      setErrorMsg(err instanceof Error ? err.message : 'Error limpiando bitácora.');
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = async (idx: number, entry: ErrorJournalEntry) => {
    const text = `[${entry.timestamp}] [${entry.source}${entry.printer_id ? ` | ${entry.printer_id}` : ''}] ${entry.message}${entry.detail ? `\nDetalle: ${entry.detail}` : ''}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIdx(idx);
      setTimeout(() => setCopiedIdx(null), 1500);
    } catch {
      // ignore clipboard errors
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div className="flex max-h-[85vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-4 py-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-400" />
            <div>
              <h2 className="text-sm font-semibold text-slate-100">
                Bitácora de Fallos ({entries.length})
              </h2>
              {logPath && (
                <p className="font-mono text-[10px] text-slate-400" title={logPath}>
                  Archivo: {logPath}
                </p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={loading}
              onClick={() => void loadJournal()}
              className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1 text-xs text-cyan-300 hover:border-cyan-500/60 disabled:opacity-40"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
              Actualizar
            </button>
            {entries.length > 0 && (
              <button
                type="button"
                disabled={loading}
                onClick={() => void handleClear()}
                className="flex items-center gap-1 rounded-lg border border-rose-500/40 bg-rose-500/15 px-2.5 py-1 text-xs text-rose-200 hover:bg-rose-500/25 disabled:opacity-40"
              >
                <Trash2 className="h-3.5 w-3.5" />
                Limpiar
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1 text-slate-400 hover:bg-slate-800 hover:text-slate-100"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-2 overflow-y-auto p-4">
          {errorMsg && (
            <div className="rounded-lg border border-rose-500/40 bg-rose-500/10 p-2.5 text-xs text-rose-200">
              {errorMsg}
            </div>
          )}

          {entries.length === 0 ? (
            <div className="py-12 text-center text-xs text-slate-400">
              No hay fallos registrados en la bitácora.
            </div>
          ) : (
            entries.map((entry, idx) => (
              <div
                key={`${entry.timestamp}-${idx}`}
                className="space-y-1.5 rounded-xl border border-slate-800 bg-slate-950/75 p-3 text-xs"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded bg-rose-500/20 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-rose-200">
                      {entry.source}
                    </span>
                    {entry.printer_id && (
                      <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300">
                        {entry.printer_id}
                      </span>
                    )}
                    <span className="font-mono text-[10px] text-slate-400">
                      {entry.timestamp}
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleCopy(idx, entry)}
                    className="flex items-center gap-1 rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500/50"
                  >
                    <Copy className="h-3 w-3" />
                    {copiedIdx === idx ? 'Copiado' : 'Copiar'}
                  </button>
                </div>
                <p className="font-mono text-[11px] text-rose-100">{entry.message}</p>
                {entry.detail && (
                  <p className="break-all font-mono text-[10px] text-slate-400">
                    {entry.detail}
                  </p>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
