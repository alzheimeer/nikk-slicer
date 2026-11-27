import * as THREE from 'three';
import { getTriangleMeshIndex } from './supportPaint';

export type ColorPaintToolMode = 'sphere' | 'smart_fill' | 'height_range' | 'triangle';
export type ColorPaintMap = Record<number, number>; // origTriIdx -> extruder (1..4)

function toOrigTriIndex(geo: THREE.BufferGeometry, renderTriIdx: number): number {
  const map = geo.userData?.origTriMap as Uint32Array | undefined;
  if (map && renderTriIdx >= 0 && renderTriIdx < map.length) {
    return map[renderTriIdx];
  }
  return renderTriIdx;
}

export function paintColorSphereWorldOnMesh(
  mesh: THREE.Mesh,
  worldPoint: THREE.Vector3,
  radiusMm: number,
  extruder: number, // 0 = borrar, 1..4 = extrusor
  currentMap: ColorPaintMap,
): ColorPaintMap | null {
  const geo = mesh.geometry as THREE.BufferGeometry;
  if (!geo) return null;
  const idx = getTriangleMeshIndex(geo);
  mesh.updateMatrixWorld(true);
  const invMat = mesh.matrixWorld.clone().invert();
  const localPt = worldPoint.clone().applyMatrix4(invMat);

  const scaleVec = new THREE.Vector3();
  mesh.matrixWorld.decompose(new THREE.Vector3(), new THREE.Quaternion(), scaleVec);
  const minScale = Math.max(0.05, Math.min(Math.abs(scaleVec.x), Math.abs(scaleVec.y), Math.abs(scaleVec.z)));
  const rLocal = radiusMm / minScale;
  const r2 = rLocal * rLocal;

  let changed = false;
  const next: ColorPaintMap = { ...currentMap };
  const lx = localPt.x;
  const ly = localPt.y;
  const lz = localPt.z;

  for (let t = 0; t < idx.triCount; t++) {
    const dx = idx.centroids[t * 3] - lx;
    const dy = idx.centroids[t * 3 + 1] - ly;
    const dz = idx.centroids[t * 3 + 2] - lz;
    if (dx * dx + dy * dy + dz * dz <= r2) {
      const origT = toOrigTriIndex(geo, t);
      if (extruder === 0) {
        if (next[origT] !== undefined) {
          delete next[origT];
          changed = true;
        }
      } else if (next[origT] !== extruder) {
        next[origT] = extruder;
        changed = true;
      }
    }
  }
  return changed ? next : null;
}

export function paintColorSmartFillOnGeometry(
  geo: THREE.BufferGeometry,
  seedRenderTriIdx: number,
  maxAngleDeg: number,
  extruder: number,
  currentMap: ColorPaintMap,
): ColorPaintMap | null {
  const idx = getTriangleMeshIndex(geo);
  if (seedRenderTriIdx < 0 || seedRenderTriIdx >= idx.triCount) return null;

  const cosThresh = Math.cos((Math.max(1, Math.min(89, maxAngleDeg)) * Math.PI) / 180);
  const visited = new Uint8Array(idx.triCount);
  const queue: number[] = [seedRenderTriIdx];
  visited[seedRenderTriIdx] = 1;
  const selected: number[] = [];

  const maxFlood = Math.min(idx.triCount, 40000);
  let head = 0;
  while (head < queue.length && selected.length < maxFlood) {
    const cur = queue[head++];
    selected.push(cur);
    const nx = idx.normals[cur * 3];
    const ny = idx.normals[cur * 3 + 1];
    const nz = idx.normals[cur * 3 + 2];

    const neighbors = idx.adj[cur];
    for (let i = 0; i < neighbors.length; i++) {
      const nb = neighbors[i];
      if (visited[nb]) continue;
      const dot =
        nx * idx.normals[nb * 3] +
        ny * idx.normals[nb * 3 + 1] +
        nz * idx.normals[nb * 3 + 2];
      if (dot < cosThresh) continue;
      visited[nb] = 1;
      queue.push(nb);
    }
  }

  let changed = false;
  const next: ColorPaintMap = { ...currentMap };
  for (let i = 0; i < selected.length; i++) {
    const origT = toOrigTriIndex(geo, selected[i]);
    if (extruder === 0) {
      if (next[origT] !== undefined) {
        delete next[origT];
        changed = true;
      }
    } else if (next[origT] !== extruder) {
      next[origT] = extruder;
      changed = true;
    }
  }
  return changed ? next : null;
}

export function paintColorHeightRangeOnMesh(
  mesh: THREE.Mesh,
  worldPoint: THREE.Vector3,
  bandHeightMm: number,
  extruder: number,
  currentMap: ColorPaintMap,
): ColorPaintMap | null {
  const geo = mesh.geometry as THREE.BufferGeometry;
  if (!geo) return null;
  const idx = getTriangleMeshIndex(geo);
  mesh.updateMatrixWorld(true);

  const halfBand = Math.max(0.2, bandHeightMm * 0.5);
  const targetY = worldPoint.y; // Three.js Y-up = Altura Z en cama
  const tmp = new THREE.Vector3();
  let changed = false;
  const next: ColorPaintMap = { ...currentMap };

  for (let t = 0; t < idx.triCount; t++) {
    tmp.set(idx.centroids[t * 3], idx.centroids[t * 3 + 1], idx.centroids[t * 3 + 2]);
    tmp.applyMatrix4(mesh.matrixWorld);
    if (Math.abs(tmp.y - targetY) <= halfBand) {
      const origT = toOrigTriIndex(geo, t);
      if (extruder === 0) {
        if (next[origT] !== undefined) {
          delete next[origT];
          changed = true;
        }
      } else if (next[origT] !== extruder) {
        next[origT] = extruder;
        changed = true;
      }
    }
  }
  return changed ? next : null;
}

export function paintColorTriangleOnGeometry(
  geo: THREE.BufferGeometry,
  renderTriIdx: number,
  extruder: number,
  currentMap: ColorPaintMap,
): ColorPaintMap | null {
  const origT = toOrigTriIndex(geo, renderTriIdx);
  const next: ColorPaintMap = { ...currentMap };
  if (extruder === 0) {
    if (next[origT] === undefined) return null;
    delete next[origT];
    return next;
  }
  if (next[origT] === extruder) return null;
  next[origT] = extruder;
  return next;
}

export function buildColorPaintOverlayGeometry(
  geo: THREE.BufferGeometry,
  colorPaintMap: ColorPaintMap,
  extruderColors: string[],
): THREE.BufferGeometry | null {
  const keys = Object.keys(colorPaintMap);
  if (keys.length === 0) return null;

  const pos = geo.attributes.position;
  const idxAttr = geo.index;
  if (!pos) return null;
  const triCount = idxAttr ? Math.floor(idxAttr.count / 3) : Math.floor(pos.count / 3);
  const origMap = geo.userData?.origTriMap as Uint32Array | undefined;

  const paletteCols = [0, 1, 2, 3].map(
    (s) => new THREE.Color(extruderColors[s] || ['#F68D11', '#191919', '#DBDADA', '#EC120B'][s]),
  );

  const positions: number[] = [];
  const colors: number[] = [];

  for (let rt = 0; rt < triCount; rt++) {
    const origT = origMap && rt < origMap.length ? origMap[rt] : rt;
    const ext = colorPaintMap[origT];
    if (!ext || ext < 1 || ext > 4) continue;
    const c = paletteCols[ext - 1];
    const i0 = idxAttr ? idxAttr.getX(rt * 3) : rt * 3;
    const i1 = idxAttr ? idxAttr.getX(rt * 3 + 1) : rt * 3 + 1;
    const i2 = idxAttr ? idxAttr.getX(rt * 3 + 2) : rt * 3 + 2;
    positions.push(
      pos.getX(i0), pos.getY(i0), pos.getZ(i0),
      pos.getX(i1), pos.getY(i1), pos.getZ(i1),
      pos.getX(i2), pos.getY(i2), pos.getZ(i2),
    );
    colors.push(c.r, c.g, c.b, c.r, c.g, c.b, c.r, c.g, c.b);
  }

  if (positions.length === 0) return null;
  const out = new THREE.BufferGeometry();
  out.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  out.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  out.computeVertexNormals();
  return out;
}
