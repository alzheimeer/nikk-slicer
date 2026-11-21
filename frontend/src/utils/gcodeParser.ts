import * as THREE from 'three';

export type ExtrusionRoleId = 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7;
export type GcodeColorScheme = 'type' | 'tool' | 'speed' | 'flow' | 'temp';

export interface ExtrusionRoleMeta {
  id: ExtrusionRoleId;
  label: string;
  color: string;
}

export const EXTRUSION_ROLES: ExtrusionRoleMeta[] = [
  { id: 0, label: 'Pared exterior', color: '#F97316' },
  { id: 1, label: 'Pared interior', color: '#FACC15' },
  { id: 2, label: 'Pared en voladizo', color: '#3B82F6' },
  { id: 3, label: 'Relleno disperso', color: '#DC2626' },
  { id: 4, label: 'Relleno sólido', color: '#EC4899' },
  { id: 5, label: 'Superficie sup./inf.', color: '#A855F7' },
  { id: 6, label: 'Soportes', color: '#10B981' },
  { id: 7, label: 'Falda / Balsa / Torre', color: '#14B8A6' },
];

export interface RoleBreakdownItem {
  id: ExtrusionRoleId;
  label: string;
  color: string;
  timeSec: number;
  percentTime: number;
  meters: number;
  grams: number;
  segmentCount: number;
}

export interface ParsedLayer {
  layerIndex: number;
  z: number;
  startIndex: number;
  endIndex: number;
  travelPositions: Float32Array;
}

export interface ParsedGcodeStats {
  totalTimeSec: number;
  totalMeters: number;
  totalGrams: number;
  minSpeed: number;
  maxSpeed: number;
  minFlow: number;
  maxFlow: number;
  minTemp: number;
  maxTemp: number;
  roleStats: RoleBreakdownItem[];
}

export interface GcodePrinterCalibration {
  kinematics?: string;
  profileId?: string;
  printerId?: string;
  nominalSpeedMmS?: number;
}

export interface ParsedGcode {
  layers: ParsedLayer[];
  geometry: THREE.BufferGeometry;
  baseIndices: Uint32Array;
  segmentRoles: Uint8Array;
  segmentDurationsSec: Float32Array;
  segmentSpeedsMmS: Float32Array;
  typeColors: Float32Array;
  toolColors: Float32Array;
  speedColors: Float32Array;
  flowColors: Float32Array;
  tempColors: Float32Array;
  extruderColors: string[];
  stats: ParsedGcodeStats;
  maxZ: number;
  totalSegments: number;
}

const DEFAULT_EXTRUDER_COLORS = ['#22d3ee', '#f97316', '#22c55e', '#a855f7'];
const FILAMENT_CROSS_SECTION_MM2 = Math.PI * 0.875 * 0.875; // 1.75 mm -> 2.40528 mm²
const DEFAULT_FILAMENT_DENSITY = 1.245; // g/cm³ (GCodeProcessor.hpp)

// Soporta números con o sin cero inicial (.01977, -.8, 12.5) en X/Y/Z/I/J/R/E/F/S/T
const TOKEN_RE = /([GXYZIJREFST])(-?(?:\d+\.?\d*|\.\d+))/gi;

function hexToRgbTuple(hex: string): [number, number, number] {
  const clean = hex.replace('#', '').trim();
  if (clean.length === 6) {
    const r = parseInt(clean.slice(0, 2), 16) / 255;
    const g = parseInt(clean.slice(2, 4), 16) / 255;
    const b = parseInt(clean.slice(4, 6), 16) / 255;
    if (Number.isFinite(r) && Number.isFinite(g) && Number.isFinite(b)) {
      return [r, g, b];
    }
  }
  return [0.58, 0.64, 0.72];
}

const ROLE_RGB: Record<ExtrusionRoleId, [number, number, number]> = {
  0: hexToRgbTuple(EXTRUSION_ROLES[0].color),
  1: hexToRgbTuple(EXTRUSION_ROLES[1].color),
  2: hexToRgbTuple(EXTRUSION_ROLES[2].color),
  3: hexToRgbTuple(EXTRUSION_ROLES[3].color),
  4: hexToRgbTuple(EXTRUSION_ROLES[4].color),
  5: hexToRgbTuple(EXTRUSION_ROLES[5].color),
  6: hexToRgbTuple(EXTRUSION_ROLES[6].color),
  7: hexToRgbTuple(EXTRUSION_ROLES[7].color),
};

function classifyType(typeName: string): ExtrusionRoleId {
  const t = typeName.trim().toLowerCase();
  if (
    t.includes('skirt') ||
    t.includes('brim') ||
    t.includes('raft') ||
    t.includes('prime tower') ||
    t.includes('wipe tower')
  ) {
    return 7;
  }
  if (t.includes('support')) {
    return 6;
  }
  if (t.includes('overhang') || t.includes('bridge')) {
    return 2;
  }
  if (t.includes('outer wall') || t.includes('external perimeter')) {
    return 0;
  }
  if (t.includes('inner wall') || t.includes('perimeter') || t.includes('gap fill')) {
    return 1;
  }
  if (
    t.includes('top surface') ||
    t.includes('bottom surface') ||
    t.includes('top solid') ||
    t.includes('bottom solid') ||
    t.includes('ironing')
  ) {
    return 5;
  }
  if (t.includes('solid infill') || t.includes('internal solid') || t.includes('skin')) {
    return 4;
  }
  return 3;
}

// Paleta térmica estilo OrcaSlicer: Azul -> Cian -> Verde -> Amarillo -> Naranja -> Rojo
function heatmapRgb(tRaw: number): [number, number, number] {
  const t = Math.max(0, Math.min(1, tRaw));
  const stops: Array<[number, number, number]> = [
    [0.145, 0.388, 0.922], // Azul (#2563EB)
    [0.024, 0.714, 0.831], // Cian (#06B6D4)
    [0.133, 0.773, 0.369], // Verde (#22C55E)
    [0.98, 0.8, 0.082],    // Amarillo (#FACC15)
    [0.976, 0.451, 0.086], // Naranja (#F97316)
    [0.863, 0.149, 0.149], // Rojo (#DC2626)
  ];
  const scaled = t * (stops.length - 1);
  const idx = Math.min(stops.length - 2, Math.floor(scaled));
  const frac = scaled - idx;
  const a = stops[idx];
  const b = stops[idx + 1];
  return [
    a[0] + (b[0] - a[0]) * frac,
    a[1] + (b[1] - a[1]) * frac,
    a[2] + (b[2] - a[2]) * frac,
  ];
}

export function applyVisibleRolesToGeometry(
  parsed: ParsedGcode,
  visibleRoles: Record<ExtrusionRoleId, boolean>,
): void {
  const idxAttr = parsed.geometry.getIndex();
  if (!idxAttr) return;
  const arr = idxAttr.array as Uint32Array;
  const base = parsed.baseIndices;
  const roles = parsed.segmentRoles;
  const segCount = roles.length;
  for (let i = 0; i < segCount; i++) {
    const off = i * 12;
    if (visibleRoles[roles[i] as ExtrusionRoleId] !== false) {
      for (let k = 0; k < 12; k++) {
        arr[off + k] = base[off + k];
      }
    } else {
      const anchor = base[off];
      for (let k = 0; k < 12; k++) {
        arr[off + k] = anchor;
      }
    }
  }
  idxAttr.needsUpdate = true;
}

export function formatDurationCompact(totalSec: number): string {
  const sec = Math.max(0, Math.round(totalSec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function resolvePrinterKinematicsCalibration(cal?: GcodePrinterCalibration): {
  nominalSpeedMmS: number;
  accelFactor: number;
} {
  const kin = (cal?.kinematics ?? '').toLowerCase();
  const idStr = `${cal?.profileId ?? ''} ${cal?.printerId ?? ''}`.toLowerCase();
  if (kin === 'delta' || idStr.includes('flsun') || idStr.includes('t1')) {
    return {
      nominalSpeedMmS: cal?.nominalSpeedMmS && cal.nominalSpeedMmS > 0 ? cal.nominalSpeedMmS : 600,
      accelFactor: 1.1,
    };
  }
  if (kin === 'corexy' || idStr.includes('creator')) {
    return {
      nominalSpeedMmS: cal?.nominalSpeedMmS && cal.nominalSpeedMmS > 0 ? cal.nominalSpeedMmS : 250,
      accelFactor: 1.18,
    };
  }
  return {
    nominalSpeedMmS: cal?.nominalSpeedMmS && cal.nominalSpeedMmS > 0 ? cal.nominalSpeedMmS : 60,
    accelFactor: 1.35,
  };
}

export function parseGcodeLayers(
  gcodeText: string,
  expectedCenterX: number,
  expectedCenterY: number,
  bedSpanX = 260,
  bedSpanY = 260,
  overrideExtruderColors?: string[],
  printerCal?: GcodePrinterCalibration,
): ParsedGcode {
  const { nominalSpeedMmS, accelFactor } = resolvePrinterKinematicsCalibration(printerCal);
  let curX = expectedCenterX;
  let curY = expectedCenterY;
  let curZ = 0;
  let curE = 0;
  let relativeE = true;
  let absoluteXYZ = true;
  const hasLayerMarkers = gcodeText.includes(';LAYER_CHANGE');
  let insidePrint = false;
  let sawExplicitLayerMarker = hasLayerMarkers;
  let waitingLayerZ = false;
  let currentLayerZ = 0;
  let currentType: ExtrusionRoleId = 0;
  let currentTool = 0;
  let currentWidth = 0.42;
  let currentHeight = 0.22;
  let currentSpeedMmS = nominalSpeedMmS;
  let currentTempC = 215.0;
  let pendingToolChangeSec = 0;

  const headerColors = [...DEFAULT_EXTRUDER_COLORS];

  const segCoords: number[] = [];
  const segDims: number[] = [];
  const segMeta: number[] = [];
  const segFlowVals: number[] = [];
  const segSpeedVals: number[] = [];
  const segDurVals: number[] = [];
  const segTempVals: number[] = [];
  const layerZs: number[] = [];
  const layerTravels: number[][] = [];
  const layerElapsedMarks: (number | null)[] = [];

  const roleVolMm3 = new Float64Array(8);
  const roleTimeSec = new Float64Array(8);
  const roleSegs = new Int32Array(8);

  let currentLayerIdx = -1;
  let minParsedX = Infinity;
  let maxParsedX = -Infinity;
  let minParsedY = Infinity;
  let maxParsedY = -Infinity;

  const isGiant = gcodeText.length > 35_000_000;
  const minSegWallSq = (isGiant ? 0.85 : 0.35) ** 2;
  const minSegInnerSq = (isGiant ? 1.5 : 0.45) ** 2;

  let hasChain = false;
  let chainStartX = 0;
  let chainStartY = 0;
  let chainStartZ = 0;
  let chainEndX = 0;
  let chainEndY = 0;
  let chainEndZ = 0;
  let chainDirX = 0;
  let chainDirY = 0;
  let chainAccumDE = 0;
  let chainSpeedSum = 0;
  let chainDistSum = 0;
  let hasLastDir = false;

  const ensureLayer = (zHint: number): number => {
    const zVal = currentLayerZ > 0 ? currentLayerZ : Math.max(0.1, zHint);
    if (
      currentLayerIdx === -1 ||
      (!sawExplicitLayerMarker && Math.abs(layerZs[currentLayerIdx] - zVal) > 0.04)
    ) {
      currentLayerIdx = layerZs.length;
      layerZs.push(zVal);
      layerTravels.push([]);
      layerElapsedMarks.push(null);
    }
    return currentLayerIdx;
  };

  const emitRawSegment = (
    x1: number,
    y1: number,
    z1: number,
    x2: number,
    y2: number,
    z2: number,
    lIdx: number,
    dEVal: number,
    speedVal: number,
    tempVal: number,
  ) => {
    const segLen = Math.hypot(x2 - x1, y2 - y1, z2 - z1) || 1e-3;
    const effSpeed = Math.max(1.0, speedVal);
    const volMm3 =
      dEVal > 0 ? FILAMENT_CROSS_SECTION_MM2 * dEVal : segLen * currentWidth * currentHeight;
    const timeSec = segLen / effSpeed;
    const durationSec = timeSec * accelFactor + pendingToolChangeSec;
    pendingToolChangeSec = 0;
    const flowMm3S = Math.min(80, Math.max(0.1, volMm3 / Math.max(1e-4, timeSec)));

    segCoords.push(x1, y1, z1, x2, y2, z2);
    segDims.push(currentWidth, currentHeight);
    segMeta.push(currentType, currentTool, lIdx);
    segSpeedVals.push(effSpeed);
    segDurVals.push(durationSec);
    segFlowVals.push(flowMm3S);
    segTempVals.push(tempVal);
    roleSegs[currentType]++;

    if (x1 < minParsedX) minParsedX = x1;
    if (x1 > maxParsedX) maxParsedX = x1;
    if (x2 < minParsedX) minParsedX = x2;
    if (x2 > maxParsedX) maxParsedX = x2;
    if (y1 < minParsedY) minParsedY = y1;
    if (y1 > maxParsedY) maxParsedY = y1;
    if (y2 < minParsedY) minParsedY = y2;
    if (y2 > maxParsedY) maxParsedY = y2;
  };

  const flushChain = () => {
    if (!hasChain || currentLayerIdx < 0) {
      hasChain = false;
      hasLastDir = false;
      return;
    }
    if (
      Math.abs(chainEndX - chainStartX) > 1e-4 ||
      Math.abs(chainEndY - chainStartY) > 1e-4 ||
      Math.abs(chainEndZ - chainStartZ) > 1e-4
    ) {
      const avgSpeed = chainDistSum > 0 ? chainSpeedSum / chainDistSum : currentSpeedMmS;
      emitRawSegment(
        chainStartX,
        chainStartY,
        chainStartZ,
        chainEndX,
        chainEndY,
        chainEndZ,
        currentLayerIdx,
        chainAccumDE,
        avgSpeed,
        currentTempC,
      );
    }
    hasChain = false;
    hasLastDir = false;
    chainAccumDE = 0;
    chainSpeedSum = 0;
    chainDistSum = 0;
  };

  const pushExtrudedStep = (
    sx: number,
    sy: number,
    sz: number,
    ex: number,
    ey: number,
    ez: number,
    stepDE: number,
  ) => {
    const lIdx = ensureLayer(ez > 0 ? ez : sz);
    const vx = ex - sx;
    const vy = ey - sy;
    const vz = ez - sz;
    const segLenSq = vx * vx + vy * vy + vz * vz;
    if (segLenSq < 1e-6) return;
    const segLen = Math.sqrt(segLenSq);

    // Acumular métricas exactas del paso sin perder volumen por decimación
    const stepVol =
      stepDE > 0 ? FILAMENT_CROSS_SECTION_MM2 * stepDE : segLen * currentWidth * currentHeight;
    roleVolMm3[currentType] += stepVol;
    roleTimeSec[currentType] += segLen / Math.max(1.0, currentSpeedMmS);

    const nx = vx / segLen;
    const ny = vy / segLen;
    const minSq = currentType === 0 || currentType === 2 ? minSegWallSq : minSegInnerSq;

    if (!hasChain) {
      hasChain = true;
      chainStartX = sx;
      chainStartY = sy;
      chainStartZ = sz;
      chainEndX = ex;
      chainEndY = ey;
      chainEndZ = ez;
      chainDirX = nx;
      chainDirY = ny;
      chainAccumDE = stepDE;
      chainSpeedSum = currentSpeedMmS * segLen;
      chainDistSum = segLen;
      hasLastDir = true;
      return;
    }

    const totalDx = ex - chainStartX;
    const totalDy = ey - chainStartY;
    const totalDz = ez - chainStartZ;
    const accumSq = totalDx * totalDx + totalDy * totalDy + totalDz * totalDz;
    const cosAngle = hasLastDir ? chainDirX * nx + chainDirY * ny : 1.0;
    const cosThresh = isGiant && segLen < 0.55 ? 0.78 : 0.96;

    if (cosAngle < cosThresh || accumSq >= minSq) {
      const avgSpeed = chainDistSum > 0 ? chainSpeedSum / chainDistSum : currentSpeedMmS;
      emitRawSegment(
        chainStartX,
        chainStartY,
        chainStartZ,
        chainEndX,
        chainEndY,
        chainEndZ,
        lIdx,
        chainAccumDE,
        avgSpeed,
        currentTempC,
      );
      chainStartX = chainEndX;
      chainStartY = chainEndY;
      chainStartZ = chainEndZ;
      chainEndX = ex;
      chainEndY = ey;
      chainEndZ = ez;
      chainDirX = nx;
      chainDirY = ny;
      chainAccumDE = stepDE;
      chainSpeedSum = currentSpeedMmS * segLen;
      chainDistSum = segLen;
      hasLastDir = true;
    } else {
      chainEndX = ex;
      chainEndY = ey;
      chainEndZ = ez;
      chainAccumDE += stepDE;
      chainSpeedSum += currentSpeedMmS * segLen;
      chainDistSum += segLen;
    }
  };

  const len = gcodeText.length;
  let lineStart = 0;

  while (lineStart < len) {
    let lineEnd = gcodeText.indexOf('\n', lineStart);
    if (lineEnd === -1) lineEnd = len;

    const raw = gcodeText.slice(lineStart, lineEnd).trim();
    lineStart = lineEnd + 1;
    if (!raw) continue;

    if (raw.startsWith(';')) {
      if (raw.startsWith('; SLICERHUB_EXTRUDER_COLORS')) {
        const eq = raw.indexOf('=');
        if (eq !== -1) {
          const cols = raw
            .slice(eq + 1)
            .split(',')
            .map((c) => c.trim())
            .filter(Boolean);
          for (let i = 0; i < Math.min(4, cols.length); i++) {
            headerColors[i] = cols[i];
          }
        }
      } else if (raw.startsWith(';LAYER_CHANGE')) {
        flushChain();
        insidePrint = true;
        sawExplicitLayerMarker = true;
        waitingLayerZ = true;
      } else if (raw.startsWith('; EXECUTABLE_BLOCK_START')) {
        if (!hasLayerMarkers) insidePrint = true;
      } else if (waitingLayerZ && raw.startsWith(';Z:')) {
        const parsedZ = parseFloat(raw.slice(3));
        if (Number.isFinite(parsedZ) && parsedZ >= 0) {
          currentLayerZ = parsedZ;
          currentLayerIdx = layerZs.length;
          layerZs.push(parsedZ);
          layerTravels.push([]);
          layerElapsedMarks.push(null);
        }
        waitingLayerZ = false;
      } else if (raw.startsWith(';TIME_ELAPSED:')) {
        const tElapsed = parseFloat(raw.slice(14));
        if (Number.isFinite(tElapsed) && tElapsed >= 0 && currentLayerIdx >= 0) {
          layerElapsedMarks[currentLayerIdx] = tElapsed;
        }
      } else if (raw.startsWith(';WIDTH:')) {
        const w = parseFloat(raw.slice(7));
        if (Number.isFinite(w) && w >= 0.15 && w <= 1.8) currentWidth = w;
      } else if (raw.startsWith(';HEIGHT:')) {
        const h = parseFloat(raw.slice(8));
        if (Number.isFinite(h) && h >= 0.05 && h <= 1.0) currentHeight = h;
      } else if (raw.startsWith(';TYPE:')) {
        const nextKind = classifyType(raw.slice(6));
        if (nextKind !== currentType) {
          flushChain();
          currentType = nextKind;
        }
      } else if (
        raw.startsWith('; EXECUTABLE_BLOCK_END') ||
        raw.startsWith(';end_gcode') ||
        raw.startsWith('; SlicerHub END')
      ) {
        flushChain();
        insidePrint = false;
      }
      continue;
    }

    const semi = raw.indexOf(';');
    const codeOnly = (semi === -1 ? raw : raw.slice(0, semi)).trim();
    if (!codeOnly) continue;

    if (codeOnly[0] === 'T' || codeOnly[0] === 't') {
      const mTool = /^T([0-3])(?:\s|$)/i.exec(codeOnly);
      if (mTool) {
        flushChain();
        const nextTool = parseInt(mTool[1], 10);
        if (nextTool !== currentTool) {
          pendingToolChangeSec += 1.5;
        }
        currentTool = nextTool;
        continue;
      }
    }

    if (codeOnly.startsWith('M104') || codeOnly.startsWith('M109')) {
      const mS = /S(\d+(?:\.\d+)?)/i.exec(codeOnly);
      if (mS) {
        const tVal = parseFloat(mS[1]);
        if (Number.isFinite(tVal) && tVal >= 150 && tVal <= 340) {
          currentTempC = tVal;
        }
      }
      continue;
    }

    if (codeOnly.startsWith('M82')) {
      relativeE = false;
      continue;
    }
    if (codeOnly.startsWith('M83')) {
      relativeE = true;
      continue;
    }
    if (codeOnly.startsWith('G90')) {
      absoluteXYZ = true;
      continue;
    }
    if (codeOnly.startsWith('G91')) {
      absoluteXYZ = false;
      continue;
    }
    if (codeOnly.startsWith('G92')) {
      const mE = /E(-?(?:\d+\.?\d*|\.\d+))/i.exec(codeOnly);
      if (mE) curE = parseFloat(mE[1]);
      continue;
    }

    const isG01 = codeOnly.startsWith('G0') || codeOnly.startsWith('G1');
    const isArc = codeOnly.startsWith('G2') || codeOnly.startsWith('G3');
    if (!isG01 && !isArc) continue;
    const secondChar = codeOnly[2];
    if (secondChar !== undefined && secondChar !== ' ' && secondChar !== '\t') continue;

    let nextX = curX;
    let nextY = curY;
    let nextZ = curZ;
    let nextE: number | null = null;
    let arcI: number | null = null;
    let arcJ: number | null = null;
    let arcR: number | null = null;

    TOKEN_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    while ((match = TOKEN_RE.exec(codeOnly)) !== null) {
      const axis = match[1].toUpperCase();
      const val = parseFloat(match[2]);
      if (axis === 'X') nextX = absoluteXYZ ? val : curX + val;
      else if (axis === 'Y') nextY = absoluteXYZ ? val : curY + val;
      else if (axis === 'Z') nextZ = absoluteXYZ ? val : curZ + val;
      else if (axis === 'E') nextE = val;
      else if (axis === 'I') arcI = val;
      else if (axis === 'J') arcJ = val;
      else if (axis === 'R') arcR = val;
      else if (axis === 'F' && val > 0) {
        currentSpeedMmS = Math.max(1, Math.min(1500, val / 60));
      }
    }

    let deltaE = 0;
    if (nextE !== null) {
      if (relativeE) {
        deltaE = nextE;
      } else {
        deltaE = nextE - curE;
        curE = nextE;
      }
    }
    const isExtruding = deltaE > 1e-5;
    const activePrint = insidePrint || (!sawExplicitLayerMarker && curZ > 0 && isExtruding);

    if (isArc) {
      const cw = codeOnly.startsWith('G2');
      let cx = curX + (arcI ?? 0);
      let cy = curY + (arcJ ?? 0);
      let r = 0;

      if (arcI !== null || arcJ !== null) {
        r = Math.hypot(curX - cx, curY - cy);
      } else if (arcR !== null && Math.abs(arcR) > 1e-5) {
        const dx = nextX - curX;
        const dy = nextY - curY;
        const dist = Math.hypot(dx, dy);
        r = Math.abs(arcR);
        if (dist > 1e-5 && dist <= 2 * r) {
          const h = Math.sqrt(Math.max(0, r * r - (dist * 0.5) ** 2));
          const mx = (curX + nextX) * 0.5;
          const my = (curY + nextY) * 0.5;
          const ux = -dy / dist;
          const uy = dx / dist;
          const sign = (cw ? -1 : 1) * (arcR > 0 ? 1 : -1);
          cx = mx + sign * h * ux;
          cy = my + sign * h * uy;
        }
      }

      if (r > 1e-4 && activePrint) {
        const startA = Math.atan2(curY - cy, curX - cx);
        const endA = Math.atan2(nextY - cy, nextX - cx);
        let sweep = endA - startA;
        if (cw) {
          if (sweep >= 0) sweep -= Math.PI * 2;
        } else {
          if (sweep <= 0) sweep += Math.PI * 2;
        }
        if (Math.hypot(nextX - curX, nextY - curY) < 1e-4) {
          sweep = cw ? -Math.PI * 2 : Math.PI * 2;
        }

        const arcLen = Math.abs(sweep) * r;
        const steps = Math.max(4, Math.min(96, Math.ceil(arcLen / 0.65)));
        const stepDE = deltaE / steps;
        let px = curX;
        let py = curY;
        let pz = curZ;

        for (let s = 1; s <= steps; s++) {
          const t = s / steps;
          const a = startA + sweep * t;
          const sx = s === steps ? nextX : cx + r * Math.cos(a);
          const sy = s === steps ? nextY : cy + r * Math.sin(a);
          const sz = curZ + (nextZ - curZ) * t;
          if (isExtruding) {
            pushExtrudedStep(px, py, pz, sx, sy, sz, stepDE);
          }
          px = sx;
          py = sy;
          pz = sz;
        }
      }
      curX = nextX;
      curY = nextY;
      curZ = nextZ;
      continue;
    }

    const movedXY = Math.abs(nextX - curX) > 1e-4 || Math.abs(nextY - curY) > 1e-4;
    const zRef = currentLayerZ > 0 ? currentLayerZ : Math.max(curZ, nextZ);

    if (activePrint && movedXY && zRef > 0) {
      if (isExtruding) {
        const zA = currentLayerZ > 0 ? currentLayerZ : curZ;
        const zB = currentLayerZ > 0 ? currentLayerZ : nextZ;
        pushExtrudedStep(curX, curY, zA, nextX, nextY, zB, deltaE);
      } else {
        flushChain();
        const lIdx = ensureLayer(nextZ);
        layerTravels[lIdx].push(curX, curZ, curY, nextX, nextZ, nextY);
      }
    } else if (!movedXY) {
      flushChain();
    }

    curX = nextX;
    curY = nextY;
    curZ = nextZ;
  }

  flushChain();

  const extruderColors = headerColors.map((c, idx) =>
    overrideExtruderColors && overrideExtruderColors[idx]
      ? overrideExtruderColors[idx]
      : c,
  );
  const toolRgbPalette = extruderColors.map(hexToRgbTuple);

  const segCount = segDims.length / 2;
  let minSpeed = Infinity;
  let maxSpeed = -Infinity;
  let minFlow = Infinity;
  let maxFlow = -Infinity;
  let minTemp = Infinity;
  let maxTemp = -Infinity;

  for (let i = 0; i < segCount; i++) {
    const sp = segSpeedVals[i];
    const fl = segFlowVals[i];
    const tp = segTempVals[i];
    if (sp < minSpeed) minSpeed = sp;
    if (sp > maxSpeed) maxSpeed = sp;
    if (fl < minFlow) minFlow = fl;
    if (fl > maxFlow) maxFlow = fl;
    if (tp < minTemp) minTemp = tp;
    if (tp > maxTemp) maxTemp = tp;
  }

  if (!Number.isFinite(minSpeed)) {
    minSpeed = 40;
    maxSpeed = 200;
    minFlow = 2;
    maxFlow = 24;
    minTemp = 200;
    maxTemp = 230;
  }
  const speedSpan = Math.max(1, maxSpeed - minSpeed);
  const flowSpan = Math.max(0.5, maxFlow - minFlow);
  const tempSpan = Math.max(1, maxTemp - minTemp);

  let offsetX = expectedCenterX;
  let offsetY = expectedCenterY;
  if (segCount > 0 && Number.isFinite(minParsedX) && Number.isFinite(minParsedY)) {
    const parsedCx = (minParsedX + maxParsedX) * 0.5;
    const parsedCy = (minParsedY + maxParsedY) * 0.5;
    if (
      Math.abs(parsedCx - expectedCenterX) > bedSpanX * 0.65 ||
      Math.abs(parsedCy - expectedCenterY) > bedSpanY * 0.65
    ) {
      offsetX = parsedCx;
      offsetY = parsedCy;
    }
  }

  const positions = new Float32Array(segCount * 6 * 3);
  const normals = new Float32Array(segCount * 6 * 3);
  const typeColors = new Float32Array(segCount * 6 * 3);
  const toolColors = new Float32Array(segCount * 6 * 3);
  const speedColors = new Float32Array(segCount * 6 * 3);
  const flowColors = new Float32Array(segCount * 6 * 3);
  const tempColors = new Float32Array(segCount * 6 * 3);
  const baseIndices = new Uint32Array(segCount * 12);
  const indices = new Uint32Array(segCount * 12);
  const segmentRoles = new Uint8Array(segCount);
  const segmentDurationsSec = new Float32Array(segCount);
  const segmentSpeedsMmS = new Float32Array(segCount);

  const layerCounts = new Int32Array(layerZs.length);
  for (let i = 0; i < segCount; i++) {
    layerCounts[segMeta[i * 3 + 2]]++;
  }
  const layerSegStarts = new Int32Array(layerZs.length);
  const layerCursors = new Int32Array(layerZs.length);
  let running = 0;
  for (let l = 0; l < layerZs.length; l++) {
    layerSegStarts[l] = running;
    layerCursors[l] = running;
    running += layerCounts[l];
  }

  for (let i = 0; i < segCount; i++) {
    const cOff = i * 6;
    const dOff = i * 2;
    const mOff = i * 3;
    const lIdx = segMeta[mOff + 2];
    const outSegIdx = layerCursors[lIdx]++;

    const x1 = segCoords[cOff] - offsetX;
    const y1 = segCoords[cOff + 2];
    const z1 = -(segCoords[cOff + 1] - offsetY);

    const x2 = segCoords[cOff + 3] - offsetX;
    const y2 = segCoords[cOff + 5];
    const z2 = -(segCoords[cOff + 4] - offsetY);

    const w = segDims[dOff];
    const h = segDims[dOff + 1];
    const kind = segMeta[mOff] as ExtrusionRoleId;
    const tool = segMeta[mOff + 1];
    segmentRoles[outSegIdx] = kind;
    segmentDurationsSec[outSegIdx] = Math.max(1e-4, segDurVals[i] ?? 0.01);
    segmentSpeedsMmS[outSegIdx] = segSpeedVals[i] ?? nominalSpeedMmS;

    const dx = x2 - x1;
    const dz = z2 - z1;
    const xzLen = Math.hypot(dx, dz) || 1.0;
    const nx = -dz / xzLen;
    const nz = dx / xzLen;

    // 78% del ancho nominal de extrusión para máxima nitidez en Gyroid y paredes contiguas
    const hw = Math.max(0.11, w * 0.78 * 0.5);
    const botYOff = -h * 0.42;
    const topYOff = h * 0.5;
    const rxOff = nx * hw;
    const rzOff = nz * hw;

    const vBase = outSegIdx * 6;
    const pBase = vBase * 3;

    positions[pBase] = x1 - rxOff;
    positions[pBase + 1] = y1 + botYOff;
    positions[pBase + 2] = z1 - rzOff;

    positions[pBase + 3] = x1;
    positions[pBase + 4] = y1 + topYOff;
    positions[pBase + 5] = z1;

    positions[pBase + 6] = x1 + rxOff;
    positions[pBase + 7] = y1 + botYOff;
    positions[pBase + 8] = z1 + rzOff;

    positions[pBase + 9] = x2 - rxOff;
    positions[pBase + 10] = y2 + botYOff;
    positions[pBase + 11] = z2 - rzOff;

    positions[pBase + 12] = x2;
    positions[pBase + 13] = y2 + topYOff;
    positions[pBase + 14] = z2;

    positions[pBase + 15] = x2 + rxOff;
    positions[pBase + 16] = y2 + botYOff;
    positions[pBase + 17] = z2 + rzOff;

    const lnx = -nx * 0.85;
    const lnz = -nz * 0.85;
    const rnx = nx * 0.85;
    const rnz = nz * 0.85;

    normals[pBase] = lnx;
    normals[pBase + 1] = 0.52;
    normals[pBase + 2] = lnz;
    normals[pBase + 3] = 0;
    normals[pBase + 4] = 1;
    normals[pBase + 5] = 0;
    normals[pBase + 6] = rnx;
    normals[pBase + 7] = 0.52;
    normals[pBase + 8] = rnz;

    normals[pBase + 9] = lnx;
    normals[pBase + 10] = 0.52;
    normals[pBase + 11] = lnz;
    normals[pBase + 12] = 0;
    normals[pBase + 13] = 1;
    normals[pBase + 14] = 0;
    normals[pBase + 15] = rnx;
    normals[pBase + 16] = 0.52;
    normals[pBase + 17] = rnz;

    const tRgb = ROLE_RGB[kind] ?? ROLE_RGB[0];
    const eRgb = toolRgbPalette[tool] ?? toolRgbPalette[0];
    const sRgb = heatmapRgb((segSpeedVals[i] - minSpeed) / speedSpan);
    const fRgb = heatmapRgb((segFlowVals[i] - minFlow) / flowSpan);
    const hRgb = heatmapRgb((segTempVals[i] - minTemp) / tempSpan);

    for (let k = 0; k < 6; k++) {
      const kOff = pBase + k * 3;
      const shade = k === 1 || k === 4 ? 1.0 : 0.82;

      typeColors[kOff] = tRgb[0] * shade;
      typeColors[kOff + 1] = tRgb[1] * shade;
      typeColors[kOff + 2] = tRgb[2] * shade;

      toolColors[kOff] = eRgb[0] * shade;
      toolColors[kOff + 1] = eRgb[1] * shade;
      toolColors[kOff + 2] = eRgb[2] * shade;

      speedColors[kOff] = sRgb[0] * shade;
      speedColors[kOff + 1] = sRgb[1] * shade;
      speedColors[kOff + 2] = sRgb[2] * shade;

      flowColors[kOff] = fRgb[0] * shade;
      flowColors[kOff + 1] = fRgb[1] * shade;
      flowColors[kOff + 2] = fRgb[2] * shade;

      tempColors[kOff] = hRgb[0] * shade;
      tempColors[kOff + 1] = hRgb[1] * shade;
      tempColors[kOff + 2] = hRgb[2] * shade;
    }

    const iBase = outSegIdx * 12;
    const tris = [
      vBase, vBase + 3, vBase + 4,
      vBase, vBase + 4, vBase + 1,
      vBase + 1, vBase + 4, vBase + 5,
      vBase + 1, vBase + 5, vBase + 2,
    ];
    for (let k = 0; k < 12; k++) {
      baseIndices[iBase + k] = tris[k];
      indices[iBase + k] = tris[k];
    }
  }

  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(normals, 3));
  geometry.setAttribute('color', new THREE.BufferAttribute(typeColors.slice(), 3));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.computeBoundingSphere();

  const layers: ParsedLayer[] = [];
  let maxZ = 0;
  let prevElapsedMark = 0;
  for (let l = 0; l < layerZs.length; l++) {
    const cnt = layerCounts[l];
    const mark = layerElapsedMarks[l];
    if (cnt === 0) {
      if (mark !== null && Number.isFinite(mark) && mark > prevElapsedMark) {
        prevElapsedMark = mark;
      }
      continue;
    }

    if (mark !== null && Number.isFinite(mark) && mark > prevElapsedMark) {
      const targetLayerSec = mark - prevElapsedMark;
      prevElapsedMark = mark;
      const startSeg = layerSegStarts[l];
      const endSeg = startSeg + cnt;
      let rawLayerSec = 0;
      for (let s = startSeg; s < endSeg; s++) {
        rawLayerSec += segmentDurationsSec[s];
      }
      if (targetLayerSec > 0.05 && rawLayerSec > 0.05) {
        const scale = targetLayerSec / rawLayerSec;
        for (let s = startSeg; s < endSeg; s++) {
          segmentDurationsSec[s] = Math.max(1e-4, segmentDurationsSec[s] * scale);
        }
      }
    }

    const zVal = layerZs[l];
    if (zVal > maxZ) maxZ = zVal;

    const trvRaw = layerTravels[l];
    const trv = new Float32Array(trvRaw.length);
    for (let j = 0; j < trvRaw.length; j += 6) {
      trv[j] = trvRaw[j] - offsetX;
      trv[j + 1] = trvRaw[j + 1];
      trv[j + 2] = -(trvRaw[j + 2] - offsetY);
      trv[j + 3] = trvRaw[j + 3] - offsetX;
      trv[j + 4] = trvRaw[j + 4];
      trv[j + 5] = -(trvRaw[j + 5] - offsetY);
    }

    const startIndex = layerSegStarts[l] * 12;
    const endIndex = (layerSegStarts[l] + cnt) * 12;
    layers.push({
      layerIndex: layers.length,
      z: zVal,
      startIndex,
      endIndex,
      travelPositions: trv,
    });
  }

  // Estadísticas acumuladas según fórmulas de GCodeProcessor.cpp
  let totalTimeSec = 0;
  let totalMeters = 0;
  let totalGrams = 0;
  for (let r = 0; r < 8; r++) {
    totalTimeSec += roleTimeSec[r];
    totalMeters += (roleVolMm3[r] / FILAMENT_CROSS_SECTION_MM2) * 0.001;
    totalGrams += roleVolMm3[r] * DEFAULT_FILAMENT_DENSITY * 0.001;
  }

  const roleStats: RoleBreakdownItem[] = EXTRUSION_ROLES.map((meta) => {
    const vol = roleVolMm3[meta.id];
    const tSec = roleTimeSec[meta.id];
    return {
      id: meta.id,
      label: meta.label,
      color: meta.color,
      timeSec: tSec,
      percentTime: totalTimeSec > 0 ? (tSec / totalTimeSec) * 100 : 0,
      meters: (vol / FILAMENT_CROSS_SECTION_MM2) * 0.001,
      grams: vol * DEFAULT_FILAMENT_DENSITY * 0.001,
      segmentCount: roleSegs[meta.id],
    };
  }).filter((item) => item.segmentCount > 0 || item.meters > 0);

  return {
    layers,
    geometry,
    baseIndices,
    segmentRoles,
    segmentDurationsSec,
    segmentSpeedsMmS,
    typeColors,
    toolColors,
    speedColors,
    flowColors,
    tempColors,
    extruderColors,
    stats: {
      totalTimeSec,
      totalMeters,
      totalGrams,
      minSpeed: Math.round(minSpeed * 10) / 10,
      maxSpeed: Math.round(maxSpeed * 10) / 10,
      minFlow: Math.round(minFlow * 10) / 10,
      maxFlow: Math.round(maxFlow * 10) / 10,
      minTemp: Math.round(minTemp * 10) / 10,
      maxTemp: Math.round(maxTemp * 10) / 10,
      roleStats,
    },
    maxZ,
    totalSegments: segCount,
  };
}
