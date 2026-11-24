import * as THREE from 'three';

export type SupportPaintValue = 0 | 1 | 2; // 0 = borrar, 1 = forzar (verde), 2 = bloquear (rojo)
export type SupportPaintMap = Record<number, 1 | 2>;

export interface TriangleMeshIndex {
  triCount: number;
  centroids: Float32Array;
  normals: Float32Array;
  adj: number[][];
}

const INDEX_CACHE = new WeakMap<THREE.BufferGeometry, TriangleMeshIndex>();

export function getTriangleMeshIndex(geo: THREE.BufferGeometry): TriangleMeshIndex {
  const cached = INDEX_CACHE.get(geo);
  if (cached) return cached;

  const pos = geo.attributes.position;
  const idxAttr = geo.index;
  const triCount = idxAttr ? Math.floor(idxAttr.count / 3) : Math.floor(pos.count / 3);
  const centroids = new Float32Array(triCount * 3);
  const normals = new Float32Array(triCount * 3);
  const adj: number[][] = Array.from({ length: triCount }, () => []);

  geo.computeBoundingBox();
  const bbSize = geo.boundingBox
    ? geo.boundingBox.getSize(new THREE.Vector3())
    : new THREE.Vector3(100, 100, 100);
  const diag = bbSize.length() || 100;
  const eps = Math.max(diag * 1e-4, 1e-5);

  const edgeMap = new Map<string, number[]>();
  const q = (n: number) => Math.round(n / eps);
  const vKey = (vi: number) => `${q(pos.getX(vi))}_${q(pos.getY(vi))}_${q(pos.getZ(vi))}`;

  const a = new THREE.Vector3();
  const b = new THREE.Vector3();
  const c = new THREE.Vector3();
  const ab = new THREE.Vector3();
  const ac = new THREE.Vector3();
  const norm = new THREE.Vector3();

  for (let t = 0; t < triCount; t++) {
    const i0 = idxAttr ? idxAttr.getX(t * 3) : t * 3;
    const i1 = idxAttr ? idxAttr.getX(t * 3 + 1) : t * 3 + 1;
    const i2 = idxAttr ? idxAttr.getX(t * 3 + 2) : t * 3 + 2;

    a.fromBufferAttribute(pos, i0);
    b.fromBufferAttribute(pos, i1);
    c.fromBufferAttribute(pos, i2);

    centroids[t * 3] = (a.x + b.x + c.x) / 3;
    centroids[t * 3 + 1] = (a.y + b.y + c.y) / 3;
    centroids[t * 3 + 2] = (a.z + b.z + c.z) / 3;

    ab.subVectors(b, a);
    ac.subVectors(c, a);
    norm.crossVectors(ab, ac).normalize();
    normals[t * 3] = norm.x;
    normals[t * 3 + 1] = norm.y;
    normals[t * 3 + 2] = norm.z;

    const k0 = vKey(i0);
    const k1 = vKey(i1);
    const k2 = vKey(i2);
    const edges: [string, string][] = [
      k0 < k1 ? [k0, k1] : [k1, k0],
      k1 < k2 ? [k1, k2] : [k2, k1],
      k2 < k0 ? [k2, k0] : [k0, k2],
    ];
    for (const [ea, eb] of edges) {
      const ek = `${ea}|${eb}`;
      let list = edgeMap.get(ek);
      if (!list) {
        list = [];
        edgeMap.set(ek, list);
      }
      list.push(t);
    }
  }

  for (const list of edgeMap.values()) {
    if (list.length < 2) continue;
    for (let i = 0; i < list.length; i++) {
      for (let j = i + 1; j < list.length; j++) {
        adj[list[i]].push(list[j]);
        adj[list[j]].push(list[i]);
      }
    }
  }

  const out: TriangleMeshIndex = { triCount, centroids, normals, adj };
  INDEX_CACHE.set(geo, out);
  return out;
}

export function isOverhangTriangle(
  normals: Float32Array,
  triIdx: number,
  thresholdDeg: number,
): boolean {
  const cosLimit = -Math.cos((thresholdDeg * Math.PI) / 180);
  return normals[triIdx * 3 + 1] < cosLimit;
}

export function getGeometryTriangleCount(geo: THREE.BufferGeometry): number {
  const pos = geo.attributes.position;
  if (!pos) return 0;
  return geo.index ? Math.floor(geo.index.count / 3) : Math.floor(pos.count / 3);
}

export function paintSphereWorldOnMesh(
  mesh: THREE.Mesh,
  worldPoint: THREE.Vector3,
  radiusMm: number,
  state: SupportPaintValue,
  overhangsOnly: boolean,
  overhangThresholdDeg: number,
  currentMap: SupportPaintMap,
  hitFaceIndex?: number | null,
): SupportPaintMap | null {
  const geo = mesh.geometry as THREE.BufferGeometry;
  if (!geo?.attributes?.position) return null;
  mesh.updateMatrixWorld(true);
  const matWorld = mesh.matrixWorld;
  const idx = getTriangleMeshIndex(geo);
  const pos = geo.attributes.position;
  const idxAttr = geo.index;
  const r2 = radiusMm * radiusMm;
  const px = worldPoint.x;
  const py = worldPoint.y;
  const pz = worldPoint.z;

  const vA = new THREE.Vector3();
  const vB = new THREE.Vector3();
  const vC = new THREE.Vector3();
  const cW = new THREE.Vector3();
  const cosLimit = -Math.cos((overhangThresholdDeg * Math.PI) / 180);
  const normMat = new THREE.Matrix3().getNormalMatrix(matWorld);
  const nW = new THREE.Vector3();

  let changed = false;
  const next: SupportPaintMap = { ...currentMap };

  for (let t = 0; t < idx.triCount; t++) {
    let inside = hitFaceIndex === t;
    if (!inside) {
      const i0 = idxAttr ? idxAttr.getX(t * 3) : t * 3;
      const i1 = idxAttr ? idxAttr.getX(t * 3 + 1) : t * 3 + 1;
      const i2 = idxAttr ? idxAttr.getX(t * 3 + 2) : t * 3 + 2;

      vA.fromBufferAttribute(pos, i0).applyMatrix4(matWorld);
      vB.fromBufferAttribute(pos, i1).applyMatrix4(matWorld);
      vC.fromBufferAttribute(pos, i2).applyMatrix4(matWorld);
      cW.set((vA.x + vB.x + vC.x) / 3, (vA.y + vB.y + vC.y) / 3, (vA.z + vB.z + vC.z) / 3);

      const dC = (cW.x - px) ** 2 + (cW.y - py) ** 2 + (cW.z - pz) ** 2;
      const d0 = (vA.x - px) ** 2 + (vA.y - py) ** 2 + (vA.z - pz) ** 2;
      const d1 = (vB.x - px) ** 2 + (vB.y - py) ** 2 + (vB.z - pz) ** 2;
      const d2 = (vC.x - px) ** 2 + (vC.y - py) ** 2 + (vC.z - pz) ** 2;
      if (dC <= r2 || d0 <= r2 || d1 <= r2 || d2 <= r2) {
        inside = true;
      }
    }
    if (!inside) continue;
    if (overhangsOnly && state !== 0) {
      nW.set(idx.normals[t * 3], idx.normals[t * 3 + 1], idx.normals[t * 3 + 2])
        .applyMatrix3(normMat)
        .normalize();
      if (nW.y >= cosLimit) continue;
    }
    if (state === 0) {
      if (next[t] !== undefined) {
        delete next[t];
        changed = true;
      }
    } else if (next[t] !== state) {
      next[t] = state;
      changed = true;
    }
  }
  return changed ? next : null;
}

export function paintSphereOnGeometry(
  geo: THREE.BufferGeometry,
  localPoint: THREE.Vector3,
  radiusMm: number,
  state: SupportPaintValue,
  overhangsOnly: boolean,
  overhangThresholdDeg: number,
  currentMap: SupportPaintMap,
  hitFaceIndex?: number | null,
): SupportPaintMap | null {
  const idx = getTriangleMeshIndex(geo);
  const pos = geo.attributes.position;
  const idxAttr = geo.index;
  const r2 = radiusMm * radiusMm;
  const px = localPoint.x;
  const py = localPoint.y;
  const pz = localPoint.z;

  let changed = false;
  const next: SupportPaintMap = { ...currentMap };

  for (let t = 0; t < idx.triCount; t++) {
    let inside = hitFaceIndex === t;
    if (!inside) {
      const dx = idx.centroids[t * 3] - px;
      const dy = idx.centroids[t * 3 + 1] - py;
      const dz = idx.centroids[t * 3 + 2] - pz;
      if (dx * dx + dy * dy + dz * dz <= r2) {
        inside = true;
      } else {
        const i0 = idxAttr ? idxAttr.getX(t * 3) : t * 3;
        const i1 = idxAttr ? idxAttr.getX(t * 3 + 1) : t * 3 + 1;
        const i2 = idxAttr ? idxAttr.getX(t * 3 + 2) : t * 3 + 2;
        const d0 = (pos.getX(i0) - px) ** 2 + (pos.getY(i0) - py) ** 2 + (pos.getZ(i0) - pz) ** 2;
        const d1 = (pos.getX(i1) - px) ** 2 + (pos.getY(i1) - py) ** 2 + (pos.getZ(i1) - pz) ** 2;
        const d2 = (pos.getX(i2) - px) ** 2 + (pos.getY(i2) - py) ** 2 + (pos.getZ(i2) - pz) ** 2;
        if (d0 <= r2 || d1 <= r2 || d2 <= r2) {
          inside = true;
        }
      }
    }
    if (!inside) continue;
    if (overhangsOnly && state !== 0 && !isOverhangTriangle(idx.normals, t, overhangThresholdDeg)) {
      continue;
    }
    if (state === 0) {
      if (next[t] !== undefined) {
        delete next[t];
        changed = true;
      }
    } else if (next[t] !== state) {
      next[t] = state;
      changed = true;
    }
  }
  return changed ? next : null;
}

export function smartFillOnGeometry(
  geo: THREE.BufferGeometry,
  startTriIdx: number,
  maxAngleDeg: number,
  state: SupportPaintValue,
  overhangsOnly: boolean,
  overhangThresholdDeg: number,
  currentMap: SupportPaintMap,
): SupportPaintMap | null {
  const idx = getTriangleMeshIndex(geo);
  if (startTriIdx < 0 || startTriIdx >= idx.triCount) return null;

  const minDot = Math.cos((Math.max(2, Math.min(89, maxAngleDeg)) * Math.PI) / 180);
  const startState = currentMap[startTriIdx] ?? 0;
  const visited = new Uint8Array(idx.triCount);
  const queue: number[] = [startTriIdx];
  visited[startTriIdx] = 1;

  const snx = idx.normals[startTriIdx * 3];
  const sny = idx.normals[startTriIdx * 3 + 1];
  const snz = idx.normals[startTriIdx * 3 + 2];

  const next: SupportPaintMap = { ...currentMap };
  let changed = false;

  for (let head = 0; head < queue.length; head++) {
    const cur = queue[head];
    if (!overhangsOnly || state === 0 || isOverhangTriangle(idx.normals, cur, overhangThresholdDeg)) {
      if (state === 0) {
        if (next[cur] !== undefined) {
          delete next[cur];
          changed = true;
        }
      } else if (next[cur] !== state) {
        next[cur] = state;
        changed = true;
      }
    }

    const neighbors = idx.adj[cur];
    for (let i = 0; i < neighbors.length; i++) {
      const nb = neighbors[i];
      if (visited[nb]) continue;
      if ((currentMap[nb] ?? 0) !== startState) continue;
      const dot =
        snx * idx.normals[nb * 3] +
        sny * idx.normals[nb * 3 + 1] +
        snz * idx.normals[nb * 3 + 2];
      if (dot < minDot) continue;
      visited[nb] = 1;
      queue.push(nb);
      if (queue.length > 25000) break;
    }
  }

  return changed ? next : null;
}

export function buildAllTrianglesSupportMap(
  geo: THREE.BufferGeometry,
  state: 1 | 2,
): SupportPaintMap {
  const idx = getTriangleMeshIndex(geo);
  const out: SupportPaintMap = {};
  for (let t = 0; t < idx.triCount; t++) {
    out[t] = state;
  }
  return out;
}

export function buildSupportPaintOverlayGeometry(
  geo: THREE.BufferGeometry,
  paintMap: SupportPaintMap,
  highlightOverhangs: boolean,
  overhangThresholdDeg: number,
): THREE.BufferGeometry | null {
  const idx = getTriangleMeshIndex(geo);
  const pos = geo.attributes.position;
  const idxAttr = geo.index;

  const positions: number[] = [];
  const colors: number[] = [];

  for (let t = 0; t < idx.triCount; t++) {
    const st = paintMap[t];
    let r = 0;
    let g = 0;
    let b = 0;
    if (st === 1) {
      // Verde esmeralda (#10B981) - Forzar soporte
      r = 0.063;
      g = 0.725;
      b = 0.506;
    } else if (st === 2) {
      // Rojo intenso (#EF4444) - Bloquear soporte
      r = 0.937;
      g = 0.267;
      b = 0.267;
    } else if (highlightOverhangs && isOverhangTriangle(idx.normals, t, overhangThresholdDeg)) {
      // Naranja / Ámbar (Voladizo detectable)
      r = 0.96;
      g = 0.62;
      b = 0.04;
    } else {
      continue;
    }

    const i0 = idxAttr ? idxAttr.getX(t * 3) : t * 3;
    const i1 = idxAttr ? idxAttr.getX(t * 3 + 1) : t * 3 + 1;
    const i2 = idxAttr ? idxAttr.getX(t * 3 + 2) : t * 3 + 2;

    positions.push(
      pos.getX(i0), pos.getY(i0), pos.getZ(i0),
      pos.getX(i1), pos.getY(i1), pos.getZ(i1),
      pos.getX(i2), pos.getY(i2), pos.getZ(i2),
    );
    colors.push(r, g, b, r, g, b, r, g, b);
  }

  if (positions.length === 0) return null;
  const overlay = new THREE.BufferGeometry();
  overlay.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  overlay.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  overlay.computeVertexNormals();
  return overlay;
}
