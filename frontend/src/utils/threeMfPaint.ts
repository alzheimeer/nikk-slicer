import * as THREE from 'three';
import { unzipSync } from 'three/examples/jsm/libs/fflate.module.js';

const FAST_PAINT_SLOT: Record<string, number> = {
  '4': 0,
  '8': 1,
  '0C': 2,
  '1C': 3,
  '2C': 3,
};

/**
 * Decodifica el atributo `paint_color` (árbol cuaternario Orca/Bambu en nibbles hex) a slot `0..3` (T0..T3).
 */
export function decodePaintColorSlot(paintHex: string): number {
  const code = paintHex.trim().toUpperCase();
  if (!code) return 0;
  const fast = FAST_PAINT_SLOT[code];
  if (fast !== undefined) return fast;

  let idx = code.length - 1;
  const counts = [0, 0, 0, 0, 0];
  const stack = [1];

  while (idx >= 0 && stack.length > 0) {
    const nib = parseInt(code[idx], 16);
    idx -= 1;
    if (Number.isNaN(nib)) break;

    const splitSides = nib & 0x3;
    if (splitSides === 0) {
      let state = nib >> 2;
      if (state === 3 && idx >= 0) {
        const extOff = parseInt(code[idx], 16);
        idx -= 1;
        if (!Number.isNaN(extOff)) state = 3 + extOff;
      }
      const slot = Math.max(0, Math.min(4, state));
      counts[slot] += 1;
    } else {
      stack.push(4);
      continue;
    }

    while (stack.length > 0) {
      stack[stack.length - 1] -= 1;
      if (stack[stack.length - 1] === 0) {
        stack.pop();
      } else {
        break;
      }
    }
  }

  let bestSlot = 0;
  let bestCount = 0;
  for (let ext = 1; ext <= 4; ext += 1) {
    if (counts[ext] > bestCount) {
      bestCount = counts[ext];
      bestSlot = ext - 1;
    }
  }
  return bestCount > 0 ? bestSlot : 0;
}

function normZipPath(p: string): string {
  return p.replace(/^\/+/, '').replace(/\\/g, '/');
}

function normalizeHexColor(raw: unknown): string | null {
  if (typeof raw !== 'string') return null;
  const clean = raw.trim().replace(/^#/, '');
  if (clean.length < 6) return null;
  return `#${clean.slice(0, 6).toUpperCase()}`;
}

function extractAttr(tag: string, attrName: string): string | null {
  const needle = `${attrName}="`;
  const idx = tag.indexOf(needle);
  if (idx === -1) return null;
  const start = idx + needle.length;
  const end = tag.indexOf('"', start);
  if (end === -1) return null;
  return tag.slice(start, end);
}

interface ParsedObjectTriangles {
  slots: Uint8Array;
  splitCodes: Map<number, string>;
  hasMulticolorPaint: boolean;
}

function isSplitPaintCode(code: string): boolean {
  if (!code || FAST_PAINT_SLOT[code] !== undefined) return false;
  const lastNib = parseInt(code[code.length - 1], 16);
  if (Number.isNaN(lastNib)) return false;
  return (lastNib & 0x3) !== 0;
}

interface SubTri {
  ax: number; ay: number; az: number;
  bx: number; by: number; bz: number;
  cx: number; cy: number; cz: number;
  slot: number;
}

function subdividePaintedTriangle(
  ax: number, ay: number, az: number,
  bx: number, by: number, bz: number,
  cx: number, cy: number, cz: number,
  paintHex: string,
  maxDepth = 8,
): SubTri[] {
  const code = paintHex.trim().toUpperCase();
  const out: SubTri[] = [];
  let idx = code.length - 1;

  const rec = (
    p0x: number, p0y: number, p0z: number,
    p1x: number, p1y: number, p1z: number,
    p2x: number, p2y: number, p2z: number,
    depth: number,
  ) => {
    if (idx < 0) {
      out.push({ ax: p0x, ay: p0y, az: p0z, bx: p1x, by: p1y, bz: p1z, cx: p2x, cy: p2y, cz: p2z, slot: 0 });
      return;
    }
    const nib = parseInt(code[idx], 16);
    idx -= 1;
    if (Number.isNaN(nib)) return;

    const splitSides = nib & 0x3;
    if (splitSides === 0) {
      let state = nib >> 2;
      if (state === 3 && idx >= 0) {
        const extOff = parseInt(code[idx], 16);
        idx -= 1;
        if (!Number.isNaN(extOff)) state = 3 + extOff;
      }
      const slot = state >= 1 && state <= 4 ? state - 1 : 0;
      out.push({ ax: p0x, ay: p0y, az: p0z, bx: p1x, by: p1y, bz: p1z, cx: p2x, cy: p2y, cz: p2z, slot });
      return;
    }

    if (depth >= maxDepth) {
      // Límite de seguridad: consumir subárbol y emitir color dominante
      const fallbackSlot = decodePaintColorSlot(code);
      out.push({ ax: p0x, ay: p0y, az: p0z, bx: p1x, by: p1y, bz: p1z, cx: p2x, cy: p2y, cz: p2z, slot: fallbackSlot });
      return;
    }

    const m01x = (p0x + p1x) * 0.5, m01y = (p0y + p1y) * 0.5, m01z = (p0z + p1z) * 0.5;
    const m12x = (p1x + p2x) * 0.5, m12y = (p1y + p2y) * 0.5, m12z = (p1z + p2z) * 0.5;
    const m20x = (p2x + p0x) * 0.5, m20y = (p2y + p0y) * 0.5, m20z = (p2z + p0z) * 0.5;

    if (splitSides === 3) {
      // Orden inverso de serialización Orca/PrusaSlicer: [centro, v2, v1, v0]
      rec(m01x, m01y, m01z, m12x, m12y, m12z, m20x, m20y, m20z, depth + 1);
      rec(p2x, p2y, p2z, m20x, m20y, m20z, m12x, m12y, m12z, depth + 1);
      rec(p1x, p1y, p1z, m12x, m12y, m12z, m01x, m01y, m01z, depth + 1);
      rec(p0x, p0y, p0z, m01x, m01y, m01z, m20x, m20y, m20z, depth + 1);
    } else if (splitSides === 1) {
      const sp = (nib >> 2) & 0x3;
      if (sp === 1) {
        rec(p1x, p1y, p1z, m12x, m12y, m12z, p0x, p0y, p0z, depth + 1);
        rec(p2x, p2y, p2z, p0x, p0y, p0z, m12x, m12y, m12z, depth + 1);
      } else if (sp === 2) {
        rec(p2x, p2y, p2z, m20x, m20y, m20z, p1x, p1y, p1z, depth + 1);
        rec(p0x, p0y, p0z, p1x, p1y, p1z, m20x, m20y, m20z, depth + 1);
      } else {
        rec(p1x, p1y, p1z, p2x, p2y, p2z, m01x, m01y, m01z, depth + 1);
        rec(p0x, p0y, p0z, m01x, m01y, m01z, p2x, p2y, p2z, depth + 1);
      }
    } else {
      rec(p0x, p0y, p0z, m01x, m01y, m01z, m20x, m20y, m20z, depth + 1);
      rec(p1x, p1y, p1z, p2x, p2y, p2z, m01x, m01y, m01z, depth + 1);
      rec(p2x, p2y, p2z, m20x, m20y, m20z, m01x, m01y, m01z, depth + 1);
    }
  };

  rec(ax, ay, az, bx, by, bz, cx, cy, cz, 0);
  return out;
}

function parseTrianglesBlock(trisBody: string): ParsedObjectTriangles {
  // Contar '<triangle' rápidamente para pre-alojar Uint8Array exacto sin copias
  let triCount = 0;
  let pos = 0;
  while ((pos = trisBody.indexOf('<triangle', pos)) !== -1) {
    triCount += 1;
    pos += 9;
  }

  const slots = new Uint8Array(triCount);
  const splitCodes = new Map<number, string>();
  if (triCount === 0) {
    return { slots, splitCodes, hasMulticolorPaint: false };
  }

  const seenSlots = [false, false, false, false];
  let hasPaintAttr = false;
  let hasPidAttr = false;
  const paintCache = new Map<string, number>();

  pos = 0;
  let tIdx = 0;
  while ((pos = trisBody.indexOf('<triangle', pos)) !== -1 && tIdx < triCount) {
    const gt = trisBody.indexOf('>', pos);
    if (gt === -1) break;
    const tag = trisBody.slice(pos, gt + 1);
    pos = gt + 1;

    const pc = extractAttr(tag, 'paint_color');
    let slot = 0;
    if (pc !== null) {
      hasPaintAttr = true;
      const cleanPc = pc.trim().toUpperCase();
      if (isSplitPaintCode(cleanPc)) {
        splitCodes.set(tIdx, cleanPc);
      }
      const cached = paintCache.get(cleanPc);
      if (cached !== undefined) {
        slot = cached;
      } else {
        slot = decodePaintColorSlot(cleanPc);
        if (paintCache.size < 4096) paintCache.set(cleanPc, slot);
      }
    } else {
      const pid = extractAttr(tag, 'pid');
      const p1 = extractAttr(tag, 'p1');
      if (pid !== null && p1 !== null) {
        hasPidAttr = true;
        const parsed = parseInt(p1, 10);
        slot = Number.isFinite(parsed) ? ((parsed % 4) + 4) % 4 : 0;
      }
    }

    slots[tIdx] = slot;
    seenSlots[slot] = true;
    tIdx += 1;
  }

  const distinctSlots = seenSlots.filter(Boolean).length;
  return {
    slots,
    splitCodes,
    hasMulticolorPaint: distinctSlots >= 2 && (hasPaintAttr || hasPidAttr),
  };
}

/**
 * Extrae el mapa de slots `0..3` por triángulo y los colores embebidos de un `.3mf`
 * respetando exactamente el orden de mallas generado por `ThreeMFLoader`.
 */
export function applyThreeMfTrianglePaintGroups(
  buffer: ArrayBuffer,
  grp: THREE.Group,
): { paintedMeshCount: number; palette: string[] } {
  const archive = unzipSync(new Uint8Array(buffer));
  const decoder = new TextDecoder('utf-8');
  const entriesLower = new Map<string, Uint8Array>();
  for (const [k, v] of Object.entries(archive)) {
    entriesLower.set(normZipPath(k).toLowerCase(), v);
  }

  // Leer paleta `filament_colour` embebida en Metadata/project_settings.config
  const palette: string[] = [];
  const projBytes = entriesLower.get('metadata/project_settings.config');
  if (projBytes) {
    try {
      const projJson = JSON.parse(decoder.decode(projBytes)) as {
        filament_colour?: unknown[];
      };
      if (Array.isArray(projJson.filament_colour)) {
        for (const c of projJson.filament_colour.slice(0, 4)) {
          const norm = normalizeHexColor(c);
          if (norm) palette.push(norm);
        }
      }
    } catch {
      // Ignorar JSON malformado
    }
  }

  // Parsear jerarquía de componentes/build sin cargar millones de nodos DOM de vértices/triángulos
  const domParser = new DOMParser();
  const buildItems: { modelPath: string; objId: string }[] = [];
  const compMap = new Map<string, { modelPath: string; objId: string }[]>();
  const meshTrianglesMap = new Map<string, ParsedObjectTriangles>();

  let rootModelPath: string | null = null;
  for (const [origName, data] of Object.entries(archive)) {
    const normPath = normZipPath(origName);
    if (!normPath.toLowerCase().endsWith('.model')) continue;
    if (normPath.toLowerCase() === '3d/3dmodel.model' || rootModelPath === null) {
      rootModelPath = normPath;
    }

    const xmlText = decoder.decode(data);
    // Extraer bloques <object ...>...</object> para asociar <triangles> con su id
    const objRegex = /<object\b([^>]*)>([\s\S]*?)<\/object>/g;
    let objMatch: RegExpExecArray | null;
    while ((objMatch = objRegex.exec(xmlText)) !== null) {
      const attrs = objMatch[1];
      const body = objMatch[2];
      const idMatch = /\bid="([^"]+)"/.exec(attrs);
      if (!idMatch) continue;
      const objId = idMatch[1];
      const triStart = body.indexOf('<triangles>');
      const triEnd = body.indexOf('</triangles>');
      if (triStart !== -1 && triEnd !== -1 && triEnd > triStart) {
        const trisBody = body.slice(triStart + 11, triEnd);
        meshTrianglesMap.set(`${normPath}#${objId}`, parseTrianglesBlock(trisBody));
      }
    }

    // Recortar vértices y triángulos antes de pasar por DOMParser para parseo instantáneo (<1 ms)
    const strippedXml = xmlText
      .replace(/<vertices>[\s\S]*?<\/vertices>/g, '<vertices/>')
      .replace(/<triangles>[\s\S]*?<\/triangles>/g, '<triangles/>');
    const doc = domParser.parseFromString(strippedXml, 'text/xml');

    const objNodes = doc.getElementsByTagNameNS('*', 'object');
    for (let i = 0; i < objNodes.length; i += 1) {
      const objNode = objNodes[i];
      const objId = objNode.getAttribute('id');
      if (!objId) continue;
      const compNodes = objNode.getElementsByTagNameNS('*', 'component');
      if (compNodes.length > 0) {
        const children: { modelPath: string; objId: string }[] = [];
        for (let c = 0; c < compNodes.length; c += 1) {
          const comp = compNodes[c];
          const childId = comp.getAttribute('objectid');
          if (!childId) continue;
          const pAttr =
            comp.getAttribute('p:path') ||
            comp.getAttribute('path') ||
            comp.getAttributeNS('http://schemas.microsoft.com/3dmanufacturing/production/2015/06', 'path');
          children.push({
            modelPath: pAttr ? normZipPath(pAttr) : normPath,
            objId: childId,
          });
        }
        compMap.set(`${normPath}#${objId}`, children);
      }
    }

    if (normPath.toLowerCase() === '3d/3dmodel.model') {
      const itemNodes = doc.getElementsByTagNameNS('*', 'item');
      for (let i = 0; i < itemNodes.length; i += 1) {
        const oid = itemNodes[i].getAttribute('objectid');
        if (oid) {
          buildItems.push({ modelPath: normPath, objId: oid });
        }
      }
    }
  }

  // Recorrido en profundidad idéntico a ThreeMFLoader para alinear 1:1 con THREE.Mesh en `grp`
  const orderedLeafPaints: ParsedObjectTriangles[] = [];
  const walk = (modelPath: string, objId: string) => {
    const key = `${modelPath}#${objId}`;
    const triInfo = meshTrianglesMap.get(key);
    if (triInfo) orderedLeafPaints.push(triInfo);
    const children = compMap.get(key);
    if (children) {
      for (const ch of children) {
        walk(ch.modelPath, ch.objId);
      }
    }
  };
  for (const item of buildItems) {
    walk(item.modelPath, item.objId);
  }

  const meshes: THREE.Mesh[] = [];
  grp.traverse((child) => {
    const m = child as THREE.Mesh;
    if (m.isMesh && m.geometry) meshes.push(m);
  });

  let paintedMeshCount = 0;
  for (let mIdx = 0; mIdx < meshes.length && mIdx < orderedLeafPaints.length; mIdx += 1) {
    const m = meshes[mIdx];
    const paint = orderedLeafPaints[mIdx];
    if (!paint.hasMulticolorPaint) continue;

    const geo = m.geometry;
    const counts = [0, 0, 0, 0];

    if (paint.splitCodes.size > 0) {
      // Subdividir únicamente triángulos de borde con árbol `paint_color` para bordes curvos nítidos
      const posAttr = geo.getAttribute('position');
      if (!posAttr) continue;
      const srcPos = posAttr.array as Float32Array;
      const srcIdx = geo.index ? geo.index.array : null;
      const triCount = srcIdx
        ? Math.min(paint.slots.length, Math.floor(srcIdx.length / 3))
        : Math.min(paint.slots.length, Math.floor(posAttr.count / 3));

      const buckets: [number[], number[], number[], number[]] = [[], [], [], []];
      for (let t = 0; t < triCount; t += 1) {
        let i0: number, i1: number, i2: number;
        if (srcIdx) {
          const base = t * 3;
          i0 = srcIdx[base] * 3;
          i1 = srcIdx[base + 1] * 3;
          i2 = srcIdx[base + 2] * 3;
        } else {
          const base = t * 9;
          i0 = base;
          i1 = base + 3;
          i2 = base + 6;
        }
        const ax = srcPos[i0], ay = srcPos[i0 + 1], az = srcPos[i0 + 2];
        const bx = srcPos[i1], by = srcPos[i1 + 1], bz = srcPos[i1 + 2];
        const cx = srcPos[i2], cy = srcPos[i2 + 1], cz = srcPos[i2 + 2];

        const splitCode = paint.splitCodes.get(t);
        if (splitCode) {
          const subTris = subdividePaintedTriangle(ax, ay, az, bx, by, bz, cx, cy, cz, splitCode);
          for (const st of subTris) {
            buckets[st.slot].push(st.ax, st.ay, st.az, st.bx, st.by, st.bz, st.cx, st.cy, st.cz);
            counts[st.slot] += 1;
          }
        } else {
          const s = paint.slots[t];
          buckets[s].push(ax, ay, az, bx, by, bz, cx, cy, cz);
          counts[s] += 1;
        }
      }

      const totalTris = counts[0] + counts[1] + counts[2] + counts[3];
      const nextPos = new Float32Array(totalTris * 9);
      let cursor = 0;
      for (let s = 0; s < 4; s += 1) {
        if (buckets[s].length > 0) {
          nextPos.set(buckets[s], cursor);
          cursor += buckets[s].length;
        }
      }

      if (geo.index) geo.setIndex(null);
      geo.setAttribute('position', new THREE.BufferAttribute(nextPos, 3));
      geo.deleteAttribute('color');
      geo.computeVertexNormals();
      geo.clearGroups();
      let start = 0;
      for (let s = 0; s < 4; s += 1) {
        const cnt = counts[s] * 3;
        if (cnt > 0) {
          geo.addGroup(start, cnt, s);
          start += cnt;
        }
      }
    } else if (geo.index) {
      const srcIdx = geo.index.array;
      const triCount = Math.min(paint.slots.length, Math.floor(srcIdx.length / 3));
      for (let t = 0; t < triCount; t += 1) {
        counts[paint.slots[t]] += 1;
      }

      const offsets = [0, counts[0] * 3, (counts[0] + counts[1]) * 3, (counts[0] + counts[1] + counts[2]) * 3];
      const nextIdx = new Uint32Array(triCount * 3);
      for (let t = 0; t < triCount; t += 1) {
        const s = paint.slots[t];
        const dst = offsets[s];
        const src = t * 3;
        nextIdx[dst] = srcIdx[src];
        nextIdx[dst + 1] = srcIdx[src + 1];
        nextIdx[dst + 2] = srcIdx[src + 2];
        offsets[s] += 3;
      }

      geo.setIndex(new THREE.BufferAttribute(nextIdx, 1));
      geo.clearGroups();
      let start = 0;
      for (let s = 0; s < 4; s += 1) {
        const cnt = counts[s] * 3;
        if (cnt > 0) {
          geo.addGroup(start, cnt, s);
          start += cnt;
        }
      }
    } else {
      const posAttr = geo.getAttribute('position');
      if (!posAttr) continue;
      const triCount = Math.min(paint.slots.length, Math.floor(posAttr.count / 3));
      for (let t = 0; t < triCount; t += 1) {
        counts[paint.slots[t]] += 1;
      }

      const srcPos = posAttr.array as Float32Array;
      const nextPos = new Float32Array(triCount * 9);
      const offsets = [0, counts[0] * 9, (counts[0] + counts[1]) * 9, (counts[0] + counts[1] + counts[2]) * 9];
      for (let t = 0; t < triCount; t += 1) {
        const s = paint.slots[t];
        const dst = offsets[s];
        const src = t * 9;
        nextPos.set(srcPos.subarray(src, src + 9), dst);
        offsets[s] += 9;
      }
      geo.setAttribute('position', new THREE.BufferAttribute(nextPos, 3));
      geo.deleteAttribute('color');
      geo.computeVertexNormals();
      geo.clearGroups();
      let start = 0;
      for (let s = 0; s < 4; s += 1) {
        const cnt = counts[s] * 3;
        if (cnt > 0) {
          geo.addGroup(start, cnt, s);
          start += cnt;
        }
      }
    }

    m.userData.paintedExtruderGroups = true;
    m.userData.paintedPalette = palette;
    paintedMeshCount += 1;
  }

  return { paintedMeshCount, palette };
}
