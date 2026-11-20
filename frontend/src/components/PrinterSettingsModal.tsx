import { useEffect, useState } from 'react';
import {
  Activity,
  HardDrive,
  KeyRound,
  Loader2,
  Plus,
  RefreshCw,
  Save,
  Search,
  Server,
  Trash2,
  Usb,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react';
import {
  discoverNetworkPrinters,
  fetchPrintersConfig,
  testPrinterConnection,
  updatePrintersConfig,
  type DiscoveredPrinter,
  type MachineProfileInfo,
  type PrinterLiveStatus,
  type PrinterNetworkEntry,
  type PrintersConfigResponse,
  type ProfileId,
} from '../services/api';

interface PrinterSettingsModalProps {
  open: boolean;
  onClose: () => void;
  machineProfiles: MachineProfileInfo[];
  onSaved?: (config: PrintersConfigResponse) => void;
  onOpenAddCatalog?: () => void;
}

const DEFAULT_PROFILE_META: Array<{
  profile_id: ProfileId;
  display_name: string;
}> = [
  { profile_id: 'flsun_t1_pro', display_name: 'FLSUN T1 Pro' },
  { profile_id: 'creator5_pro', display_name: 'FlashForge Creator 5 Pro' },
  { profile_id: 'flsun_v400', display_name: 'FLSUN V400' },
  { profile_id: 'flsun_sr', display_name: 'FLSUN Super Racer (SR)' },
  { profile_id: 'ender3_s1_pro', display_name: 'Creality Ender 3 S1 Pro' },
];

export function PrinterSettingsModal({
  open,
  onClose,
  machineProfiles,
  onSaved,
  onOpenAddCatalog,
}: PrinterSettingsModalProps) {
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMsg, setSavedMsg] = useState<string | null>(null);

  const [entries, setEntries] = useState<Record<string, PrinterNetworkEntry>>({});
  const [serialPorts, setSerialPorts] = useState<string[]>([]);
  const [volumes, setVolumes] = useState<string[]>([]);
  const [geminiMasked, setGeminiMasked] = useState('');
  const [deepseekMasked, setDeepseekMasked] = useState('');
  const [geminiInput, setGeminiInput] = useState('');
  const [deepseekInput, setDeepseekInput] = useState('');

  const [newProfileId, setNewProfileId] = useState<ProfileId>('flsun_t1_pro');
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, PrinterLiveStatus>>({});
  const [isDiscovering, setIsDiscovering] = useState(false);
  const [discoveredSubnet, setDiscoveredSubnet] = useState<string | null>(null);
  const [discoveredList, setDiscoveredList] = useState<DiscoveredPrinter[]>([]);

  const profileOptions =
    machineProfiles.length > 0
      ? machineProfiles.map((p) => ({
          profile_id: p.profile_id,
          display_name: p.display_name,
        }))
      : DEFAULT_PROFILE_META;

  const loadConfig = async () => {
    setLoading(true);
    setError(null);
    try {
      const cfg = await fetchPrintersConfig();
      setEntries(cfg.printers);
      setSerialPorts(cfg.detected_serial_ports);
      setVolumes(cfg.detected_volumes);
      setGeminiMasked(cfg.gemini_key_masked);
      setDeepseekMasked(cfg.deepseek_key_masked);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error cargando configuración.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      setSavedMsg(null);
      setGeminiInput('');
      setDeepseekInput('');
      setTestResults({});
      void loadConfig();
    }
  }, [open]);

  if (!open) return null;

  const updateField = (
    pid: string,
    field: keyof PrinterNetworkEntry,
    value: string | number | boolean,
  ) => {
    setEntries((prev) => {
      const cur = prev[pid];
      if (!cur) return prev;
      const next: PrinterNetworkEntry = {
        ...cur,
        [field]: value,
      };
      // Si se cambia la IP y camera_url coincide con el patrón anterior o está vacía, actualizarla
      if (field === 'ip' && typeof value === 'string') {
        const oldIp = cur.ip.trim();
        const nextIp = value.trim();
        const prevCam = cur.camera_url.trim();
        if (nextIp) {
          if (cur.protocol === 'moonraker') {
            const oldPattern = oldIp ? `http://${oldIp}/webcam/?action=stream` : '';
            if (!prevCam || prevCam === oldPattern) {
              next.camera_url = `http://${nextIp}/webcam/?action=stream`;
            }
          } else if (cur.protocol === 'flashforge_lan') {
            const oldPattern = oldIp ? `http://${oldIp}:8080/?action=stream` : '';
            if (!prevCam || prevCam === oldPattern) {
              next.camera_url = `http://${nextIp}:8080/?action=stream`;
            }
          }
        }
      }
      return { ...prev, [pid]: next };
    });
  };

  const handleAddPrinter = () => {
    const profileMeta =
      profileOptions.find((p) => p.profile_id === newProfileId) ?? profileOptions[0];
    const existingSame = Object.values(entries).filter(
      (e) => e.profile_id === newProfileId,
    ).length;
    let suffix = existingSame + 1;
    let newId = `${newProfileId}_${suffix}`;
    while (entries[newId]) {
      suffix += 1;
      newId = `${newProfileId}_${suffix}`;
    }

    const protocol: PrinterNetworkEntry['protocol'] =
      newProfileId === 'creator5_pro'
        ? 'flashforge_lan'
        : newProfileId === 'ender3_s1_pro' || newProfileId === 'flsun_sr'
          ? 'marlin_serial'
          : 'moonraker';

    const newEntry: PrinterNetworkEntry = {
      id: newId,
      name: `${profileMeta.display_name} #${suffix}`,
      profile_id: newProfileId,
      protocol,
      ip: '',
      fallback_ips: [],
      port: protocol === 'flashforge_lan' ? 8899 : protocol === 'moonraker' ? 80 : 7125,
      http_port: 8080,
      access_code: '',
      serial_number: '',
      serial_port: protocol === 'marlin_serial' ? '/dev/cu.usbserial-1410' : '',
      baudrate: 115200,
      sd_volume_path: '',
      camera_url: '',
      enabled: true,
    };

    setEntries((prev) => ({ ...prev, [newId]: newEntry }));
    setSavedMsg(null);
  };

  const handleRemovePrinter = (pid: string) => {
    if (Object.keys(entries).length <= 1) return;
    setEntries((prev) => {
      const next = { ...prev };
      delete next[pid];
      return next;
    });
    setTestResults((prev) => {
      const next = { ...prev };
      delete next[pid];
      return next;
    });
  };

  const handleTestConnection = async (pid: string) => {
    const entry = entries[pid];
    if (!entry) return;
    setTestingId(pid);
    setError(null);
    try {
      const status = await testPrinterConnection(entry);
      setTestResults((prev) => ({ ...prev, [pid]: status }));
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : `Error probando conexión de ${entry.name}.`,
      );
    } finally {
      setTestingId(null);
    }
  };

  const handleDiscoverNetwork = async () => {
    setIsDiscovering(true);
    setError(null);
    try {
      const res = await discoverNetworkPrinters();
      setDiscoveredSubnet(res.subnet);
      setDiscoveredList(res.discovered);
    } catch (err: unknown) {
      setError(
        err instanceof Error ? err.message : 'Error escaneando la red local.',
      );
    } finally {
      setIsDiscovering(false);
    }
  };

  const handleApplyDiscovered = (item: DiscoveredPrinter) => {
    const targetEntry = Object.entries(entries).find(
      ([, e]) => e.ip === item.ip,
    ) ??
      Object.entries(entries).find(
        ([, e]) => e.profile_id === item.suggested_profile && !e.ip,
      );

    if (targetEntry) {
      const [tid] = targetEntry;
      updateField(tid, 'ip', item.ip);
      updateField(tid, 'port', item.port);
      updateField(tid, 'camera_url', item.camera_url);
      setSavedMsg(`IP ${item.ip} asignada a ${entries[tid].name}. Pulsa Guardar para persistir.`);
      return;
    }

    const profileMeta =
      profileOptions.find((p) => p.profile_id === item.suggested_profile) ?? profileOptions[0];
    const existingSame = Object.values(entries).filter(
      (e) => e.profile_id === item.suggested_profile,
    ).length;
    let suffix = existingSame + 1;
    let newId = `${item.suggested_profile}_${suffix}`;
    while (entries[newId]) {
      suffix += 1;
      newId = `${item.suggested_profile}_${suffix}`;
    }
    setEntries((prev) => ({
      ...prev,
      [newId]: {
        id: newId,
        name: `${profileMeta.display_name} #${suffix}`,
        profile_id: item.suggested_profile,
        protocol: item.protocol,
        ip: item.ip,
        fallback_ips: [item.ip],
        port: item.port,
        http_port: 8080,
        access_code: '',
        serial_number: '',
        serial_port: '',
        baudrate: 115200,
        sd_volume_path: '',
        camera_url: item.camera_url,
        enabled: true,
      },
    }));
    setSavedMsg(`Nueva máquina ${item.ip} añadida. Pulsa Guardar Configuración.`);
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSavedMsg(null);
    try {
      const res = await updatePrintersConfig({
        printers: entries,
        gemini_api_key: geminiInput.trim() || undefined,
        deepseek_api_key: deepseekInput.trim() || undefined,
      });
      setEntries(res.printers);
      setGeminiMasked(res.gemini_key_masked);
      setDeepseekMasked(res.deepseek_key_masked);
      setGeminiInput('');
      setDeepseekInput('');
      setSavedMsg('Configuración guardada en printers_config.json y .env.');
      onSaved?.(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error guardando configuración.');
    } finally {
      setSaving(false);
    }
  };

  const printerEntries = Object.entries(entries);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div className="flex max-h-[92vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-slate-700 bg-slate-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3.5">
          <div className="flex items-center gap-2">
            <Server className="h-4 w-4 text-cyan-400" />
            <h2 className="text-sm font-bold text-slate-100">
              Gestión Multi-Impresora ({printerEntries.length}), USB/SD y Claves IA
            </h2>
          </div>
          <div className="flex items-center gap-2">
            {onOpenAddCatalog && (
              <button
                type="button"
                onClick={() => {
                  onClose();
                  onOpenAddCatalog();
                }}
                className="inline-flex items-center gap-1 rounded-lg border border-cyan-500/50 bg-cyan-500/15 px-2.5 py-1.5 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
              >
                <Plus className="h-3.5 w-3.5" />
                <span>Agregar desde Catálogo</span>
              </button>
            )}
            <button
              type="button"
              onClick={() => void loadConfig()}
              className="rounded-lg border border-slate-700 bg-slate-950 p-1.5 text-slate-300 hover:border-cyan-500/60"
              title="Reescanear puertos USB y volúmenes SD"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-slate-700 bg-slate-950 p-1.5 text-slate-300 hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-5">
          {error && (
            <div className="rounded-xl border border-rose-500/40 bg-rose-500/15 p-3 text-xs text-rose-200">
              {error}
            </div>
          )}
          {savedMsg && (
            <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/15 p-3 text-xs text-emerald-200">
              {savedMsg}
            </div>
          )}

          {/* Bloque API Keys Gemini / DeepSeek */}
          <section className="space-y-2.5 rounded-xl border border-violet-500/30 bg-violet-950/20 p-4">
            <div className="flex items-center gap-2 text-xs font-bold uppercase tracking-wide text-violet-200">
              <KeyRound className="h-4 w-4 text-violet-400" />
              Copiloto IA (backend/.env)
            </div>
            <p className="text-[11px] text-slate-400">
              Se almacenan en <code className="text-slate-300">backend/.env</code>. Si dejas un campo vacío, se conserva la clave guardada.
            </p>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className="mb-1 flex items-center justify-between text-[11px] text-slate-300">
                  <span>GEMINI_API_KEY</span>
                  {geminiMasked && (
                    <span className="font-mono text-[10px] text-emerald-300">
                      Activa: {geminiMasked}
                    </span>
                  )}
                </label>
                <input
                  type="password"
                  placeholder={geminiMasked ? '•••••••• (guardada)' : 'AIza...'}
                  value={geminiInput}
                  onChange={(e) => setGeminiInput(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 focus:border-violet-400 focus:outline-none"
                />
              </div>
              <div>
                <label className="mb-1 flex items-center justify-between text-[11px] text-slate-300">
                  <span>DEEPSEEK_API_KEY</span>
                  {deepseekMasked && (
                    <span className="font-mono text-[10px] text-emerald-300">
                      Activa: {deepseekMasked}
                    </span>
                  )}
                </label>
                <input
                  type="password"
                  placeholder={deepseekMasked ? '•••••••• (guardada)' : 'sk-...'}
                  value={deepseekInput}
                  onChange={(e) => setDeepseekInput(e.target.value)}
                  className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 focus:border-violet-400 focus:outline-none"
                />
              </div>
            </div>
          </section>

          {/* Barra "+ Agregar Impresora" y "Auto-Descubrir en Red" */}
          <section className="space-y-2.5 rounded-xl border border-cyan-500/30 bg-cyan-950/15 px-3.5 py-2.5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="text-xs font-semibold text-cyan-200">
                Agregar o Auto-Descubrir Máquinas en la Red Local
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  disabled={isDiscovering}
                  onClick={() => void handleDiscoverNetwork()}
                  className="flex items-center gap-1.5 rounded-lg border border-emerald-500/50 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-50"
                >
                  {isDiscovering ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Search className="h-3.5 w-3.5" />
                  )}
                  Auto-Descubrir en Red
                </button>
                <select
                  value={newProfileId}
                  onChange={(e) => setNewProfileId(e.target.value as ProfileId)}
                  aria-label="Modelo base para nueva impresora"
                  className="rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                >
                  {profileOptions.map((opt) => (
                    <option key={opt.profile_id} value={opt.profile_id}>
                      {opt.display_name}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  onClick={handleAddPrinter}
                  className="flex items-center gap-1 rounded-lg border border-cyan-500/50 bg-cyan-500/20 px-3 py-1.5 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/30"
                >
                  <Plus className="h-3.5 w-3.5" />
                  + Agregar Impresora
                </button>
              </div>
            </div>

            {discoveredSubnet && (
              <div className="space-y-1.5 border-t border-cyan-500/20 pt-2">
                <p className="text-[11px] text-slate-300">
                  Subred escaneada: <span className="font-mono text-cyan-300">{discoveredSubnet}</span> ·{' '}
                  {discoveredList.length} impresora(s) detectada(s)
                </p>
                {discoveredList.length > 0 && (
                  <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                    {discoveredList.map((item) => (
                      <div
                        key={`${item.ip}:${item.port}`}
                        className="flex items-center justify-between gap-2 rounded-lg border border-emerald-500/30 bg-slate-950/80 px-2.5 py-1.5 text-[11px]"
                      >
                        <div className="min-w-0">
                          <div className="truncate font-semibold text-emerald-200">
                            {item.hostname}
                          </div>
                          <div className="font-mono text-[10px] text-slate-400">
                            {item.ip}:{item.port} · {item.protocol}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => handleApplyDiscovered(item)}
                          className="shrink-0 rounded border border-emerald-500/45 bg-emerald-500/20 px-2 py-1 text-[10px] font-semibold text-emerald-100 hover:bg-emerald-500/30"
                        >
                          Usar IP
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </section>

          {/* Lista editable de instancias */}
          <div className="space-y-3">
            {printerEntries.map(([pid, cfg]) => {
              const testRes = testResults[pid];
              const isTesting = testingId === pid;
              const baseLabel =
                profileOptions.find((o) => o.profile_id === cfg.profile_id)?.display_name ??
                cfg.profile_id;

              return (
                <section
                  key={pid}
                  className={`space-y-2.5 rounded-xl border p-3.5 ${
                    cfg.enabled
                      ? 'border-slate-800 bg-slate-950/60'
                      : 'border-slate-800/50 bg-slate-950/30 opacity-70'
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 flex-1 items-center gap-2">
                      <input
                        type="text"
                        value={cfg.name}
                        onChange={(e) => updateField(pid, 'name', e.target.value)}
                        aria-label={`Nombre identificador ${pid}`}
                        placeholder="Nombre de impresora (ej. FLSUN T1 Pro #1)"
                        className="w-full max-w-xs rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs font-bold text-slate-100 focus:border-cyan-400 focus:outline-none"
                      />
                      <span className="shrink-0 rounded bg-slate-800 px-2 py-0.5 font-mono text-[10px] text-slate-300">
                        {baseLabel}
                      </span>
                      <span className="shrink-0 rounded bg-slate-800 px-2 py-0.5 font-mono text-[10px] text-cyan-300">
                        {cfg.protocol}
                      </span>
                    </div>

                    <div className="flex items-center gap-2">
                      <label className="flex cursor-pointer items-center gap-1 text-[11px] text-slate-300">
                        <input
                          type="checkbox"
                          checked={cfg.enabled}
                          onChange={(e) => updateField(pid, 'enabled', e.target.checked)}
                          className="accent-cyan-500"
                        />
                        Activa
                      </label>
                      <button
                        type="button"
                        disabled={isTesting}
                        onClick={() => void handleTestConnection(pid)}
                        className="flex items-center gap-1 rounded-lg border border-cyan-500/45 bg-cyan-500/15 px-2.5 py-1 text-[11px] font-semibold text-cyan-100 hover:bg-cyan-500/25 disabled:opacity-50"
                      >
                        {isTesting ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Activity className="h-3 w-3" />
                        )}
                        Probar Conexión
                      </button>
                      {printerEntries.length > 1 && (
                        <button
                          type="button"
                          onClick={() => handleRemovePrinter(pid)}
                          title="Eliminar máquina de la granja"
                          className="rounded-lg border border-slate-800 bg-slate-900 p-1 text-slate-500 hover:border-rose-500/40 hover:text-rose-400"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </div>

                  {testRes && (
                    <div
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 text-[11px] ${
                        testRes.online
                          ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-200'
                          : 'border-amber-500/40 bg-amber-500/10 text-amber-200'
                      }`}
                    >
                      <span className="flex items-center gap-1.5 font-medium">
                        {testRes.online ? (
                          <Wifi className="h-3.5 w-3.5 text-emerald-400" />
                        ) : (
                          <WifiOff className="h-3.5 w-3.5 text-amber-400" />
                        )}
                        {testRes.online ? 'En línea' : 'Sin respuesta'} · {testRes.state} ·{' '}
                        {testRes.message}
                      </span>
                      {(testRes.nozzle_temp !== null || testRes.bed_temp !== null) && (
                        <span className="font-mono text-[10px]">
                          Boquilla: {testRes.nozzle_temp ?? '—'}°C · Cama:{' '}
                          {testRes.bed_temp ?? '—'}°C
                        </span>
                      )}
                    </div>
                  )}

                  {cfg.protocol === 'marlin_serial' ? (
                    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                      <div>
                        <label className="mb-1 flex items-center gap-1 text-[11px] text-slate-300">
                          <Usb className="h-3 w-3 text-cyan-400" />
                          Puerto Serial USB (`/dev/cu.*`)
                        </label>
                        <input
                          type="text"
                          list="macos-serial-ports"
                          value={cfg.serial_port}
                          onChange={(e) =>
                            updateField(pid, 'serial_port', e.target.value)
                          }
                          placeholder="/dev/cu.usbserial-1410"
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                        />
                        <datalist id="macos-serial-ports">
                          {serialPorts.map((sp) => (
                            <option key={sp} value={sp} />
                          ))}
                        </datalist>
                        {serialPorts.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {serialPorts.map((sp) => (
                              <button
                                key={sp}
                                type="button"
                                onClick={() => updateField(pid, 'serial_port', sp)}
                                className="rounded bg-cyan-500/15 px-1.5 py-0.5 font-mono text-[10px] text-cyan-300 hover:bg-cyan-500/25"
                              >
                                {sp}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>

                      <div>
                        <label className="mb-1 flex items-center gap-1 text-[11px] text-slate-300">
                          <HardDrive className="h-3 w-3 text-emerald-400" />
                          Volumen Tarjeta SD (`/Volumes/`)
                        </label>
                        <input
                          type="text"
                          list="macos-sd-volumes"
                          value={cfg.sd_volume_path}
                          onChange={(e) =>
                            updateField(pid, 'sd_volume_path', e.target.value)
                          }
                          placeholder="/Volumes/NO NAME"
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                        />
                        <datalist id="macos-sd-volumes">
                          {volumes.map((v) => (
                            <option key={v} value={v} />
                          ))}
                        </datalist>
                        {volumes.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {volumes.map((v) => (
                              <button
                                key={v}
                                type="button"
                                onClick={() => updateField(pid, 'sd_volume_path', v)}
                                className="rounded bg-emerald-500/15 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300 hover:bg-emerald-500/25"
                              >
                                {v}
                              </button>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          IP Local
                        </label>
                        <input
                          type="text"
                          value={cfg.ip}
                          onChange={(e) => updateField(pid, 'ip', e.target.value)}
                          placeholder="192.168.40.39"
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          Puerto ({cfg.protocol === 'moonraker' ? '7125' : '8899'})
                        </label>
                        <input
                          type="number"
                          value={cfg.port}
                          onChange={(e) =>
                            updateField(pid, 'port', Number(e.target.value) || 7125)
                          }
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                        />
                      </div>
                      <div>
                        <label className="mb-1 block text-[11px] text-slate-400">
                          URL Cámara MJPEG
                        </label>
                        <input
                          type="text"
                          value={cfg.camera_url}
                          onChange={(e) =>
                            updateField(pid, 'camera_url', e.target.value)
                          }
                          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                        />
                      </div>

                      {cfg.protocol === 'flashforge_lan' && (
                        <>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              Access Code (LAN)
                            </label>
                            <input
                              type="text"
                              value={cfg.access_code}
                              onChange={(e) =>
                                updateField(pid, 'access_code', e.target.value)
                              }
                              placeholder="Ej. 12345678"
                              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                            />
                          </div>
                          <div>
                            <label className="mb-1 block text-[11px] text-slate-400">
                              Serial Number (opcional)
                            </label>
                            <input
                              type="text"
                              value={cfg.serial_number}
                              onChange={(e) =>
                                updateField(pid, 'serial_number', e.target.value)
                              }
                              className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-slate-100"
                            />
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </section>
              );
            })}
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-800 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-xl border border-slate-700 px-4 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-800"
          >
            Cerrar
          </button>
          <button
            type="button"
            disabled={saving || loading}
            onClick={() => void handleSave()}
            className="flex items-center gap-1.5 rounded-xl bg-cyan-500 px-4 py-1.5 text-xs font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50"
          >
            {saving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Save className="h-3.5 w-3.5" />
            )}
            Guardar Configuración
          </button>
        </div>
      </div>
    </div>
  );
}
