import { useEffect, useState } from 'react';
import {
  Check,
  Cpu,
  Flame,
  HardDrive,
  Loader2,
  Palette,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
  Wifi,
  X,
  Zap,
} from 'lucide-react';
import {
  addCustomPrinter,
  fetchPrinterCatalog,
  syncPrinterCatalog,
  type OrcaCatalogPrinter,
} from '../services/api';

interface AddPrinterModalProps {
  open: boolean;
  onClose: () => void;
  onAdded: (printerId: string) => void;
}

export function AddPrinterModal({ open, onClose, onAdded }: AddPrinterModalProps) {
  const [query, setQuery] = useState('');
  const [vendor, setVendor] = useState('');
  const [multicolorOnly, setMulticolorOnly] = useState(false);
  const [vendors, setVendors] = useState<string[]>([]);
  const [results, setResults] = useState<OrcaCatalogPrinter[]>([]);
  const [catalogTotal, setCatalogTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [selected, setSelected] = useState<OrcaCatalogPrinter | null>(null);

  // Campos de personalización rápida
  const [customName, setCustomName] = useState('');
  const [nozzleDiameter, setNozzleDiameter] = useState<number>(0.4);
  const [connectionMode, setConnectionMode] = useState<'lan' | 'usb_sd'>('lan');
  const [ip, setIp] = useState('');
  const [isMulticolor, setIsMulticolor] = useState(false);
  const [toolCount, setToolCount] = useState(4);
  const [saving, setSaving] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void fetchPrinterCatalog({
        q: query,
        vendor,
        multicolor_only: multicolorOnly,
        limit: 120,
      })
        .then((res) => {
          if (cancelled) return;
          setResults(res.printers);
          setVendors(res.vendors);
          setCatalogTotal(res.catalog_total);
          if (!selected && res.printers.length > 0) {
            handlePickModel(res.printers[0]);
          }
        })
        .catch((err) => {
          if (!cancelled) setErrorMsg(err instanceof Error ? err.message : String(err));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 180);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, query, vendor, multicolorOnly]);

  function handlePickModel(item: OrcaCatalogPrinter) {
    setSelected(item);
    setCustomName(item.model_name);
    setNozzleDiameter(item.nozzle_diameters.includes(0.4) ? 0.4 : (item.nozzle_diameters[0] ?? 0.4));
    setIsMulticolor(item.capabilities.is_multicolor);
    setToolCount(Math.max(2, item.capabilities.tool_count || 4));
    setErrorMsg(null);
  }

  async function handleSyncGithub() {
    setSyncing(true);
    setErrorMsg(null);
    try {
      await syncPrinterCatalog();
      const res = await fetchPrinterCatalog({ q: query, vendor, multicolor_only: multicolorOnly, limit: 120 });
      setResults(res.printers);
      setVendors(res.vendors);
      setCatalogTotal(res.catalog_total);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setSyncing(false);
    }
  }

  async function handleConfirmAdd() {
    if (!selected) return;
    setSaving(true);
    setErrorMsg(null);
    try {
      const res = await addCustomPrinter({
        catalog_id: selected.catalog_id,
        display_name: customName.trim() || selected.model_name,
        nozzle_diameter: nozzleDiameter,
        connection_mode: connectionMode,
        ip: connectionMode === 'lan' ? ip.trim() : '',
        is_multicolor: isMulticolor,
        tool_count: isMulticolor ? toolCount : 1,
      });
      onAdded(res.printer.id);
      onClose();
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-sm">
      <div className="flex max-h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-slate-700/80 bg-[#0B1120] shadow-2xl shadow-cyan-950/30">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 bg-slate-900/90 px-5 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-cyan-500/40 bg-cyan-500/15 text-cyan-300">
              <Plus className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-100">
                Catálogo Universal de Impresoras (OrcaSlicer)
              </h2>
              <p className="text-[11px] text-slate-400">
                {catalogTotal} modelos indexados · Detección automática de cama, cinemática, Q_max y multicolor
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => void handleSyncGithub()}
              disabled={syncing}
              className="flex items-center gap-1.5 rounded-lg border border-slate-700 bg-slate-800/80 px-2.5 py-1.5 text-[11px] font-medium text-slate-200 transition hover:border-cyan-500/50 hover:text-cyan-200 disabled:opacity-50"
              title="Actualizar índice desde OrcaSlicer/OrcaSlicer en GitHub"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${syncing ? 'animate-spin' : ''}`} />
              <span>{syncing ? 'Sincronizando...' : 'Sincronizar OrcaSlicer'}</span>
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
              aria-label="Cerrar"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* Barra de búsqueda y filtros */}
        <div className="flex flex-wrap items-center gap-2.5 border-b border-slate-800/80 bg-slate-900/50 px-5 py-3">
          <div className="relative min-w-[240px] flex-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Buscar por marca o modelo: ej. Bambu A1, K1 Max, Prusa MK4, Voron 2.4, Neptune 4..."
              className="w-full rounded-xl border border-slate-700 bg-slate-950/90 py-2 pr-3 pl-9 text-xs text-slate-100 placeholder-slate-500 focus:border-cyan-400 focus:outline-none"
            />
          </div>

          <select
            value={vendor}
            onChange={(e) => setVendor(e.target.value)}
            aria-label="Filtrar por marca"
            className="rounded-xl border border-slate-700 bg-slate-950/90 px-3 py-2 text-xs text-slate-200 focus:border-cyan-400 focus:outline-none"
          >
            <option value="">Todas las marcas ({vendors.length})</option>
            {vendors.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => setMulticolorOnly((v) => !v)}
            className={`flex items-center gap-1.5 rounded-xl border px-3 py-2 text-xs font-semibold transition ${
              multicolorOnly
                ? 'border-purple-400/70 bg-purple-500/20 text-purple-200'
                : 'border-slate-700 bg-slate-950/90 text-slate-300 hover:border-slate-600'
            }`}
          >
            <Palette className="h-3.5 w-3.5" />
            <span>Solo Multicolor</span>
          </button>
        </div>

        {/* Cuerpo: Lista + Tarjeta Técnica */}
        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[1.05fr_0.95fr]">
          {/* Lista de resultados */}
          <div className="min-h-0 overflow-y-auto border-r border-slate-800/80 p-3 space-y-1.5">
            {loading ? (
              <div className="flex items-center justify-center py-12 text-xs text-slate-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin text-cyan-400" />
                Buscando en el catálogo OrcaSlicer...
              </div>
            ) : results.length === 0 ? (
              <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-6 text-center text-xs text-slate-400">
                No se encontraron modelos con ese filtro. Prueba otra marca o término.
              </div>
            ) : (
              results.map((item) => {
                const isActive = selected?.catalog_id === item.catalog_id;
                const bedTxt =
                  item.bed_shape === 'circular'
                    ? `Ø${item.bed_diameter_mm ?? item.bed_width_mm}×${item.max_height_mm}`
                    : `${item.bed_width_mm}×${item.bed_depth_mm}×${item.max_height_mm}`;
                return (
                  <button
                    key={item.catalog_id}
                    type="button"
                    onClick={() => handlePickModel(item)}
                    className={`flex w-full items-center justify-between rounded-xl border px-3 py-2.5 text-left transition ${
                      isActive
                        ? 'border-cyan-400/80 bg-cyan-500/12 shadow-sm shadow-cyan-500/10'
                        : 'border-slate-800/90 bg-slate-900/55 hover:border-slate-700'
                    }`}
                  >
                    <div className="min-w-0 pr-2">
                      <div className="flex items-center gap-2">
                        <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[10px] font-semibold text-cyan-300">
                          {item.vendor}
                        </span>
                        <span className="truncate text-xs font-semibold text-slate-100">
                          {item.model_name}
                        </span>
                      </div>
                      <p className="mt-1 font-mono text-[10px] text-slate-400">
                        {bedTxt} mm · {item.gcode_flavor.toUpperCase()} · Q_max {item.estimated_q_max} mm³/s
                      </p>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      {item.capabilities.is_multicolor && (
                        <span className="rounded-full border border-purple-500/40 bg-purple-500/15 px-2 py-0.5 text-[10px] font-semibold text-purple-200">
                          {item.capabilities.tool_count}C
                        </span>
                      )}
                      {item.capabilities.is_high_speed && (
                        <span className="rounded-full border border-amber-500/40 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200">
                          HS
                        </span>
                      )}
                    </div>
                  </button>
                );
              })
            )}
          </div>

          {/* Tarjeta de Inspección Técnica y Personalización */}
          <div className="min-h-0 overflow-y-auto bg-slate-950/60 p-4">
            {selected ? (
              <div className="space-y-4">
                <div className="rounded-xl border border-slate-800 bg-slate-900/80 p-3.5">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-cyan-400">
                        {selected.vendor} · {selected.kinematics.toUpperCase()}
                      </span>
                      <h3 className="text-sm font-bold text-slate-100">{selected.model_name}</h3>
                    </div>
                    <div className="flex flex-col items-end">
                      <div
                        className={`flex h-9 w-9 items-center justify-center border border-cyan-500/50 bg-cyan-500/10 text-[9px] font-mono text-cyan-300 ${
                          selected.bed_shape === 'circular' ? 'rounded-full' : 'rounded-md'
                        }`}
                        title={`Cama ${selected.bed_shape}`}
                      >
                        {selected.bed_shape === 'circular' ? 'Ø' : '▭'}
                      </div>
                    </div>
                  </div>

                  {/* Badges técnicos */}
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    <span className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[10px] text-slate-200">
                      <Cpu className="h-3 w-3 text-cyan-400" />
                      {selected.bed_shape === 'circular'
                        ? `Ø${selected.bed_diameter_mm ?? selected.bed_width_mm}×${selected.max_height_mm} mm`
                        : `${selected.bed_width_mm}×${selected.bed_depth_mm}×${selected.max_height_mm} mm`}
                    </span>
                    <span className="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-[10px] text-emerald-300">
                      {selected.gcode_flavor.toUpperCase()} · Q_max {selected.estimated_q_max} mm³/s
                    </span>
                    <span
                      className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[10px] font-semibold ${
                        isMulticolor
                          ? 'border-purple-500/50 bg-purple-500/15 text-purple-200'
                          : 'border-slate-700 bg-slate-950 text-slate-300'
                      }`}
                    >
                      <Palette className="h-3 w-3" />
                      {isMulticolor ? `Multicolor (${toolCount} colores / AMS / CFS)` : 'Monocolor'}
                    </span>
                    {selected.capabilities.has_heated_chamber && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-orange-500/40 bg-orange-500/15 px-2 py-1 text-[10px] font-semibold text-orange-200">
                        <Flame className="h-3 w-3" />
                        Cámara Calefactada
                      </span>
                    )}
                    {selected.capabilities.is_high_speed && (
                      <span className="inline-flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/15 px-2 py-1 text-[10px] font-semibold text-amber-200">
                        <Zap className="h-3 w-3" />
                        Alta Velocidad ({selected.max_accel_mm_s2} mm/s²)
                      </span>
                    )}
                  </div>
                </div>

                {/* Personalización rápida */}
                <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-900/60 p-3.5">
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-300">
                      Nombre visible en tu granja
                    </label>
                    <input
                      type="text"
                      value={customName}
                      onChange={(e) => setCustomName(e.target.value)}
                      className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                    />
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <div>
                      <label className="mb-1 block text-[11px] font-medium text-slate-300">
                        Boquilla (mm)
                      </label>
                      <select
                        value={nozzleDiameter}
                        onChange={(e) => setNozzleDiameter(Number(e.target.value))}
                        className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs text-slate-100 focus:border-cyan-400 focus:outline-none"
                      >
                        {[0.2, 0.4, 0.6, 0.8].map((n) => (
                          <option key={n} value={n}>
                            {n.toFixed(1)} mm {selected.nozzle_diameters.includes(n) ? '✓' : ''}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div>
                      <label className="mb-1 block text-[11px] font-medium text-slate-300">
                        Sistema Multicolor
                      </label>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setIsMulticolor((v) => !v)}
                          className={`flex-1 rounded-lg border px-2 py-1.5 text-[11px] font-semibold transition ${
                            isMulticolor
                              ? 'border-purple-400/70 bg-purple-500/20 text-purple-200'
                              : 'border-slate-700 bg-slate-950 text-slate-300'
                          }`}
                        >
                          {isMulticolor ? 'Activo' : 'Desactivado'}
                        </button>
                        {isMulticolor && (
                          <input
                            type="number"
                            min={2}
                            max={16}
                            value={toolCount}
                            onChange={(e) => setToolCount(Math.max(2, Math.min(16, Number(e.target.value) || 4)))}
                            aria-label="Cantidad de canales de color"
                            className="w-14 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-center font-mono text-xs text-purple-200 focus:border-purple-400 focus:outline-none"
                          />
                        )}
                      </div>
                    </div>
                  </div>

                  <div>
                    <label className="mb-1.5 block text-[11px] font-medium text-slate-300">
                      Modo de conexión
                    </label>
                    <div className="grid grid-cols-2 gap-2">
                      <button
                        type="button"
                        onClick={() => setConnectionMode('lan')}
                        className={`flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-2 text-[11px] font-semibold transition ${
                          connectionMode === 'lan'
                            ? 'border-cyan-400/70 bg-cyan-500/15 text-cyan-200'
                            : 'border-slate-700 bg-slate-950 text-slate-400'
                        }`}
                      >
                        <Wifi className="h-3.5 w-3.5" />
                        <span>Red LAN / Klipper</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => setConnectionMode('usb_sd')}
                        className={`flex items-center justify-center gap-1.5 rounded-lg border px-2.5 py-2 text-[11px] font-semibold transition ${
                          connectionMode === 'usb_sd'
                            ? 'border-emerald-400/70 bg-emerald-500/15 text-emerald-200'
                            : 'border-slate-700 bg-slate-950 text-slate-400'
                        }`}
                      >
                        <HardDrive className="h-3.5 w-3.5" />
                        <span>Exportar .gcode USB/SD</span>
                      </button>
                    </div>
                  </div>

                  {connectionMode === 'lan' && (
                    <div>
                      <label className="mb-1 block text-[11px] font-medium text-slate-300">
                        IP LAN / Moonraker (opcional)
                      </label>
                      <input
                        type="text"
                        value={ip}
                        onChange={(e) => setIp(e.target.value)}
                        placeholder="ej. 192.168.1.55 (dejar vacío para exportar G-code)"
                        className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 font-mono text-xs text-slate-100 placeholder-slate-500 focus:border-cyan-400 focus:outline-none"
                      />
                    </div>
                  )}
                </div>

                {errorMsg && (
                  <div className="rounded-lg border border-rose-500/50 bg-rose-950/50 px-3 py-2 text-xs text-rose-200">
                    {errorMsg}
                  </div>
                )}

                <button
                  type="button"
                  onClick={() => void handleConfirmAdd()}
                  disabled={saving}
                  className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-4 py-2.5 text-xs font-bold text-slate-950 shadow-lg shadow-cyan-500/20 transition hover:brightness-110 disabled:opacity-50"
                >
                  {saving ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Check className="h-4 w-4" />
                  )}
                  <span>{saving ? 'Agregando impresora...' : 'Agregar Impresora al Taller'}</span>
                </button>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-slate-400">
                <Sparkles className="mr-2 h-4 w-4 text-cyan-400" />
                Selecciona un modelo de la lista para ver sus especificaciones técnicas.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
