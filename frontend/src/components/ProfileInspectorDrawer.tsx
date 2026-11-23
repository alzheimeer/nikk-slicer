import { useEffect, useMemo, useState, type ReactNode } from 'react';
import {
  CheckCircle2,
  Flame,
  Layers,
  Palette,
  RefreshCw,
  Search,
  Settings2,
  Shield,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  X,
  Zap,
} from 'lucide-react';
import { useI18n } from '../i18n/I18nContext';
import type { SlicedProfileFilament, SlicedProfileSnapshot } from '../services/api';

type InspectorTab =
  | 'quality'
  | 'strength'
  | 'speed'
  | 'support'
  | 'multimaterial'
  | 'others'
  | 'filaments';

interface ProfileInspectorDrawerProps {
  open: boolean;
  onClose: () => void;
  snapshot: SlicedProfileSnapshot;
  projectTitle: string;
  isSlicing: boolean;
  onApplyAndReslice: (overrides: Record<string, unknown>) => Promise<void> | void;
}

type FieldInputType = 'number' | 'text' | 'boolean' | 'select' | 'readonly';

interface FieldSpec {
  tab: Exclude<InspectorTab, 'filaments'>;
  key: string;
  type: FieldInputType;
  step?: number;
  options?: string[];
}

const SECTION_FIELDS: FieldSpec[] = [
  // Calidad
  { tab: 'quality', key: 'layer_height', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'initial_layer_height', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'line_width', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'outer_wall_line_width', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'inner_wall_line_width', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'top_surface_line_width', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'infill_line_width', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'support_line_width', type: 'number', step: 0.02 },
  { tab: 'quality', key: 'wall_generator', type: 'select', options: ['arachne', 'classic'] },
  { tab: 'quality', key: 'seam_position', type: 'select', options: ['aligned', 'nearest', 'back', 'random'] },
  { tab: 'quality', key: 'ironing_type', type: 'select', options: ['no ironing', 'topmost', 'top', 'all'] },
  { tab: 'quality', key: 'top_surface_pattern', type: 'select', options: ['monotonicline', 'monotonic', 'rectilinear', 'concentric'] },
  // Fuerza
  { tab: 'strength', key: 'wall_loops', type: 'number', step: 1 },
  { tab: 'strength', key: 'top_shell_layers', type: 'number', step: 1 },
  { tab: 'strength', key: 'bottom_shell_layers', type: 'number', step: 1 },
  { tab: 'strength', key: 'sparse_infill_density', type: 'text' },
  { tab: 'strength', key: 'sparse_infill_pattern', type: 'select', options: ['gyroid', 'grid', 'rectilinear', 'cubic', 'triangles', 'honeycomb'] },
  { tab: 'strength', key: 'infill_wall_overlap', type: 'text' },
  // Velocidad
  { tab: 'speed', key: 'outer_wall_speed', type: 'number', step: 5 },
  { tab: 'speed', key: 'inner_wall_speed', type: 'number', step: 5 },
  { tab: 'speed', key: 'initial_layer_speed', type: 'number', step: 5 },
  { tab: 'speed', key: 'sparse_infill_speed', type: 'number', step: 10 },
  { tab: 'speed', key: 'top_surface_speed', type: 'number', step: 5 },
  { tab: 'speed', key: 'overhang_speed', type: 'number', step: 5 },
  { tab: 'speed', key: 'overhang_1_4_speed', type: 'readonly' },
  { tab: 'speed', key: 'overhang_2_4_speed', type: 'readonly' },
  { tab: 'speed', key: 'overhang_3_4_speed', type: 'readonly' },
  { tab: 'speed', key: 'overhang_4_4_speed', type: 'readonly' },
  { tab: 'speed', key: 'bridge_speed', type: 'number', step: 5 },
  { tab: 'speed', key: 'travel_speed', type: 'number', step: 10 },
  { tab: 'speed', key: 'max_volumetric_speed_qmax', type: 'readonly' },
  { tab: 'speed', key: 'acceleration_print', type: 'number', step: 250 },
  // Soportes
  { tab: 'support', key: 'enable_support', type: 'boolean' },
  { tab: 'support', key: 'support_type', type: 'select', options: ['tree(auto)', 'normal(auto)', 'tree(manual)', 'normal(manual)'] },
  { tab: 'support', key: 'support_style', type: 'select', options: ['default', 'tree_slim', 'tree_strong', 'tree_hybrid', 'organic', 'grid', 'snug'] },
  { tab: 'support', key: 'support_threshold_angle', type: 'number', step: 5 },
  { tab: 'support', key: 'support_top_z_distance', type: 'number', step: 0.02 },
  { tab: 'support', key: 'support_bottom_z_distance', type: 'number', step: 0.02 },
  { tab: 'support', key: 'support_object_xy_distance', type: 'number', step: 0.05 },
  { tab: 'support', key: 'support_interface_top_layers', type: 'number', step: 1 },
  { tab: 'support', key: 'support_interface_bottom_layers', type: 'number', step: 1 },
  { tab: 'support', key: 'support_interface_spacing', type: 'number', step: 0.05 },
  { tab: 'support', key: 'support_interface_pattern', type: 'select', options: ['auto', 'rectilinear', 'concentric', 'rectilinear_interlaced', 'grid'] },
  // Multimaterial
  { tab: 'multimaterial', key: 'active_tools', type: 'readonly' },
  { tab: 'multimaterial', key: 'tool_mapping', type: 'readonly' },
  { tab: 'multimaterial', key: 'enable_prime_tower', type: 'boolean' },
  { tab: 'multimaterial', key: 'prime_tower_width', type: 'number', step: 1 },
  { tab: 'multimaterial', key: 'prime_tower_brim_width', type: 'readonly' },
  { tab: 'multimaterial', key: 'flush_volumes', type: 'readonly' },
  { tab: 'multimaterial', key: 'support_interface_filament', type: 'number', step: 1 },
  { tab: 'multimaterial', key: 'z_color_changes', type: 'readonly' },
  // Otros
  { tab: 'others', key: 'brim_type', type: 'select', options: ['no_brim', 'outer_only', 'inner_only', 'outer_and_inner'] },
  { tab: 'others', key: 'brim_width', type: 'number', step: 1 },
  { tab: 'others', key: 'skirt_loops', type: 'number', step: 1 },
  { tab: 'others', key: 'layer_pauses', type: 'readonly' },
  { tab: 'others', key: 'anti_stringing_active', type: 'readonly' },
  { tab: 'others', key: 'chamber_temp', type: 'readonly' },
  { tab: 'others', key: 'bed_temp', type: 'readonly' },
  { tab: 'others', key: 'gcode_filename', type: 'readonly' },
  { tab: 'others', key: 'printer_name', type: 'readonly' },
  { tab: 'others', key: 'slicer_engine', type: 'readonly' },
  { tab: 'others', key: 'sliced_at_timestamp', type: 'readonly' },
];

const FILAMENT_FIELDS: Array<{ key: keyof SlicedProfileFilament; step?: number; readonly?: boolean }> = [
  { key: 'nozzle_temp_initial', step: 1 },
  { key: 'nozzle_temp', step: 1 },
  { key: 'bed_temp_initial', step: 1 },
  { key: 'bed_temp', step: 1 },
  { key: 'fan_min_speed', step: 5 },
  { key: 'fan_max_speed', step: 5 },
  { key: 'overhang_fan_speed', step: 5 },
  { key: 'retraction_length', step: 0.1 },
  { key: 'retraction_speed', step: 5 },
  { key: 'max_volumetric_flow', step: 0.5 },
  { key: 'density_g_cm3', step: 0.01 },
  { key: 'cost_per_kg_cop', step: 1000, readonly: true },
];

const OPTION_LABELS: Record<string, string> = {
  default: 'Por defecto (default)',
  tree_slim: 'Árbol delgado (tree_slim)',
  tree_strong: 'Árbol fuerte (tree_strong)',
  tree_hybrid: 'Árbol híbrido (tree_hybrid)',
  organic: 'Árbol orgánico (organic)',
  grid: 'Rejilla (grid)',
  snug: 'Ajustado (snug)',
  rectilinear: 'Rectilíneo (rectilinear)',
  concentric: 'Concéntrico (concentric)',
  rectilinear_interlaced: 'Entrelazado rectilíneo (rectilinear_interlaced)',
  auto: 'Automático (auto)',
};

function formatReadonlyValue(val: unknown): string {
  if (val === null || val === undefined) return '—';
  if (typeof val === 'boolean') return val ? 'ON' : 'OFF';
  if (Array.isArray(val)) return val.length === 0 ? '—' : JSON.stringify(val);
  if (typeof val === 'object') {
    const entries = Object.entries(val as Record<string, unknown>);
    return entries.length === 0 ? '—' : entries.map(([k, v]) => `${k}: ${String(v)}`).join(', ');
  }
  return String(val);
}

export function ProfileInspectorDrawer({
  open,
  onClose,
  snapshot,
  projectTitle,
  isSlicing,
  onApplyAndReslice,
}: ProfileInspectorDrawerProps) {
  const { t } = useI18n();
  const [activeTab, setActiveTab] = useState<InspectorTab>('quality');
  const [activeFilamentIdx, setActiveFilamentIdx] = useState<number>(0);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [draftEdits, setDraftEdits] = useState<Record<string, unknown>>({});
  const [draftFilaments, setDraftFilaments] = useState<Record<number, Record<string, unknown>>>({});

  useEffect(() => {
    setDraftEdits({});
    setDraftFilaments({});
    setActiveFilamentIdx(0);
  }, [snapshot]);

  const dirtyCount =
    Object.keys(draftEdits).length +
    Object.values(draftFilaments).reduce((acc, obj) => acc + Object.keys(obj).length, 0);

  const normalizedQuery = searchQuery.trim().toLowerCase();

  const visibleFields = useMemo(() => {
    if (!normalizedQuery) {
      return SECTION_FIELDS.filter((f) => f.tab === activeTab);
    }
    return SECTION_FIELDS.filter((f) => {
      const label = (t.profileInspector.fields[f.key] ?? f.key).toLowerCase();
      return label.includes(normalizedQuery) || f.key.toLowerCase().includes(normalizedQuery);
    });
  }, [activeTab, normalizedQuery, t.profileInspector.fields]);

  const visibleFilamentFields = useMemo(() => {
    if (!normalizedQuery) return FILAMENT_FIELDS;
    return FILAMENT_FIELDS.filter((f) => {
      const label = (t.profileInspector.fields[String(f.key)] ?? String(f.key)).toLowerCase();
      return (
        label.includes(normalizedQuery) ||
        String(f.key).toLowerCase().includes(normalizedQuery)
      );
    });
  }, [normalizedQuery, t.profileInspector.fields]);

  if (!open) return null;

  const tabs: Array<{ id: InspectorTab; label: string; icon: ReactNode }> = [
    { id: 'quality', label: t.profileInspector.tabs.quality, icon: <Sparkles className="h-3 w-3" /> },
    { id: 'strength', label: t.profileInspector.tabs.strength, icon: <Shield className="h-3 w-3" /> },
    { id: 'speed', label: t.profileInspector.tabs.speed, icon: <Zap className="h-3 w-3" /> },
    { id: 'support', label: t.profileInspector.tabs.support, icon: <Layers className="h-3 w-3" /> },
    { id: 'multimaterial', label: t.profileInspector.tabs.multimaterial, icon: <Palette className="h-3 w-3" /> },
    { id: 'others', label: t.profileInspector.tabs.others, icon: <Wrench className="h-3 w-3" /> },
    { id: 'filaments', label: t.profileInspector.tabs.filaments, icon: <Flame className="h-3 w-3" /> },
  ];

  const getFieldValue = (spec: FieldSpec): unknown => {
    if (spec.key in draftEdits) return draftEdits[spec.key];
    const section = snapshot[spec.tab] as Record<string, unknown> | undefined;
    return section ? section[spec.key] : '';
  };

  const setFieldValue = (key: string, value: unknown) => {
    setDraftEdits((prev) => {
      const next = { ...prev, [key]: value };
      if (key === 'support_type') {
        const isNormal = String(value ?? '').startsWith('normal');
        const curStyle = String(
          'support_style' in prev ? prev.support_style : snapshot.support.support_style ?? 'default',
        );
        const validStyles = isNormal
          ? ['default', 'grid', 'snug']
          : ['default', 'tree_slim', 'tree_strong', 'tree_hybrid', 'organic'];
        if (!validStyles.includes(curStyle)) {
          next.support_style = 'default';
        }
      }
      return next;
    });
  };

  const getFilamentFieldValue = (idx: number, key: keyof SlicedProfileFilament): unknown => {
    const slotDraft = draftFilaments[idx];
    if (slotDraft && String(key) in slotDraft) return slotDraft[String(key)];
    return snapshot.filaments[idx]?.[key] ?? '';
  };

  const setFilamentFieldValue = (idx: number, key: keyof SlicedProfileFilament, value: unknown) => {
    setDraftFilaments((prev) => ({
      ...prev,
      [idx]: {
        ...(prev[idx] ?? {}),
        [String(key)]: value,
      },
    }));
  };

  const handleApply = async () => {
    const payload: Record<string, unknown> = { ...draftEdits };
    if (Object.keys(draftFilaments).length > 0) {
      payload.filaments = snapshot.filaments.map((fil, idx) => ({
        slot: fil.slot,
        ...(draftFilaments[idx] ?? {}),
      }));
    }
    await onApplyAndReslice(payload);
  };

  const slicedAtDisplay = (() => {
    try {
      return new Date(snapshot.others.sliced_at_timestamp).toLocaleString();
    } catch {
      return snapshot.others.sliced_at_timestamp || '—';
    }
  })();

  const activeFilament = snapshot.filaments[activeFilamentIdx] ?? snapshot.filaments[0];

  return (
    <aside className="fixed top-14 right-0 bottom-0 z-40 flex w-[440px] max-w-[92vw] flex-col border-l border-slate-700/80 bg-slate-900/95 text-xs shadow-2xl backdrop-blur-md">
      {/* Encabezado */}
      <div className="border-b border-slate-800 px-4 py-3">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 shrink-0 text-cyan-400" />
              <h2 className="truncate text-sm font-bold text-slate-100">{projectTitle}</h2>
            </div>
            {snapshot.others.gcode_filename && (
              <p className="mt-0.5 truncate font-mono text-[10px] text-cyan-300">
                {snapshot.others.gcode_filename}
              </p>
            )}
            <p className="mt-0.5 truncate text-[11px] text-slate-400">
              {snapshot.others.printer_name} · {snapshot.others.slicer_engine}
            </p>
            <p className="font-mono text-[10px] text-slate-500">{slicedAtDisplay}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-slate-700 bg-slate-800/80 p-1 text-slate-400 transition hover:text-slate-100"
            aria-label={t.systemSetup.close}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-300">
            <CheckCircle2 className="h-3 w-3" />
            {t.profileInspector.savedBadge}
          </span>
          <span className="text-[10px] text-slate-400">
            {t.profileInspector.currentGcodeHint}
          </span>
        </div>

        {/* Buscador rápido */}
        <div className="relative mt-2.5">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder={t.profileInspector.searchPlaceholder}
            className="w-full rounded-lg border border-slate-700 bg-slate-950/90 py-1.5 pr-7 pl-8 text-[11px] text-slate-100 placeholder-slate-500 focus:border-cyan-500 focus:outline-none"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="absolute top-1/2 right-2 -translate-y-1/2 text-slate-500 hover:text-slate-200"
            >
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
      </div>

      {/* Pestañas estilo OrcaSlicer */}
      <div className="flex flex-wrap gap-1 border-b border-slate-800 bg-slate-950/60 px-3 py-2">
        {tabs.map((tab) => {
          const active = !normalizedQuery && activeTab === tab.id;
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => {
                setSearchQuery('');
                setActiveTab(tab.id);
              }}
              className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[10px] font-semibold transition ${
                active
                  ? 'bg-cyan-500/20 text-cyan-200 ring-1 ring-cyan-500/40'
                  : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
              }`}
            >
              {tab.icon}
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Contenido de parámetros */}
      <div className="flex-1 space-y-2 overflow-y-auto px-4 py-3">
        {(activeTab !== 'filaments' || Boolean(normalizedQuery)) &&
          visibleFields.map((spec) => {
            const val = getFieldValue(spec);
            const label = t.profileInspector.fields[spec.key] ?? spec.key;
            const isDirty = spec.key in draftEdits;
            return (
              <div
                key={`${spec.tab}-${spec.key}`}
                className={`flex items-center justify-between gap-2 rounded-xl border px-3 py-2 ${
                  isDirty
                    ? 'border-amber-500/50 bg-amber-500/10'
                    : 'border-slate-800 bg-slate-950/60'
                }`}
              >
                <div className="min-w-0 flex-1">
                  {normalizedQuery && (
                    <span className="mb-0.5 inline-block rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-semibold text-cyan-300">
                      {t.profileInspector.tabs[spec.tab]}
                    </span>
                  )}
                  <p className="truncate text-[11px] font-medium text-slate-200">{label}</p>
                  <p className="truncate font-mono text-[9px] text-slate-500">{spec.key}</p>
                </div>

                {spec.type === 'readonly' ? (
                  <span className="max-w-[165px] truncate rounded-md bg-slate-900 px-2 py-1 font-mono text-[10px] text-slate-300">
                    {formatReadonlyValue(val)}
                  </span>
                ) : spec.type === 'boolean' ? (
                  <button
                    type="button"
                    onClick={() => setFieldValue(spec.key, !Boolean(val))}
                    className={`rounded-lg px-2.5 py-1 font-mono text-[10px] font-bold transition ${
                      Boolean(val)
                        ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40'
                        : 'bg-slate-800 text-slate-400'
                    }`}
                  >
                    {Boolean(val) ? 'ON' : 'OFF'}
                  </button>
                ) : spec.type === 'select' ? (
                  <select
                    value={String(val ?? '')}
                    onChange={(e) => setFieldValue(spec.key, e.target.value)}
                    className="w-36 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 font-mono text-[11px] text-slate-100 focus:border-cyan-500 focus:outline-none"
                  >
                    {(spec.key === 'support_style'
                      ? String(
                          'support_type' in draftEdits
                            ? draftEdits.support_type
                            : snapshot.support.support_type ?? 'tree(auto)',
                        ).startsWith('normal')
                        ? ['default', 'grid', 'snug']
                        : ['default', 'tree_slim', 'tree_strong', 'tree_hybrid', 'organic']
                      : (spec.options ?? [])
                    ).map((opt) => (
                      <option key={opt} value={opt}>
                        {OPTION_LABELS[opt] ?? opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={spec.type === 'number' ? 'number' : 'text'}
                    step={spec.step ?? 0.1}
                    value={String(val ?? '')}
                    onChange={(e) =>
                      setFieldValue(
                        spec.key,
                        spec.type === 'number' ? Number(e.target.value) : e.target.value,
                      )
                    }
                    className="w-24 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1 text-right font-mono text-[11px] text-slate-100 focus:border-cyan-500 focus:outline-none"
                  />
                )}
              </div>
            );
          })}

        {(activeTab === 'filaments' || Boolean(normalizedQuery)) &&
          snapshot.filaments.length > 0 && (
            <div className="space-y-2.5">
              {/* Selector de slot T0-T3 */}
              <div className="flex flex-wrap gap-1.5">
                {snapshot.filaments.map((fil, idx) => (
                  <button
                    key={fil.slot}
                    type="button"
                    onClick={() => setActiveFilamentIdx(idx)}
                    className={`flex items-center gap-1.5 rounded-xl border px-2.5 py-1.5 text-[11px] font-semibold transition ${
                      activeFilamentIdx === idx
                        ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-100'
                        : 'border-slate-800 bg-slate-950/70 text-slate-300 hover:border-slate-700'
                    }`}
                  >
                    <span
                      className="h-3 w-3 rounded-full border border-white/30"
                      style={{ backgroundColor: fil.color_hex }}
                    />
                    <span>{fil.slot}</span>
                    <span className="text-[10px] text-slate-400">{fil.material}</span>
                  </button>
                ))}
              </div>

              {activeFilament && (
                <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-2.5">
                  <div className="mb-2 flex items-center justify-between border-b border-slate-800 pb-1.5">
                    <div className="flex items-center gap-2">
                      <span
                        className="h-3.5 w-3.5 rounded-full border border-white/30"
                        style={{ backgroundColor: activeFilament.color_hex }}
                      />
                      <span className="font-semibold text-slate-100">
                        {activeFilament.slot} · {activeFilament.material}
                      </span>
                    </div>
                    <span className="max-w-[170px] truncate text-[10px] text-slate-400">
                      {activeFilament.brand_or_name}
                    </span>
                  </div>

                  <div className="space-y-1.5">
                    {visibleFilamentFields.map((spec) => {
                      const val = getFilamentFieldValue(activeFilamentIdx, spec.key);
                      const label =
                        t.profileInspector.fields[String(spec.key)] ?? String(spec.key);
                      const isDirty = Boolean(
                        draftFilaments[activeFilamentIdx]?.[String(spec.key)] !== undefined,
                      );
                      return (
                        <div
                          key={`${activeFilament.slot}-${String(spec.key)}`}
                          className={`flex items-center justify-between gap-2 rounded-lg border px-2.5 py-1.5 ${
                            isDirty
                              ? 'border-amber-500/50 bg-amber-500/10'
                              : 'border-slate-800/80 bg-slate-900/60'
                          }`}
                        >
                          <span className="truncate text-[11px] text-slate-200">{label}</span>
                          {spec.readonly ? (
                            <span className="font-mono text-[11px] text-slate-300">
                              {formatReadonlyValue(val)}
                            </span>
                          ) : (
                            <input
                              type="number"
                              step={spec.step ?? 1}
                              value={String(val ?? '')}
                              onChange={(e) =>
                                setFilamentFieldValue(
                                  activeFilamentIdx,
                                  spec.key,
                                  Number(e.target.value),
                                )
                              }
                              className="w-24 rounded-md border border-slate-700 bg-slate-950 px-2 py-0.5 text-right font-mono text-[11px] text-slate-100 focus:border-cyan-500 focus:outline-none"
                            />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

        {normalizedQuery &&
          visibleFields.length === 0 &&
          visibleFilamentFields.length === 0 && (
            <div className="rounded-xl border border-slate-800 bg-slate-950/60 p-4 text-center text-[11px] text-slate-400">
              {t.profileInspector.noMatches}
            </div>
          )}
      </div>

      {/* Pie con Aplicar y Re-laminar */}
      <div className="flex items-center justify-between gap-2 border-t border-slate-800 bg-slate-950/90 px-4 py-3">
        {dirtyCount > 0 ? (
          <button
            type="button"
            onClick={() => {
              setDraftEdits({});
              setDraftFilaments({});
            }}
            className="rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 text-[11px] font-semibold text-slate-300 hover:text-slate-100"
          >
            {t.profileInspector.resetChanges} ({dirtyCount})
          </button>
        ) : (
          <span className="flex items-center gap-1 text-[10px] text-slate-400">
            <Settings2 className="h-3.5 w-3.5 text-slate-500" />
            {snapshot.quality.layer_height}mm · {snapshot.speed.outer_wall_speed} mm/s
          </span>
        )}

        <button
          type="button"
          disabled={isSlicing}
          onClick={() => void handleApply()}
          className="flex items-center gap-1.5 rounded-xl bg-gradient-to-r from-cyan-500 to-emerald-500 px-3.5 py-2 text-[11px] font-bold text-slate-950 shadow-lg transition hover:brightness-110 disabled:opacity-50"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${isSlicing ? 'animate-spin' : ''}`} />
          <span>
            {isSlicing ? t.profileInspector.reslicing : t.profileInspector.applyAndReslice}
          </span>
        </button>
      </div>
    </aside>
  );
}
