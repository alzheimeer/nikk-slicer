import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Calculator,
  Check,
  Copy,
  PackagePlus,
  Paintbrush,
  Save,
  Store,
  X,
} from 'lucide-react';
import type { MaterialType, ProfileId } from '../services/api';

export interface QuoteInitialData {
  modelName?: string;
  printerProfileId?: ProfileId;
  printerName?: string;
  material?: MaterialType;
  hours?: number;
  minutes?: number;
  grams?: number;
  filamentPricePerKg?: number;
  energyRateKwh?: number;
}

export interface QuoteCalculatorModalProps {
  open: boolean;
  onClose: () => void;
  initialData?: QuoteInitialData | null;
}

export interface VolumeDiscountTier {
  id: string;
  minQty: number;
  maxQty: number | null;
  label: string;
  pct: number;
}

export const DEFAULT_DISCOUNT_TIERS: VolumeDiscountTier[] = [
  { id: 't1', minQty: 1, maxQty: 9, label: '1–9', pct: 0 },
  { id: 't2', minQty: 10, maxQty: 24, label: '10–24', pct: 10 },
  { id: 't3', minQty: 25, maxQty: 49, label: '25–49', pct: 15 },
  { id: 't4', minQty: 50, maxQty: 99, label: '50–99', pct: 20 },
  { id: 't5', minQty: 100, maxQty: null, label: '100+', pct: 25 },
];

export interface WorkshopPreset {
  filamentPricePerKg: number;
  energyRateKwh: number;
  machineLifeHours: number;
  sparePartsFundCop: number;
  laborHourlyRate: number;
  volumeDiscountTiers?: VolumeDiscountTier[];
}

export const PRESET_STORAGE_KEY = 'nikk_slicer_quote_preset_v1';

export const DEFAULT_PRESET: WorkshopPreset = {
  filamentPricePerKg: 100000,
  energyRateKwh: 900,
  machineLifeHours: 4320,
  sparePartsFundCop: 600000,
  laborHourlyRate: 15000,
};

export const PRINTER_WATTS: Record<ProfileId, { label: string; watts: number }> = {
  flsun_t1_pro: { label: 'FLSUN T1 Pro (180W)', watts: 180 },
  flsun_v400: { label: 'FLSUN V400 (160W)', watts: 160 },
  creator5_pro: { label: 'FlashForge Creator 5 Pro (150W)', watts: 150 },
  flsun_sr: { label: 'FLSUN Super Racer (130W)', watts: 130 },
  ender3_s1_pro: { label: 'Creality Ender 3 S1 Pro (115W)', watts: 115 },
};

const MULTIPLIERS: Array<{ value: number; label: string; hint: string }> = [
  { value: 2, label: '×2', hint: 'Mayorista' },
  { value: 2.5, label: '×2.5', hint: 'Volumen' },
  { value: 3, label: '×3', hint: 'Directo' },
  { value: 3.5, label: '×3.5', hint: 'Intermedio' },
  { value: 4, label: '×4', hint: 'Minorista' },
  { value: 5, label: '×5', hint: 'Llaveros' },
];

export function loadWorkshopPreset(): WorkshopPreset {
  try {
    const raw = localStorage.getItem(PRESET_STORAGE_KEY);
    if (!raw) return { ...DEFAULT_PRESET, volumeDiscountTiers: DEFAULT_DISCOUNT_TIERS };
    const parsed = JSON.parse(raw) as Partial<WorkshopPreset>;
    const tiers =
      Array.isArray(parsed.volumeDiscountTiers) && parsed.volumeDiscountTiers.length === DEFAULT_DISCOUNT_TIERS.length
        ? DEFAULT_DISCOUNT_TIERS.map((def, idx) => {
          const saved = parsed.volumeDiscountTiers?.[idx];
          const pct = Number(saved?.pct);
          return {
            ...def,
            pct: Number.isFinite(pct) ? Math.min(50, Math.max(0, pct)) : def.pct,
          };
        })
        : DEFAULT_DISCOUNT_TIERS;
    return {
      filamentPricePerKg: Number(parsed.filamentPricePerKg) || DEFAULT_PRESET.filamentPricePerKg,
      energyRateKwh: Number(parsed.energyRateKwh) || DEFAULT_PRESET.energyRateKwh,
      machineLifeHours: Number(parsed.machineLifeHours) || DEFAULT_PRESET.machineLifeHours,
      sparePartsFundCop: Number(parsed.sparePartsFundCop) || DEFAULT_PRESET.sparePartsFundCop,
      laborHourlyRate: Number(parsed.laborHourlyRate) || DEFAULT_PRESET.laborHourlyRate,
      volumeDiscountTiers: tiers,
    };
  } catch {
    return { ...DEFAULT_PRESET, volumeDiscountTiers: DEFAULT_DISCOUNT_TIERS };
  }
}

function getDiscountTierForQty(tiers: VolumeDiscountTier[], qty: number): VolumeDiscountTier {
  const q = Math.max(1, Math.round(qty));
  return (
    tiers.find((t) => q >= t.minQty && (t.maxQty === null || q <= t.maxQty)) ??
    tiers[0]
  );
}

function formatCop(amount: number): string {
  return `$${Math.round(amount).toLocaleString('es-CO')} COP`;
}

export function QuoteCalculatorModal({
  open,
  onClose,
  initialData,
}: QuoteCalculatorModalProps) {
  const [preset, setPreset] = useState<WorkshopPreset>(loadWorkshopPreset);

  const [pieceName, setPieceName] = useState('Pieza 3D Personalizada');
  const [profileId, setProfileId] = useState<ProfileId>('flsun_t1_pro');
  const [material, setMaterial] = useState<MaterialType>('pla');
  const [hours, setHours] = useState(2);
  const [minutes, setMinutes] = useState(30);
  const [grams, setGrams] = useState(45);

  const [filamentPricePerKg, setFilamentPricePerKg] = useState(preset.filamentPricePerKg);
  const [energyRateKwh, setEnergyRateKwh] = useState(preset.energyRateKwh);
  const [machineLifeHours, setMachineLifeHours] = useState(preset.machineLifeHours);
  const [sparePartsFundCop, setSparePartsFundCop] = useState(preset.sparePartsFundCop);
  const [errorMarginPct, setErrorMarginPct] = useState(5);

  // Switch A: Insumos Extra
  const [extraEnabled, setExtraEnabled] = useState(false);
  const [extraCost, setExtraCost] = useState(2500);
  const [extraNote, setExtraNote] = useState('Argolla llavero / imanes');

  // Switch B: Pintura y Mano de Obra
  const [paintEnabled, setPaintEnabled] = useState(false);
  const [paintDirectMode, setPaintDirectMode] = useState(false);
  const [laborHours, setLaborHours] = useState(1);
  const [laborHourlyRate, setLaborHourlyRate] = useState(preset.laborHourlyRate);
  const [paintSuppliesCost, setPaintSuppliesCost] = useState(5000);
  const [paintGlobalCost, setPaintGlobalCost] = useState(20000);

  // Switch C: Plataforma / Comisiones
  const [platformEnabled, setPlatformEnabled] = useState(false);
  const [platformPct, setPlatformPct] = useState(17.5);

  // Multiplicador, cantidad y descuento por volumen sobre ganancia neta (0-50%)
  const [multiplier, setMultiplier] = useState(3);
  const [quantity, setQuantity] = useState(1);
  const [discountTiers, setDiscountTiers] = useState<VolumeDiscountTier[]>(
    () => preset.volumeDiscountTiers ?? DEFAULT_DISCOUNT_TIERS,
  );
  const [profitDiscountPct, setProfitDiscountPct] = useState(0);

  const activeTier = useMemo(
    () => getDiscountTierForQty(discountTiers, quantity),
    [discountTiers, quantity],
  );

  useEffect(() => {
    setProfitDiscountPct(activeTier.pct);
  }, [activeTier]);

  const [copiedMsg, setCopiedMsg] = useState(false);
  const [savedPresetMsg, setSavedPresetMsg] = useState(false);

  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (!open) {
      wasOpenRef.current = false;
      return;
    }
    if (wasOpenRef.current) return;
    wasOpenRef.current = true;
    const saved = loadWorkshopPreset();
    setPreset(saved);
    setEnergyRateKwh(initialData?.energyRateKwh ?? saved.energyRateKwh);
    setFilamentPricePerKg(initialData?.filamentPricePerKg ?? saved.filamentPricePerKg);
    setMachineLifeHours(saved.machineLifeHours);
    setSparePartsFundCop(saved.sparePartsFundCop);
    setLaborHourlyRate(saved.laborHourlyRate);
    setDiscountTiers(saved.volumeDiscountTiers ?? DEFAULT_DISCOUNT_TIERS);

    if (initialData) {
      if (initialData.modelName) {
        setPieceName(initialData.modelName.replace(/\.(stl|3mf|gcode)$/i, ''));
      }
      if (initialData.printerProfileId) setProfileId(initialData.printerProfileId);
      if (initialData.material) {
        setMaterial(initialData.material);
        setErrorMarginPct(initialData.material === 'pla' ? 5 : 10);
      }
      if (typeof initialData.hours === 'number') setHours(Math.max(0, Math.floor(initialData.hours)));
      if (typeof initialData.minutes === 'number') setMinutes(Math.max(0, Math.min(59, Math.round(initialData.minutes))));
      if (typeof initialData.grams === 'number') setGrams(Math.max(0, Number(initialData.grams.toFixed(1))));
    }
    setCopiedMsg(false);
    setSavedPresetMsg(false);
  }, [open, initialData]);

  const calc = useMemo(() => {
    const totalHours = Math.max(0.01, hours + minutes / 60);
    const watts = PRINTER_WATTS[profileId]?.watts ?? 150;
    const materialCostUnit = (grams / 1000) * filamentPricePerKg;
    const energyCostUnit = (watts / 1000) * totalHours * energyRateKwh;
    const wearPerHour = machineLifeHours > 0 ? sparePartsFundCop / machineLifeHours : 0;
    const wearCostUnit = wearPerHour * totalHours;

    const subBaseUnit = materialCostUnit + energyCostUnit + wearCostUnit;
    const errorCostUnit = subBaseUnit * (errorMarginPct / 100);
    const extraCostUnit = extraEnabled ? Math.max(0, extraCost) : 0;
    const paintCostUnit = paintEnabled
      ? paintDirectMode
        ? Math.max(0, paintGlobalCost)
        : Math.max(0, laborHours * laborHourlyRate + paintSuppliesCost)
      : 0;

    const realBreakEvenUnit =
      subBaseUnit + errorCostUnit + extraCostUnit + paintCostUnit;

    const qty = Math.max(1, Math.round(quantity));
    const baseClientPriceUnit = realBreakEvenUnit * Math.max(1, multiplier);
    const grossProfitUnit = Math.max(0, baseClientPriceUnit - realBreakEvenUnit);
    const discountRatio = Math.min(50, Math.max(0, profitDiscountPct)) / 100;
    const discountPerUnit = grossProfitUnit * discountRatio;
    const netProfitUnit = grossProfitUnit - discountPerUnit;
    const clientPriceUnit = realBreakEvenUnit + netProfitUnit;
    const clientPriceTotal = clientPriceUnit * qty;
    const breakEvenTotal = realBreakEvenUnit * qty;
    const grossProfitTotal = grossProfitUnit * qty;
    const discountTotal = discountPerUnit * qty;
    const netProfitTotal = netProfitUnit * qty;

    const comm = Math.min(45, Math.max(0, platformPct)) / 100;
    const platformPriceTotal =
      platformEnabled && comm < 0.95 ? clientPriceTotal / (1 - comm) : clientPriceTotal;

    return {
      watts,
      totalHours,
      wearPerHour,
      materialCostUnit,
      energyCostUnit,
      wearCostUnit,
      errorCostUnit,
      extraCostUnit,
      paintCostUnit,
      realBreakEvenUnit,
      breakEvenTotal,
      clientPriceUnit,
      clientPriceTotal,
      grossProfitTotal,
      discountTotal,
      netProfitTotal,
      platformPriceTotal,
      qty,
      discountPct: Math.min(50, Math.max(0, profitDiscountPct)),
    };
  }, [
    hours,
    minutes,
    profileId,
    grams,
    filamentPricePerKg,
    energyRateKwh,
    machineLifeHours,
    sparePartsFundCop,
    errorMarginPct,
    extraEnabled,
    extraCost,
    paintEnabled,
    paintDirectMode,
    laborHours,
    laborHourlyRate,
    paintSuppliesCost,
    paintGlobalCost,
    multiplier,
    quantity,
    profitDiscountPct,
    platformEnabled,
    platformPct,
  ]);

  if (!open) return null;

  const handleSaveWorkshopPreset = () => {
    const next: WorkshopPreset = {
      filamentPricePerKg,
      energyRateKwh,
      machineLifeHours,
      sparePartsFundCop,
      laborHourlyRate,
      volumeDiscountTiers: discountTiers,
    };
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(next));
    setPreset(next);
    window.dispatchEvent(new CustomEvent('nikk:quote-preset-updated'));
    setSavedPresetMsg(true);
    window.setTimeout(() => setSavedPresetMsg(false), 2200);
  };

  const handleCopyWhatsApp = async () => {
    const finishes: string[] = [];
    if (extraEnabled && extraNote.trim()) finishes.push(extraNote.trim());
    if (paintEnabled) finishes.push('Pintura y acabado artesanal');
    const finishText = finishes.length > 0 ? finishes.join(' + ') : 'Acabado limpio de impresión 3D';
    const estHoursText = `${hours}h ${minutes}m`;
    const totalToShare = platformEnabled ? calc.platformPriceTotal : calc.clientPriceTotal;
    const unitToShare = totalToShare / calc.qty;

    const msg = [
      `Hola, te comparto tu cotización de impresión 3D:`,
      `*Pieza:* ${pieceName || 'Modelo 3D'}`,
      `*Material:* ${material.toUpperCase()} (${grams} g)`,
      `*Cantidad:* ${calc.qty} unidad(es)`,
      ...(calc.qty > 1 ? [`*Valor Unitario:* ${formatCop(unitToShare)}`] : []),
      ...(calc.discountPct > 0 ? [`*Descuento por volumen aplicado:* ${calc.discountPct}% sobre margen`] : []),
      `*Acabados:* ${finishText}`,
      `*Tiempo estimado de fabricación:* ${estHoursText}`,
      `*Valor Total:* ${formatCop(totalToShare)}`,
    ].join('\n');

    try {
      await navigator.clipboard.writeText(msg);
      setCopiedMsg(true);
      window.setTimeout(() => setCopiedMsg(false), 2200);
    } catch {
      // Ignorar si portapapeles no disponible
    }
  };

  return (
    <div className="fixed inset-0 z-[9995] flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-md">
      <div className="flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-2xl border border-cyan-500/35 bg-slate-900 shadow-[0_0_50px_rgba(6,182,212,0.2)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-cyan-500/15 text-cyan-300">
              <Calculator className="h-4 w-4" />
            </span>
            <div>
              <h2 className="text-sm font-bold text-white">
                Calculadora Comercial de Cotización 3D
              </h2>
              <p className="text-[11px] text-slate-400">
                Costos reales de taller (Enel Bogotá, desgaste, insumos y margen) en COP$
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 bg-slate-800 p-1.5 text-slate-300 hover:bg-slate-700"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Body 2 columnas */}
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-y-auto p-5 lg:grid-cols-2">
          {/* Columna Izquierda: Costos Base y Opciones */}
          <div className="space-y-3">
            {/* Bloque 1: Datos de Pieza + Costos Base */}
            <div className="space-y-2.5 rounded-xl border border-slate-800 bg-slate-950/70 p-3.5">
              <p className="text-xs font-bold uppercase tracking-wide text-cyan-300">
                1. Costos Base de Producción
              </p>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="col-span-2">
                  <label className="mb-0.5 block text-[10px] text-slate-400">Nombre de pieza / proyecto</label>
                  <input
                    type="text"
                    value={pieceName}
                    onChange={(e) => setPieceName(e.target.value)}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1 text-xs text-white outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Impresora (Watts)</label>
                  <select
                    value={profileId}
                    onChange={(e) => setProfileId(e.target.value as ProfileId)}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white outline-none focus:border-cyan-400"
                  >
                    {(Object.keys(PRINTER_WATTS) as ProfileId[]).map((pid) => (
                      <option key={pid} value={pid}>
                        {PRINTER_WATTS[pid].label}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Material</label>
                  <select
                    value={material}
                    onChange={(e) => {
                      const nextMat = e.target.value as MaterialType;
                      setMaterial(nextMat);
                      setErrorMarginPct(nextMat === 'pla' ? 5 : 10);
                    }}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white outline-none focus:border-cyan-400"
                  >
                    <option value="pla">PLA (Error 5%)</option>
                    <option value="petg">PETG (Error 10%)</option>
                    <option value="abs">ABS (Error 10%)</option>
                    <option value="tpu">TPU (Error 10%)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2 text-xs">
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Horas</label>
                  <input
                    type="number"
                    min={0}
                    value={hours}
                    onChange={(e) => setHours(Math.max(0, Number(e.target.value) || 0))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Minutos</label>
                  <input
                    type="number"
                    min={0}
                    max={59}
                    value={minutes}
                    onChange={(e) => setMinutes(Math.max(0, Math.min(59, Number(e.target.value) || 0)))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Gramos (g)</label>
                  <input
                    type="number"
                    min={0}
                    step={0.5}
                    value={grams}
                    onChange={(e) => setGrams(Math.max(0, Number(e.target.value) || 0))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Filamento (COP$/kg)</label>
                  <input
                    type="number"
                    min={0}
                    step={1000}
                    value={filamentPricePerKg}
                    onChange={(e) => setFilamentPricePerKg(Math.max(0, Number(e.target.value) || 0))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Tarifa Enel (COP$/kWh)</label>
                  <input
                    type="number"
                    min={0}
                    step={50}
                    value={energyRateKwh}
                    onChange={(e) => setEnergyRateKwh(Math.max(0, Number(e.target.value) || 0))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Vida útil máq. (h)</label>
                  <input
                    type="number"
                    min={100}
                    step={100}
                    value={machineLifeHours}
                    onChange={(e) => setMachineLifeHours(Math.max(100, Number(e.target.value) || 4320))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Fondo repuestos (COP$)</label>
                  <input
                    type="number"
                    min={0}
                    step={10000}
                    value={sparePartsFundCop}
                    onChange={(e) => setSparePartsFundCop(Math.max(0, Number(e.target.value) || 0))}
                    className="w-full rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-xs text-white"
                  />
                </div>
              </div>

              <div className="flex items-center justify-between gap-2 pt-0.5 text-[11px]">
                <span className="text-slate-400">
                  Desgaste: <strong className="font-mono text-slate-200">{formatCop(calc.wearPerHour)}/h</strong>
                </span>
                <label className="flex items-center gap-1.5 text-slate-300">
                  <span>Margen error (%):</span>
                  <input
                    type="number"
                    min={0}
                    max={50}
                    value={errorMarginPct}
                    onChange={(e) => setErrorMarginPct(Math.max(0, Math.min(50, Number(e.target.value) || 0)))}
                    className="w-14 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-center font-mono text-xs text-white"
                  />
                </label>
              </div>
            </div>

            {/* Bloque 2: Switches Adicionales */}
            <div className="space-y-2 rounded-xl border border-slate-800 bg-slate-950/70 p-3.5">
              <p className="text-xs font-bold uppercase tracking-wide text-violet-300">
                2. Opciones Adicionales
              </p>

              {/* Switch A: Insumos Extra */}
              <div className="rounded-lg border border-slate-800 bg-slate-900/75 p-2.5">
                <label className="flex cursor-pointer items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-100">
                    <PackagePlus className="h-3.5 w-3.5 text-cyan-400" />
                    Insumos Extra (Imanes, argollas, empaque)
                  </span>
                  <input
                    type="checkbox"
                    checked={extraEnabled}
                    onChange={(e) => setExtraEnabled(e.target.checked)}
                    className="h-4 w-4 accent-cyan-500"
                  />
                </label>
                {extraEnabled && (
                  <div className="mt-2 space-y-1.5 border-t border-slate-800 pt-2">
                    <div className="flex flex-wrap gap-1">
                      {[
                        { label: 'Imanes neodimio', cost: 4000 },
                        { label: 'Argolla llavero', cost: 1200 },
                        { label: 'Insertos roscados', cost: 3000 },
                        { label: 'Caja / empaque', cost: 2500 },
                      ].map((chip) => (
                        <button
                          key={chip.label}
                          type="button"
                          onClick={() => {
                            setExtraNote(chip.label);
                            setExtraCost(chip.cost);
                          }}
                          className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[9px] text-slate-300 hover:border-cyan-400 hover:text-cyan-200"
                        >
                          {chip.label}
                        </button>
                      ))}
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      <input
                        type="number"
                        min={0}
                        step={500}
                        value={extraCost}
                        onChange={(e) => setExtraCost(Math.max(0, Number(e.target.value) || 0))}
                        placeholder="Costo COP$"
                        className="rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-white"
                      />
                      <input
                        type="text"
                        value={extraNote}
                        onChange={(e) => setExtraNote(e.target.value)}
                        placeholder="Nota corta..."
                        className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white"
                      />
                    </div>
                  </div>
                )}
              </div>

              {/* Switch B: Pintura y Mano de Obra */}
              <div className="rounded-lg border border-slate-800 bg-slate-900/75 p-2.5">
                <label className="flex cursor-pointer items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-100">
                    <Paintbrush className="h-3.5 w-3.5 text-amber-400" />
                    Pintura y Acabado Post-Procesado
                  </span>
                  <input
                    type="checkbox"
                    checked={paintEnabled}
                    onChange={(e) => setPaintEnabled(e.target.checked)}
                    className="h-4 w-4 accent-amber-500"
                  />
                </label>
                {paintEnabled && (
                  <div className="mt-2 space-y-2 border-t border-slate-800 pt-2 text-xs">
                    <label className="flex items-center gap-1.5 text-[10px] text-slate-300">
                      <input
                        type="checkbox"
                        checked={paintDirectMode}
                        onChange={(e) => setPaintDirectMode(e.target.checked)}
                        className="h-3.5 w-3.5 accent-amber-500"
                      />
                      Ingresar monto global único
                    </label>
                    {paintDirectMode ? (
                      <div>
                        <label className="mb-0.5 block text-[10px] text-slate-400">
                          Valor total pintura + mano de obra (COP$)
                        </label>
                        <input
                          type="number"
                          min={0}
                          step={1000}
                          value={paintGlobalCost}
                          onChange={(e) => setPaintGlobalCost(Math.max(0, Number(e.target.value) || 0))}
                          className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-white"
                        />
                      </div>
                    ) : (
                      <div className="grid grid-cols-3 gap-1.5">
                        <div>
                          <label className="mb-0.5 block text-[10px] text-slate-400">Horas</label>
                          <input
                            type="number"
                            min={0}
                            step={0.5}
                            value={laborHours}
                            onChange={(e) => setLaborHours(Math.max(0, Number(e.target.value) || 0))}
                            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-white"
                          />
                        </div>
                        <div>
                          <label className="mb-0.5 block text-[10px] text-slate-400">Hora (COP$)</label>
                          <input
                            type="number"
                            min={0}
                            step={1000}
                            value={laborHourlyRate}
                            onChange={(e) => setLaborHourlyRate(Math.max(0, Number(e.target.value) || 0))}
                            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-white"
                          />
                        </div>
                        <div>
                          <label className="mb-0.5 block text-[10px] text-slate-400">Pinturas ($)</label>
                          <input
                            type="number"
                            min={0}
                            step={1000}
                            value={paintSuppliesCost}
                            onChange={(e) => setPaintSuppliesCost(Math.max(0, Number(e.target.value) || 0))}
                            className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 font-mono text-xs text-white"
                          />
                        </div>
                      </div>
                    )}
                  </div>
                )}
              </div>

              {/* Switch C: Plataforma / Comisiones */}
              <div className="rounded-lg border border-slate-800 bg-slate-900/75 p-2.5">
                <label className="flex cursor-pointer items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-xs font-semibold text-slate-100">
                    <Store className="h-3.5 w-3.5 text-emerald-400" />
                    Venta en Plataforma / Comisiones
                  </span>
                  <input
                    type="checkbox"
                    checked={platformEnabled}
                    onChange={(e) => setPlatformEnabled(e.target.checked)}
                    className="h-4 w-4 accent-emerald-500"
                  />
                </label>
                {platformEnabled && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 border-t border-slate-800 pt-2 text-[10px]">
                    <button
                      type="button"
                      onClick={() => setPlatformPct(17.5)}
                      className={`rounded border px-2 py-1 font-semibold ${platformPct === 17.5
                        ? 'border-emerald-500 bg-emerald-500/20 text-emerald-200'
                        : 'border-slate-700 bg-slate-950 text-slate-300'
                        }`}
                    >
                      MercadoLibre (17.5%)
                    </button>
                    <button
                      type="button"
                      onClick={() => setPlatformPct(3.5)}
                      className={`rounded border px-2 py-1 font-semibold ${platformPct === 3.5
                        ? 'border-emerald-500 bg-emerald-500/20 text-emerald-200'
                        : 'border-slate-700 bg-slate-950 text-slate-300'
                        }`}
                    >
                      Datafono / Link (3.5%)
                    </button>
                    <input
                      type="number"
                      min={0}
                      max={45}
                      step={0.5}
                      value={platformPct}
                      onChange={(e) => setPlatformPct(Math.max(0, Math.min(45, Number(e.target.value) || 0)))}
                      className="w-16 rounded border border-slate-700 bg-slate-950 px-1.5 py-1 text-center font-mono text-white"
                    />
                    <span className="text-slate-400">%</span>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Columna Derecha: Multiplicadores y Resultado Final */}
          <div className="flex flex-col justify-between space-y-3">
            <div className="space-y-3 rounded-xl border border-slate-800 bg-slate-950/70 p-3.5">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-bold uppercase tracking-wide text-emerald-300">
                  3. Margen y Precio Final
                </p>
                <label className="flex items-center gap-1.5 text-[11px] text-slate-300">
                  <span>Unidades:</span>
                  <input
                    type="number"
                    min={1}
                    value={quantity}
                    onChange={(e) => setQuantity(Math.max(1, Number(e.target.value) || 1))}
                    className="w-14 rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-center font-mono text-xs text-white"
                  />
                </label>
              </div>

              {/* Botones rápidos de multiplicador */}
              <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
                {MULTIPLIERS.map((m) => (
                  <button
                    key={m.value}
                    type="button"
                    onClick={() => setMultiplier(m.value)}
                    className={`flex flex-col items-center rounded-lg border py-1.5 text-center transition ${multiplier === m.value
                      ? 'border-cyan-500 bg-cyan-500/20 text-cyan-100'
                      : 'border-slate-800 bg-slate-900 text-slate-300 hover:border-slate-700'
                      }`}
                  >
                    <span className="font-mono text-xs font-bold">{m.label}</span>
                    <span className="text-[9px] text-slate-400">{m.hint}</span>
                  </button>
                ))}
              </div>

              <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-1.5 text-xs">
                <span className="text-slate-300">Multiplicador personalizado:</span>
                <input
                  type="number"
                  min={1}
                  step={0.1}
                  value={multiplier}
                  onChange={(e) => setMultiplier(Math.max(1, Number(e.target.value) || 1))}
                  className="w-20 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-right font-mono text-xs font-bold text-cyan-300"
                />
              </div>

              {/* Descuento por cantidad de unidades (solo reduce la ganancia neta, 0-50%) */}
              <div className="space-y-1.5 rounded-lg border border-slate-800 bg-slate-900/70 px-3 py-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <span className="font-medium text-slate-200">
                      Descuento por volumen (solo sobre ganancia)
                    </span>
                    <p className="text-[10px] text-slate-400">
                      Tramo activo para {calc.qty} ud(s): <span className="font-semibold text-amber-300">{activeTier.label}</span> · editable 0%–50%
                    </p>
                  </div>
                  <div className="flex items-center gap-1">
                    <input
                      type="number"
                      min={0}
                      max={50}
                      step={1}
                      value={profitDiscountPct}
                      onChange={(e) =>
                        setProfitDiscountPct(Math.min(50, Math.max(0, Number(e.target.value) || 0)))
                      }
                      className="w-16 rounded border border-slate-700 bg-slate-950 px-2 py-0.5 text-right font-mono text-xs font-bold text-amber-300"
                    />
                    <span className="font-mono text-xs text-slate-400">%</span>
                  </div>
                </div>
                <div className="grid grid-cols-5 gap-1">
                  {discountTiers.map((tier) => {
                    const isInRange = tier.id === activeTier.id;
                    return (
                      <div
                        key={tier.id}
                        className={`flex flex-col items-center gap-1 rounded-md border px-1 py-1 text-center transition ${isInRange
                          ? 'border-amber-500/70 bg-amber-500/15 text-amber-200'
                          : 'border-slate-800/80 bg-slate-950/60 text-slate-500 opacity-60'
                          }`}
                        title={
                          isInRange
                            ? `Tramo activo para ${calc.qty} unidad(es)`
                            : `Se activa automáticamente con ${tier.label} unidades`
                        }
                      >
                        <button
                          type="button"
                          disabled={!isInRange}
                          onClick={() => setProfitDiscountPct(tier.pct)}
                          className="w-full text-[9px] font-semibold disabled:cursor-not-allowed"
                        >
                          {tier.label} uds
                        </button>
                        <div className="flex items-center justify-center gap-0.5">
                          <input
                            type="number"
                            min={0}
                            max={50}
                            step={1}
                            value={tier.pct}
                            onChange={(e) => {
                              const nextPct = Math.min(50, Math.max(0, Number(e.target.value) || 0));
                              setDiscountTiers((prev) =>
                                prev.map((x) => (x.id === tier.id ? { ...x, pct: nextPct } : x)),
                              );
                            }}
                            className={`w-10 rounded border px-1 py-0.5 text-center font-mono text-[10px] font-bold focus:outline-none ${isInRange
                              ? 'border-amber-500/60 bg-slate-950 text-amber-200'
                              : 'border-slate-800 bg-slate-900 text-slate-400'
                              }`}
                          />
                          <span className="text-[9px]">%</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Desglose en tiempo real */}
              <div className="space-y-1.5 rounded-xl border border-slate-800 bg-slate-900/80 p-3 text-xs">
                <div className="flex justify-between text-slate-300">
                  <span>Material (Filamento · {grams} g)</span>
                  <span className="font-mono">{formatCop(calc.materialCostUnit * calc.qty)}</span>
                </div>
                <div className="flex justify-between text-slate-300">
                  <span>Energía Eléctrica (Enel · {calc.watts}W)</span>
                  <span className="font-mono">{formatCop(calc.energyCostUnit * calc.qty)}</span>
                </div>
                <div className="flex justify-between text-slate-300">
                  <span>Desgaste de Máquina</span>
                  <span className="font-mono">{formatCop(calc.wearCostUnit * calc.qty)}</span>
                </div>
                <div className="flex justify-between text-slate-300">
                  <span>Margen de Error ({errorMarginPct}%)</span>
                  <span className="font-mono">{formatCop(calc.errorCostUnit * calc.qty)}</span>
                </div>
                {extraEnabled && (
                  <div className="flex justify-between text-cyan-200">
                    <span>Insumos Extra</span>
                    <span className="font-mono">{formatCop(calc.extraCostUnit * calc.qty)}</span>
                  </div>
                )}
                {paintEnabled && (
                  <div className="flex justify-between text-amber-200">
                    <span>Pintura y Mano de Obra</span>
                    <span className="font-mono">{formatCop(calc.paintCostUnit * calc.qty)}</span>
                  </div>
                )}
                <div className="flex justify-between border-t border-slate-800 pt-1.5 font-semibold text-slate-200">
                  <span>Costo Real Total (Punto de Equilibrio)</span>
                  <span className="font-mono">{formatCop(calc.breakEvenTotal)}</span>
                </div>
              </div>

              {/* Resultado Final */}
              <div className="space-y-2 rounded-xl border border-emerald-500/40 bg-gradient-to-br from-emerald-950/40 to-cyan-950/30 p-3.5">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-bold uppercase text-emerald-200">
                    Total a Cobrar al Cliente
                  </span>
                  <span className="font-mono text-xl font-extrabold text-white">
                    {formatCop(calc.clientPriceTotal)}
                  </span>
                </div>
                {calc.qty > 1 && (
                  <div className="flex items-center justify-between text-[11px] text-cyan-200">
                    <span>Precio unitario ({calc.qty} uds):</span>
                    <span className="font-mono font-semibold">{formatCop(calc.clientPriceUnit)}</span>
                  </div>
                )}
                {calc.discountPct > 0 && (
                  <div className="flex items-center justify-between text-[11px] text-amber-300">
                    <span>Descuento aplicado ({calc.discountPct}% s/ ganancia):</span>
                    <span className="font-mono font-semibold">-{formatCop(calc.discountTotal)}</span>
                  </div>
                )}
                <div className="flex items-center justify-between text-xs">
                  <span className="text-slate-300">Ganancia Neta Estimada:</span>
                  <span className="font-mono font-bold text-emerald-300">
                    {formatCop(calc.netProfitTotal)}
                  </span>
                </div>
                {platformEnabled && (
                  <div className="flex items-center justify-between border-t border-emerald-500/25 pt-2 text-xs">
                    <span className="font-semibold text-amber-200">
                      Precio Sugerido Plataforma ({platformPct}%):
                    </span>
                    <span className="font-mono text-sm font-bold text-amber-200">
                      {formatCop(calc.platformPriceTotal)}
                    </span>
                  </div>
                )}
              </div>
            </div>

            {/* Acciones rápidas al pie */}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              <button
                type="button"
                onClick={handleCopyWhatsApp}
                className="flex items-center justify-center gap-1.5 rounded-xl border border-emerald-500/50 bg-emerald-500/20 px-3 py-2.5 text-xs font-semibold text-emerald-100 hover:bg-emerald-500/30"
              >
                {copiedMsg ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                {copiedMsg ? '¡Cotización copiada!' : 'Copiar Cotización para WhatsApp'}
              </button>
              <button
                type="button"
                onClick={handleSaveWorkshopPreset}
                className="flex items-center justify-center gap-1.5 rounded-xl border border-cyan-500/45 bg-cyan-500/15 px-3 py-2.5 text-xs font-semibold text-cyan-100 hover:bg-cyan-500/25"
              >
                {savedPresetMsg ? <Check className="h-4 w-4" /> : <Save className="h-4 w-4" />}
                {savedPresetMsg ? '¡Preset guardado!' : 'Guardar como Preset de Taller'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
