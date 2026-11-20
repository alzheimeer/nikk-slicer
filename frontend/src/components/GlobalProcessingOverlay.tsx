import { useEffect, useMemo, useState } from 'react';
import { Check, Cpu, Layers, Send } from 'lucide-react';

export type ProcessingOverlayMode =
  | 'slicing'
  | 'ai_optimize'
  | 'ai_analyze'
  | 'upload_only'
  | 'upload_and_print';

export interface GlobalProcessingOverlayProps {
  active: boolean;
  mode: ProcessingOverlayMode;
  printerName: string;
  printerIp?: string;
  fileSizeMb?: number;
  triangleCount?: number;
  layerHeightMm?: number;
}

export function GlobalProcessingOverlay({
  active,
  mode,
  printerName,
  printerIp = '',
  fileSizeMb = 0,
  triangleCount = 0,
  layerHeightMm = 0.2,
}: GlobalProcessingOverlayProps) {
  const [visible, setVisible] = useState(false);
  const [progress, setProgress] = useState(0);
  const [elapsedMs, setElapsedMs] = useState(0);

  const expectedStep3Seconds = useMemo(() => {
    const sizeTerm = Math.max(0, fileSizeMb) * 12;
    const triTerm = Math.max(0, triangleCount / 150000) * 10;
    const lhFactor = layerHeightMm < 0.18 ? 1.25 : layerHeightMm >= 0.24 ? 0.85 : 1.0;
    const raw = (25 + sizeTerm + triTerm) * lhFactor;
    return Math.min(140, Math.max(20, raw));
  }, [fileSizeMb, triangleCount, layerHeightMm]);

  useEffect(() => {
    if (active) {
      setVisible(true);
      setProgress(1);
      setElapsedMs(0);

      const startTime = performance.now();
      const timer = window.setInterval(() => {
        const ms = performance.now() - startTime;
        const t = ms / 1000;
        setElapsedMs(ms);

        let nextPct = 0;
        if (mode === 'slicing') {
          if (t <= 1.5) {
            nextPct = (t / 1.5) * 8;
          } else if (t <= 4.0) {
            nextPct = 8 + ((t - 1.5) / 2.5) * 10;
          } else {
            const s3Elapsed = t - 4.0;
            if (s3Elapsed <= expectedStep3Seconds) {
              nextPct = 18 + (s3Elapsed / expectedStep3Seconds) * 70;
            } else {
              nextPct = Math.min(97, 88 + (s3Elapsed - expectedStep3Seconds) * 0.2);
            }
          }
        } else if (mode === 'ai_optimize') {
          if (t <= 1.5) {
            nextPct = (t / 1.5) * 10;
          } else if (t <= 6.5) {
            nextPct = 10 + ((t - 1.5) / 5.0) * 18;
          } else {
            const s3Elapsed = t - 6.5;
            if (s3Elapsed <= expectedStep3Seconds) {
              nextPct = 28 + (s3Elapsed / expectedStep3Seconds) * 60;
            } else {
              nextPct = Math.min(97, 88 + (s3Elapsed - expectedStep3Seconds) * 0.2);
            }
          }
        } else if (mode === 'upload_only' || mode === 'upload_and_print') {
          const transferSec = Math.max(4, Math.min(45, 4 + Math.max(0, fileSizeMb) * 1.4));
          if (t <= 1.2) {
            nextPct = (t / 1.2) * 25;
          } else if (t <= 1.2 + transferSec) {
            nextPct = 25 + ((t - 1.2) / transferSec) * 60;
          } else {
            nextPct = Math.min(97, 85 + (t - 1.2 - transferSec) * 1.2);
          }
        } else {
          // ai_analyze: Etapa 1 (0 -> 25% en 1s) y Etapa 2 (25 -> 96%)
          if (t <= 1.0) {
            nextPct = t * 25;
          } else if (t <= 10.0) {
            nextPct = 25 + ((t - 1.0) / 9.0) * 63;
          } else {
            nextPct = Math.min(96, 88 + (t - 10.0) * 0.2);
          }
        }

        setProgress((prev) => Math.max(prev, Math.min(97, nextPct)));
      }, 200);

      return () => window.clearInterval(timer);
    }

    if (visible) {
      setProgress(100);
      const hideTimer = window.setTimeout(() => {
        setVisible(false);
        setProgress(0);
        setElapsedMs(0);
      }, 350);
      return () => window.clearTimeout(hideTimer);
    }
    return undefined;
  }, [active, visible, mode, expectedStep3Seconds]);

  if (!visible) return null;

  const pct = Math.min(100, Math.max(0, Math.round(progress)));
  const elapsedStr = `${(elapsedMs / 1000).toFixed(1)}s`;

  const steps: Array<{ label: string; threshold: number; liveSubtext?: string }> =
    mode === 'slicing'
      ? [
          {
            label: `Validando límites térmicos y caudal de ${printerName}`,
            threshold: 8,
          },
          {
            label: 'Preparando malla, soportes y perfil de capa',
            threshold: 18,
          },
          {
            label: 'Motor CLI generando capas y trayectorias G-code',
            threshold: 99,
            liveSubtext: `Procesando capas y rellenos · ${elapsedStr} transcurridos...`,
          },
        ]
      : mode === 'ai_optimize'
        ? [
            {
              label: 'Inspeccionando geometría, voladizos y área de base',
              threshold: 10,
            },
            {
              label: `Consultando DeepSeek IA con límites físicos de ${printerName}`,
              threshold: 28,
            },
            {
              label: 'Aplicando parámetros óptimos y re-laminando modelo',
              threshold: 99,
              liveSubtext: `Procesando capas y rellenos · ${elapsedStr} transcurridos...`,
            },
          ]
      : mode === 'upload_only' || mode === 'upload_and_print'
        ? [
            {
              label: 'Preparando paquete .gcode y pausas programadas...',
              threshold: 25,
            },
            {
              label: `Transfiriendo archivo por LAN a ${printerName}${printerIp ? ` (${printerIp})` : ''}...`,
              threshold: 85,
              liveSubtext: `Enviando datos por red · ${elapsedStr} transcurridos...`,
            },
            {
              label:
                mode === 'upload_and_print'
                  ? 'Verificando archivo en /gcodeList e iniciando impresión...'
                  : 'Confirmando almacenamiento en memoria sin imprimir...',
              threshold: 99,
              liveSubtext: `Validando respuesta de la impresora · ${elapsedStr}`,
            },
          ]
      : [
            {
              label: 'Inspeccionando geometría, voladizos y área de base',
              threshold: 25,
            },
            {
              label: `Consultando DeepSeek IA con límites físicos de ${printerName}`,
              threshold: 99,
              liveSubtext: `Evaluando estrategias óptimas · ${elapsedStr} transcurridos...`,
            },
          ];

  return (
    <div
      className="fixed inset-0 z-[9999] flex items-center justify-center bg-slate-950/85 p-4 backdrop-blur-md"
      role="dialog"
      aria-modal="true"
      aria-live="polite"
    >
      <div className="w-full max-w-lg rounded-2xl border border-cyan-500/40 bg-slate-900/95 p-8 shadow-[0_0_60px_rgba(6,182,212,0.3)]">
        <div className="flex flex-col items-center text-center">
          {/* Anillo giratorio doble cian/violeta 80x80 px */}
          <div className="relative flex h-20 w-20 items-center justify-center">
            <div className="absolute inset-0 animate-spin rounded-full border-4 border-cyan-400/20 border-t-cyan-400" />
            <div
              className="absolute inset-2 animate-spin rounded-full border-4 border-violet-500/20 border-b-violet-400"
              style={{ animationDirection: 'reverse', animationDuration: '1.35s' }}
            />
            <span className="font-mono text-lg font-extrabold text-white">{pct}%</span>
          </div>

          <span className="mt-2 font-mono text-xs font-semibold text-cyan-300">
            {elapsedStr}
          </span>

          <div className="mt-3 flex items-center gap-2">
            {mode === 'slicing' ? (
              <Layers className="h-4 w-4 text-cyan-400" />
            ) : mode === 'upload_only' || mode === 'upload_and_print' ? (
              <Send className="h-4 w-4 text-emerald-400" />
            ) : (
              <Cpu className="h-4 w-4 text-violet-400" />
            )}
            <h3 className="text-base font-bold tracking-tight text-white">
              {mode === 'slicing'
                ? 'Laminando Modelo 3D'
                : mode === 'ai_optimize'
                  ? 'Optimización IA + Re-laminado'
                  : mode === 'upload_only'
                    ? 'Subiendo G-code a Memoria'
                    : mode === 'upload_and_print'
                      ? 'Enviando e Iniciando Impresión'
                      : 'Análisis IA del Modelo'}
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-400">{printerName}</p>
        </div>

        {/* Barra de progreso luminosa con degradado */}
        <div className="mt-6 h-2.5 w-full overflow-hidden rounded-full bg-slate-800/90 p-0.5">
          <div
            className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-blue-500 to-violet-500 shadow-[0_0_14px_rgba(34,211,238,0.65)] transition-all duration-200"
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Checklist de etapas en vivo */}
        <div className="mt-5 space-y-2.5">
          {steps.map((step, idx) => {
            const done = pct >= step.threshold;
            const prevDone = idx === 0 ? true : pct >= steps[idx - 1].threshold;
            const current = !done && prevDone;
            return (
              <div
                key={step.label}
                className={`flex items-start gap-2.5 rounded-xl border px-3 py-2 text-xs transition ${
                  done
                    ? 'border-emerald-500/35 bg-emerald-500/10 text-emerald-200'
                    : current
                      ? 'border-cyan-500/45 bg-cyan-500/10 text-white'
                      : 'border-slate-800 bg-slate-950/50 text-slate-500'
                }`}
              >
                {done ? (
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-emerald-300">
                    <Check className="h-3.5 w-3.5" />
                  </span>
                ) : current ? (
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
                    <span className="h-2.5 w-2.5 animate-ping rounded-full bg-cyan-400" />
                  </span>
                ) : (
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center">
                    <span className="h-2 w-2 rounded-full bg-slate-700" />
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <p className="font-medium leading-snug">{step.label}</p>
                  {current && step.liveSubtext && (
                    <p className="mt-0.5 font-mono text-[10px] text-cyan-300">
                      {step.liveSubtext}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <p className="mt-5 text-center text-[11px] text-slate-400">
          Por favor espera un momento, no cierres la ventana...
        </p>
      </div>
    </div>
  );
}
