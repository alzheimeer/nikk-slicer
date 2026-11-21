import { useEffect, useState } from 'react';
import {
  Check,
  CheckCircle2,
  Copy,
  Cpu,
  Download,
  FolderSearch,
  KeyRound,
  Loader2,
  RefreshCw,
  Server,
  Sparkles,
  X,
} from 'lucide-react';
import {
  fetchSystemEnvironment,
  rescanSystemSlicers,
  saveSystemAIConfig,
  setManualSlicerPath,
  testSystemAIConnection,
  type SystemEnvironmentResponse,
} from '../services/api';
import { useI18n } from '../i18n/I18nContext';

export interface SystemSetupModalProps {
  open: boolean;
  onClose: () => void;
}

export function SystemSetupModal({ open, onClose }: SystemSetupModalProps) {
  const { t } = useI18n();
  const [env, setEnv] = useState<SystemEnvironmentResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [rescanning, setRescanning] = useState(false);
  const [aiProvider, setAiProvider] = useState<'deepseek' | 'gemini'>('deepseek');
  const [aiKey, setAiKey] = useState('');
  const [savingAi, setSavingAi] = useState(false);
  const [testingAi, setTestingAi] = useState(false);
  const [aiTestMsg, setAiTestMsg] = useState<string | null>(null);
  const [mcpCopied, setMcpCopied] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const loadEnv = async () => {
    setLoading(true);
    setErrorMsg(null);
    try {
      const data = await fetchSystemEnvironment();
      setEnv(data);
      setAiProvider(data.ai_config.provider);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Error leyendo entorno del sistema.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      void loadEnv();
    }
  }, [open]);

  if (!open) return null;

  const handleRescan = async () => {
    setRescanning(true);
    setErrorMsg(null);
    try {
      const res = await rescanSystemSlicers();
      setEnv(res.environment);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Error al re-escanear laminadores.');
    } finally {
      setRescanning(false);
    }
  };

  const handleLocateManually = async (slicerId: string, slicerName: string) => {
    setErrorMsg(null);
    const pyApi = (
      window as unknown as {
        pywebview?: {
          api?: { pick_slicer_executable?: () => Promise<{ cancelled?: boolean; path?: string }> };
        };
      }
    ).pywebview?.api;

    let chosenPath: string | null = null;
    if (pyApi?.pick_slicer_executable) {
      const res = await pyApi.pick_slicer_executable();
      if (!res?.cancelled && res?.path) {
        chosenPath = res.path;
      }
    } else {
      const entered = window.prompt(`Ruta del ejecutable de ${slicerName}:`, '');
      if (entered && entered.trim()) {
        chosenPath = entered.trim();
      }
    }

    if (!chosenPath) return;
    try {
      const res = await setManualSlicerPath(slicerId, chosenPath);
      setEnv(res.environment);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Ruta de ejecutable inválida.');
    }
  };

  const handleSaveAi = async () => {
    setSavingAi(true);
    setAiTestMsg(null);
    setErrorMsg(null);
    try {
      const res = await saveSystemAIConfig(aiProvider, aiKey);
      setEnv((prev) => (prev ? { ...prev, ai_config: res.ai_config } : prev));
      setAiKey('');
      setAiTestMsg(`Configuración guardada (${res.ai_config.provider.toUpperCase()}).`);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : 'Error guardando API Key.');
    } finally {
      setSavingAi(false);
    }
  };

  const handleTestAi = async () => {
    setTestingAi(true);
    setAiTestMsg(null);
    try {
      const res = await testSystemAIConnection();
      setAiTestMsg(
        res.connected
          ? `Conexión exitosa con ${res.provider}`
          : 'Sin API Key activa (usando heurística local).',
      );
    } catch (err) {
      setAiTestMsg(err instanceof Error ? err.message : 'Error probando conexión.');
    } finally {
      setTestingAi(false);
    }
  };

  const handleCopyMcpConfig = async () => {
    const snippet = JSON.stringify(
      {
        mcpServers: {
          'nikk-slicer': {
            url: env?.mcp.http_url || 'http://127.0.0.1:8000/mcp',
            command: 'python3',
            args: ['-m', 'backend.app.mcp_server'],
          },
        },
      },
      null,
      2,
    );
    try {
      await navigator.clipboard.writeText(snippet);
      setMcpCopied(true);
      window.setTimeout(() => setMcpCopied(false), 2500);
    } catch {
      // silencioso
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/85 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
    >
      <div className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-500/40 bg-cyan-500/15">
              <Cpu className="h-4.5 w-4.5 text-cyan-300" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-white">
                {t.systemSetup.title}
              </h2>
              <p className="text-[11px] text-slate-400">
                {env ? `${env.os} · ${env.user_data_dir}` : t.systemSetup.scanning}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={rescanning}
              onClick={() => void handleRescan()}
              className="flex items-center gap-1.5 rounded-xl border border-cyan-500/40 bg-cyan-500/15 px-3 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/25 disabled:opacity-50"
            >
              {rescanning ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              {rescanning ? t.systemSetup.scanning : t.systemSetup.rescan}
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-700 bg-slate-800 p-1.5 text-slate-300 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5 text-xs">
          {errorMsg && (
            <div className="rounded-xl border border-rose-500/40 bg-rose-500/15 px-3 py-2 text-rose-200">
              {errorMsg}
            </div>
          )}

          {loading && !env ? (
            <div className="flex items-center justify-center gap-2 py-10 text-slate-400">
              <Loader2 className="h-4 w-4 animate-spin text-cyan-400" />
              Escaneando motores 3D...
            </div>
          ) : (
            <>
              {/* Tarjetas de Motores 3D */}
              <div className="space-y-2">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-400">
                  Laminadores Detectados ({env?.os})
                </p>
                <div className="space-y-2">
                  {(env?.slicers ?? []).map((s) => (
                    <div
                      key={s.id}
                      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-950/80 p-3"
                    >
                      <div className="min-w-0 flex-1 space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-slate-100">{s.name}</span>
                          {s.detected ? (
                            <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
                              <CheckCircle2 className="h-3 w-3" />
                              {t.systemSetup.installed}
                            </span>
                          ) : (
                            <span className="rounded-full border border-amber-500/40 bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-200">
                              {t.systemSetup.missing}
                            </span>
                          )}
                        </div>
                        <p className="text-[11px] text-slate-400">{s.description}</p>
                        {s.executable_path && (
                          <p className="truncate font-mono text-[10px] text-cyan-300">
                            {s.executable_path}
                          </p>
                        )}
                      </div>

                      <div className="flex shrink-0 items-center gap-1.5">
                        {!s.detected && (
                          <button
                            type="button"
                            onClick={() => window.open(s.download_url, '_blank')}
                            className="flex items-center gap-1 rounded-lg border border-amber-500/45 bg-amber-500/15 px-2.5 py-1.5 text-[11px] font-semibold text-amber-200 hover:bg-amber-500/25"
                          >
                            <Download className="h-3.5 w-3.5" />
                            Descargar Oficial
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => void handleLocateManually(s.id, s.name)}
                          className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-[11px] font-medium text-slate-200 hover:border-cyan-500/60"
                        >
                          <FolderSearch className="h-3.5 w-3.5 text-cyan-400" />
                          Ubicar manualmente...
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Configuración IA BYOK */}
              <div className="space-y-2.5 rounded-xl border border-violet-500/30 bg-violet-500/5 p-3.5">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-violet-200">
                    <Sparkles className="h-3.5 w-3.5 text-violet-400" />
                    Inteligencia Artificial (BYOK · DeepSeek / Gemini)
                  </span>
                  {env?.ai_config.has_api_key && (
                    <span className="font-mono text-[10px] text-emerald-300">
                      Activa ({env.ai_config.provider.toUpperCase()} · {env.ai_config.masked_key})
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-[170px_1fr_auto_auto]">
                  <select
                    value={aiProvider}
                    onChange={(e) => setAiProvider(e.target.value as 'deepseek' | 'gemini')}
                    className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100"
                  >
                    <option value="deepseek">DeepSeek API</option>
                    <option value="gemini">Google Gemini</option>
                  </select>
                  <div className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5">
                    <KeyRound className="h-3.5 w-3.5 text-slate-400" />
                    <input
                      type="password"
                      value={aiKey}
                      onChange={(e) => setAiKey(e.target.value)}
                      placeholder="Pega tu API Key (sk-... / AIza...)"
                      className="min-w-0 flex-1 bg-transparent text-xs text-slate-100 outline-none"
                    />
                  </div>
                  <button
                    type="button"
                    disabled={savingAi}
                    onClick={() => void handleSaveAi()}
                    className="rounded-lg border border-violet-500/45 bg-violet-500/20 px-3 py-1.5 font-semibold text-violet-100 hover:bg-violet-500/30 disabled:opacity-50"
                  >
                    {savingAi ? 'Guardando...' : 'Guardar'}
                  </button>
                  <button
                    type="button"
                    disabled={testingAi}
                    onClick={() => void handleTestAi()}
                    className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-1.5 font-medium text-slate-200 hover:border-emerald-500/50 disabled:opacity-50"
                  >
                    {testingAi ? '...' : t.systemSetup.testConnection}
                  </button>
                </div>
                {aiTestMsg && <p className="text-[11px] text-cyan-200">{aiTestMsg}</p>}
              </div>

              {/* Tarjeta Servidor MCP Interno */}
              <div className="space-y-2 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-3.5">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-emerald-200">
                    <Server className="h-3.5 w-3.5 text-emerald-400" />
                    {t.systemSetup.mcpServer}
                  </span>
                  <span className="rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 font-mono text-[10px] font-semibold text-emerald-300">
                    {env?.mcp.tools_count ?? 19} tools · 3 resources
                  </span>
                </div>
                <div className="grid grid-cols-1 gap-1.5 font-mono text-[10px] text-slate-300 sm:grid-cols-2">
                  <div className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5">
                    <span className="text-slate-500">HTTP/SSE: </span>
                    {env?.mcp.http_url || 'http://127.0.0.1:8000/mcp'}
                  </div>
                  <div className="rounded-lg border border-slate-800 bg-slate-950 px-2.5 py-1.5">
                    <span className="text-slate-500">stdio: </span>
                    {env?.mcp.stdio_command || 'python3 -m backend.app.mcp_server'}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void handleCopyMcpConfig()}
                  className="flex items-center gap-1.5 rounded-lg border border-emerald-500/45 bg-emerald-500/15 px-3 py-1.5 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/25"
                >
                  {mcpCopied ? (
                    <>
                      <Check className="h-3.5 w-3.5" />
                      {t.systemSetup.copied}
                    </>
                  ) : (
                    <>
                      <Copy className="h-3.5 w-3.5" />
                      {t.systemSetup.copyMcpJson}
                    </>
                  )}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
