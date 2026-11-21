import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Canvas, useThree, type ThreeEvent } from '@react-three/fiber';
import { Grid, OrbitControls, TransformControls } from '@react-three/drei';
import * as THREE from 'three';
import { STLLoader } from 'three/examples/jsm/loaders/STLLoader.js';
import { ThreeMFLoader } from 'three/examples/jsm/loaders/3MFLoader.js';
import { applyThreeMfTrianglePaintGroups } from '../utils/threeMfPaint';
import { useI18n } from '../i18n/I18nContext';
import {
  ArrowDownToLine,
  Box,
  Compass,
  CopyPlus,
  Eye,
  EyeOff,
  FlipVertical2,
  Layers,
  LayoutGrid,
  Loader2,
  Maximize2,
  MousePointerClick,
  Move,
  Pause,
  Plus,
  RotateCcw,
  RotateCw,
  Ruler,
  Scaling,
  Scissors,
  Sparkles,
  Trash2,
  X,
} from 'lucide-react';
import type {
  AIOrientationsResponse,
  LayerPauseItem,
  LayOnFaceCandidate,
  ModelInstanceTransform,
  ModelTransform,
  MultimaterialPartInfo,
  OrientationOption,
  PrinterInfo,
  SceneObjectTransform,
} from '../services/api';
import {
  applyVisibleRolesToGeometry,
  formatDurationCompact,
  parseGcodeLayers,
  type ExtrusionRoleId,
  type GcodeColorScheme,
  type ParsedGcode,
} from '../utils/gcodeParser';

export type CadToolMode =
  | 'select'
  | 'move'
  | 'rotate'
  | 'scale'
  | 'lay_on_face'
  | 'cut'
  | 'measure';

interface Viewport3DProps {
  printer: PrinterInfo | null;
  stlFile: File | null;
  meshId?: string | null;
  fitsInVolume: boolean;
  recommendedScalePercent: number;
  transform: ModelTransform;
  onChangeTransform: (next: ModelTransform) => void;
  onAutoOrient: () => void;
  isAutoOrienting?: boolean;
  autoOrientMessage?: string | null;
  orientationsData?: AIOrientationsResponse | null;
  selectedOrientationId?: string | null;
  onSelectOrientation?: (option: OrientationOption) => void;
  onCloseOrientations?: () => void;
  onAutoArrange?: (instances: ModelInstanceTransform[]) => Promise<void> | void;
  isAutoArranging?: boolean;
  onFetchLayOnFaces?: () => Promise<LayOnFaceCandidate[]>;
  onCutMesh?: (params: {
    cutZMm: number;
    tiltXDeg: number;
    tiltYDeg: number;
    keepMode: 'upper' | 'lower' | 'both';
  }) => Promise<void>;
  isCuttingMesh?: boolean;
  extruderColors?: string[];
  multimaterialParts?: MultimaterialPartInfo[];
  partExtruderMap?: Record<string, number>;
  gcodeText: string | null;
  isAnalyzing?: boolean;
  layerPauses?: LayerPauseItem[];
  onAddLayerPause?: (layer: number, zMm: number, note: string) => void;
  onRemoveLayerPause?: (layer: number) => void;
  sceneObjects?: SceneObjectTransform[];
  selectedObjectIds?: string[];
  onSelectObjects?: (ids: string[]) => void;
  onChangeSceneObjects?: (next: SceneObjectTransform[]) => void;
  onSplitObjects?: () => Promise<void> | void;
  isSplittingObjects?: boolean;
}

function buildInitialInstances(t: ModelTransform): ModelInstanceTransform[] {
  if (t.instances && t.instances.length > 0) return t.instances;
  return [
    {
      instance_id: 'inst_1',
      offset_x: t.offsetX ?? 0,
      offset_y: t.offsetY ?? 0,
      offset_z: t.offsetZ ?? 0,
      scale_percent: t.scalePercent,
      scale_x: t.scaleX ?? null,
      scale_y: t.scaleY ?? null,
      scale_z: t.scaleZ ?? null,
      rot_x: t.rotX,
      rot_y: t.rotY,
      rot_z: t.rotZ,
      drop_to_bed: t.dropToBed ?? true,
    },
  ];
}

function DeltaCircularGrid({ radius }: { radius: number }) {
  const { minorGeo, majorGeo } = useMemo(() => {
    const minor: number[] = [];
    const major: number[] = [];
    const step = 10;
    const limit = Math.floor(radius / step) * step;

    for (let coord = -limit; coord <= limit; coord += step) {
      const span = Math.sqrt(Math.max(0, radius * radius - coord * coord));
      if (span < 0.5) continue;
      const target = coord % 50 === 0 ? major : minor;
      target.push(-span, 0.04, coord, span, 0.04, coord);
      target.push(coord, 0.04, -span, coord, 0.04, span);
    }

    const gMinor = new THREE.BufferGeometry();
    gMinor.setAttribute('position', new THREE.Float32BufferAttribute(minor, 3));
    const gMajor = new THREE.BufferGeometry();
    gMajor.setAttribute('position', new THREE.Float32BufferAttribute(major, 3));
    return { minorGeo: gMinor, majorGeo: gMajor };
  }, [radius]);

  useEffect(() => {
    return () => {
      minorGeo.dispose();
      majorGeo.dispose();
    };
  }, [minorGeo, majorGeo]);

  return (
    <group>
      <lineSegments geometry={minorGeo}>
        <lineBasicMaterial color="#334155" />
      </lineSegments>
      <lineSegments geometry={majorGeo}>
        <lineBasicMaterial color="#475569" />
      </lineSegments>
    </group>
  );
}

function BuildPlate({ printer }: { printer: PrinterInfo | null }) {
  const isDelta = printer?.kinematics === 'delta';
  const radius = (printer?.diameter_mm ?? 260) / 2;
  const bedX = printer?.bed_mm?.[0] ?? 220;
  const bedY = printer?.bed_mm?.[1] ?? 220;
  const height = printer?.height_mm ?? 270;

  const { boxBedEdges, boxVolumeEdges, deltaVolumeEdges } = useMemo(() => {
    const bBed = new THREE.BoxGeometry(bedX, 0.1, bedY);
    const bVol = new THREE.BoxGeometry(bedX, height, bedY);
    const dVol = new THREE.CylinderGeometry(radius, radius, height, 64, 1, true);
    const eBed = new THREE.EdgesGeometry(bBed);
    const eVol = new THREE.EdgesGeometry(bVol);
    const eDelta = new THREE.EdgesGeometry(dVol, 15);
    bBed.dispose();
    bVol.dispose();
    dVol.dispose();
    return {
      boxBedEdges: eBed,
      boxVolumeEdges: eVol,
      deltaVolumeEdges: eDelta,
    };
  }, [bedX, bedY, height, radius]);

  useEffect(() => {
    return () => {
      boxBedEdges.dispose();
      boxVolumeEdges.dispose();
      deltaVolumeEdges.dispose();
    };
  }, [boxBedEdges, boxVolumeEdges, deltaVolumeEdges]);

  return (
    <group>
      {isDelta ? (
        <group>
          <mesh position={[0, -0.9, 0]} receiveShadow>
            <cylinderGeometry args={[radius, radius, 1.8, 72]} />
            <meshStandardMaterial color="#172238" roughness={0.55} metalness={0.25} />
          </mesh>
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.06, 0]}>
            <ringGeometry args={[radius - 1.8, radius, 72]} />
            <meshBasicMaterial color="#22d3ee" side={THREE.DoubleSide} />
          </mesh>
          <DeltaCircularGrid radius={radius} />
          <lineSegments position={[0, height / 2, 0]} geometry={deltaVolumeEdges}>
            <lineBasicMaterial color="#22d3ee" transparent opacity={0.22} />
          </lineSegments>
        </group>
      ) : (
        <group>
          <mesh position={[0, -0.9, 0]} receiveShadow>
            <boxGeometry args={[bedX, 1.8, bedY]} />
            <meshStandardMaterial color="#172238" roughness={0.55} metalness={0.25} />
          </mesh>
          <lineSegments position={[0, 0.08, 0]} geometry={boxBedEdges}>
            <lineBasicMaterial color="#22d3ee" />
          </lineSegments>
          <lineSegments position={[0, height / 2, 0]} geometry={boxVolumeEdges}>
            <lineBasicMaterial color="#22d3ee" transparent opacity={0.22} />
          </lineSegments>
          <Grid
            position={[0, 0.03, 0]}
            args={[bedX, bedY]}
            cellSize={10}
            cellThickness={0.7}
            cellColor="#334155"
            sectionSize={50}
            sectionThickness={1.3}
            sectionColor="#475569"
            fadeDistance={650}
            infiniteGrid={false}
          />
        </group>
      )}
      <axesHelper args={[35]} />
    </group>
  );
}

interface LoadedRawModel {
  stlGeo: THREE.BufferGeometry | null;
  threeMfGroup: THREE.Group | null;
  baseExtents: [number, number, number];
}

function buildTransformedInstanceGeometry(
  rawGeo: THREE.BufferGeometry,
  inst: ModelInstanceTransform,
): { geo: THREE.BufferGeometry; size: [number, number, number] } {
  const g = rawGeo.clone();
  const sx = Math.max(0.01, (inst.scale_x ?? inst.scale_percent) / 100);
  const sy = Math.max(0.01, (inst.scale_y ?? inst.scale_percent) / 100);
  const sz = Math.max(0.01, (inst.scale_z ?? inst.scale_percent) / 100);
  g.scale(sx, sy, sz);

  if (inst.rot_x !== 0 || inst.rot_y !== 0 || inst.rot_z !== 0) {
    const euler = new THREE.Euler(
      THREE.MathUtils.degToRad(inst.rot_x),
      THREE.MathUtils.degToRad(inst.rot_y),
      THREE.MathUtils.degToRad(inst.rot_z),
      'ZYX',
    );
    g.applyMatrix4(new THREE.Matrix4().makeRotationFromEuler(euler));
  }

  g.rotateX(-Math.PI / 2);
  g.computeBoundingBox();
  const box = g.boundingBox;
  let size: [number, number, number] = [0, 0, 0];
  if (box) {
    const cx = (box.min.x + box.max.x) / 2;
    const cz = (box.min.z + box.max.z) / 2;
    const minY = box.min.y;
    g.translate(-cx, -minY, -cz);
    size = [
      Math.round((box.max.x - box.min.x) * 100) / 100,
      Math.round((box.max.z - box.min.z) * 100) / 100,
      Math.round((box.max.y - box.min.y) * 100) / 100,
    ];
  }
  g.computeVertexNormals();
  return { geo: g, size };
}

function applyAlwaysOnTopGizmoStyle(ctrl: unknown) {
  const root = ctrl as THREE.Object3D | null;
  if (!root || typeof root.traverse !== 'function') return;
  root.traverse((child) => {
    child.renderOrder = 999;
    const mat = (child as THREE.Mesh).material;
    if (Array.isArray(mat)) {
      mat.forEach((m) => {
        if (m) {
          m.depthTest = false;
          m.depthWrite = false;
          m.transparent = true;
          m.needsUpdate = true;
        }
      });
    } else if (mat) {
      mat.depthTest = false;
      mat.depthWrite = false;
      mat.transparent = true;
      mat.needsUpdate = true;
    }
  });
}

function SceneObjectItemPreview({
  obj,
  isSelected,
  fitsInVolume,
  ghostMode,
  extruderColors,
  partExtruderMap,
  activeCadTool,
  onSelect,
  onCommitOffset,
  onDraggingChange,
}: {
  obj: SceneObjectTransform;
  isSelected: boolean;
  fitsInVolume: boolean;
  ghostMode: boolean;
  extruderColors?: string[];
  partExtruderMap?: Record<string, number>;
  activeCadTool: CadToolMode | null;
  onSelect: (ev: ThreeEvent<MouseEvent>) => void;
  onCommitOffset: (patch: Partial<SceneObjectTransform>) => void;
  onDraggingChange: (dragging: boolean) => void;
}) {
  const [rawGeo, setRawGeo] = useState<THREE.BufferGeometry | null>(null);
  const [groupNode, setGroupNode] = useState<THREE.Group | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const controlsRef = useRef<any>(null);

  useEffect(() => {
    let cancelled = false;
    let loadedGeo: THREE.BufferGeometry | null = null;
    if (!obj.mesh_url) return;
    const loader = new STLLoader();
    fetch(obj.mesh_url)
      .then((r) => r.arrayBuffer())
      .then((buf) => {
        if (cancelled) return;
        const g = loader.parse(buf);
        g.computeVertexNormals();
        loadedGeo = g;
        setRawGeo(g);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      loadedGeo?.dispose();
    };
  }, [obj.mesh_url]);

  const transformed = useMemo(() => {
    if (!rawGeo) return null;
    return buildTransformedInstanceGeometry(rawGeo, {
      instance_id: obj.object_id,
      offset_x: obj.offset_x,
      offset_y: obj.offset_y,
      offset_z: obj.offset_z,
      scale_percent: obj.scale_percent,
      scale_x: obj.scale_x ?? null,
      scale_y: obj.scale_y ?? null,
      scale_z: obj.scale_z ?? null,
      rot_x: obj.rot_x,
      rot_y: obj.rot_y,
      rot_z: obj.rot_z,
      drop_to_bed: obj.drop_to_bed,
    });
  }, [
    rawGeo,
    obj.object_id,
    obj.offset_x,
    obj.offset_y,
    obj.offset_z,
    obj.scale_percent,
    obj.scale_x,
    obj.scale_y,
    obj.scale_z,
    obj.rot_x,
    obj.rot_y,
    obj.rot_z,
    obj.drop_to_bed,
  ]);

  useEffect(() => () => transformed?.geo.dispose(), [transformed]);

  useEffect(() => {
    const ctrl = controlsRef.current;
    if (!ctrl) return;
    applyAlwaysOnTopGizmoStyle(ctrl);
    const raf = window.requestAnimationFrame(() => applyAlwaysOnTopGizmoStyle(ctrl));
    const cb = (ev: { value: boolean }) => {
      onDraggingChange(ev.value);
      if (!ev.value && groupNode) {
        const p = groupNode.position;
        onCommitOffset({
          offset_x: Math.round(p.x * 10) / 10,
          offset_y: Math.round(-p.z * 10) / 10,
          offset_z: obj.drop_to_bed ? 0 : Math.max(0, Math.round(p.y * 10) / 10),
        });
      }
    };
    ctrl.addEventListener('dragging-changed', cb);
    return () => {
      window.cancelAnimationFrame(raf);
      ctrl.removeEventListener('dragging-changed', cb);
    };
  }, [groupNode, activeCadTool, onDraggingChange, onCommitOffset, obj.drop_to_bed]);

  if (!transformed) return null;

  const slotIdx = partExtruderMap?.[obj.object_id] ?? Math.max(0, (obj.extruder || 1) - 1);
  const color = ghostMode
    ? '#22c55e'
    : !fitsInVolume
      ? '#f97316'
      : extruderColors?.[slotIdx] || obj.color_hex || (isSelected ? '#38bdf8' : '#94a3b8');

  const showGizmo =
    !ghostMode &&
    isSelected &&
    (activeCadTool === 'move' || activeCadTool === 'rotate' || activeCadTool === 'scale');

  return (
    <>
      <group
        ref={setGroupNode}
        position={[obj.offset_x, obj.drop_to_bed ? 0 : obj.offset_z, -obj.offset_y]}
        onClick={(e) => {
          e.stopPropagation();
          onSelect(e);
        }}
      >
        <mesh geometry={transformed.geo} castShadow receiveShadow>
          <meshStandardMaterial
            color={color}
            roughness={ghostMode ? 0.6 : 0.35}
            metalness={0.08}
            transparent={ghostMode}
            opacity={ghostMode ? 0.25 : 1}
          />
        </mesh>
        {isSelected && !ghostMode && (
          <mesh position={[0, transformed.size[2] / 2, 0]}>
            <boxGeometry
              args={[
                transformed.size[0] + 1.5,
                transformed.size[2] + 1.5,
                transformed.size[1] + 1.5,
              ]}
            />
            <meshBasicMaterial color="#22d3ee" wireframe transparent opacity={0.45} />
          </mesh>
        )}
      </group>
      {showGizmo && groupNode && (
        <TransformControls
          ref={controlsRef}
          object={groupNode}
          mode={activeCadTool === 'rotate' ? 'rotate' : activeCadTool === 'scale' ? 'scale' : 'translate'}
          showY={activeCadTool !== 'move' || !obj.drop_to_bed}
          size={1.25}
        />
      )}
    </>
  );
}

function MarqueeProjector({
  projectorRef,
}: {
  projectorRef: React.MutableRefObject<((pos: [number, number, number]) => { x: number; y: number } | null) | null>;
}) {
  const { camera, size } = useThree();
  useEffect(() => {
    projectorRef.current = (pos: [number, number, number]) => {
      const v = new THREE.Vector3(pos[0], pos[1], pos[2]).project(camera);
      if (v.z > 1) return null;
      return {
        x: ((v.x + 1) / 2) * size.width,
        y: ((-v.y + 1) / 2) * size.height,
      };
    };
    return () => {
      projectorRef.current = null;
    };
  }, [camera, size, projectorRef]);
  return null;
}

function GroupMoveGizmo({
  centroid,
  allowZ,
  onCommitDelta,
  onDraggingChange,
}: {
  centroid: { x: number; y: number; z: number };
  allowZ: boolean;
  onCommitDelta: (dx: number, dy: number, dz: number) => void;
  onDraggingChange: (dragging: boolean) => void;
}) {
  const [anchorNode, setAnchorNode] = useState<THREE.Group | null>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const controlsRef = useRef<any>(null);
  const startPosRef = useRef<{ x: number; y: number; z: number }>({
    x: centroid.x,
    y: centroid.y,
    z: centroid.z,
  });

  useEffect(() => {
    startPosRef.current = { x: centroid.x, y: centroid.y, z: centroid.z };
  }, [centroid.x, centroid.y, centroid.z]);

  useEffect(() => {
    const ctrl = controlsRef.current;
    if (!ctrl) return;
    applyAlwaysOnTopGizmoStyle(ctrl);
    const raf = window.requestAnimationFrame(() => applyAlwaysOnTopGizmoStyle(ctrl));
    const cb = (ev: { value: boolean }) => {
      onDraggingChange(ev.value);
      if (ev.value) {
        startPosRef.current = { x: centroid.x, y: centroid.y, z: centroid.z };
      } else if (anchorNode) {
        const p = anchorNode.position;
        const dx = Math.round((p.x - startPosRef.current.x) * 10) / 10;
        const dy = Math.round((-p.z - startPosRef.current.y) * 10) / 10;
        const dz = allowZ ? Math.round((p.y - startPosRef.current.z) * 10) / 10 : 0;
        if (Math.abs(dx) > 0.05 || Math.abs(dy) > 0.05 || Math.abs(dz) > 0.05) {
          onCommitDelta(dx, dy, dz);
        }
      }
    };
    ctrl.addEventListener('dragging-changed', cb);
    return () => {
      window.cancelAnimationFrame(raf);
      ctrl.removeEventListener('dragging-changed', cb);
    };
  }, [anchorNode, allowZ, centroid.x, centroid.y, centroid.z, onCommitDelta, onDraggingChange]);

  return (
    <>
      <group ref={setAnchorNode} position={[centroid.x, centroid.z, -centroid.y]}>
        <mesh renderOrder={998}>
          <sphereGeometry args={[2.6, 12, 12]} />
          <meshBasicMaterial color="#22d3ee" depthTest={false} depthWrite={false} transparent />
        </mesh>
      </group>
      {anchorNode && (
        <TransformControls
          ref={controlsRef}
          object={anchorNode}
          mode="translate"
          showY={allowZ}
          size={1.25}
        />
      )}
    </>
  );
}

function arrangeSceneObjectsOnBed(
  allObjects: SceneObjectTransform[],
  targetIds: Set<string>,
  printer: PrinterInfo | null,
): SceneObjectTransform[] {
  const toArrange = allObjects.filter((o) => targetIds.has(o.object_id));
  if (toArrange.length === 0) return allObjects;

  const spacing = 4;
  const isDelta = printer?.kinematics === 'delta';
  const maxWidth = isDelta
    ? Math.max(80, ((printer?.diameter_mm ?? 260) * 0.72))
    : Math.max(80, (printer?.bed_mm?.[0] ?? 256) - 16);

  let curX = 0;
  let curY = 0;
  let rowMaxH = 0;
  const placed: Array<{ id: string; px: number; py: number; w: number; h: number }> = [];

  const sorted = [...toArrange].sort((a, b) => {
    const ha = (a.dimensions_mm?.[1] || 40) * ((a.scale_y ?? a.scale_percent) / 100);
    const hb = (b.dimensions_mm?.[1] || 40) * ((b.scale_y ?? b.scale_percent) / 100);
    return hb - ha;
  });

  for (const obj of sorted) {
    const w = Math.max(8, (obj.dimensions_mm?.[0] || 40) * ((obj.scale_x ?? obj.scale_percent) / 100));
    const h = Math.max(8, (obj.dimensions_mm?.[1] || 40) * ((obj.scale_y ?? obj.scale_percent) / 100));
    if (curX > 0 && curX + w > maxWidth) {
      curX = 0;
      curY += rowMaxH + spacing;
      rowMaxH = 0;
    }
    placed.push({ id: obj.object_id, px: curX + w / 2, py: curY + h / 2, w, h });
    curX += w + spacing;
    rowMaxH = Math.max(rowMaxH, h);
  }

  const minX = Math.min(...placed.map((p) => p.px - p.w / 2));
  const maxX = Math.max(...placed.map((p) => p.px + p.w / 2));
  const minY = Math.min(...placed.map((p) => p.py - p.h / 2));
  const maxY = Math.max(...placed.map((p) => p.py + p.h / 2));
  const cx = (minX + maxX) / 2;
  const cy = (minY + maxY) / 2;

  const byId = new Map(
    placed.map((p) => [
      p.id,
      {
        offset_x: Math.round((p.px - cx) * 10) / 10,
        offset_y: Math.round((p.py - cy) * 10) / 10,
      },
    ]),
  );

  return allObjects.map((o) => {
    const nextPos = byId.get(o.object_id);
    if (!nextPos) return o;
    return {
      ...o,
      offset_x: nextPos.offset_x,
      offset_y: nextPos.offset_y,
      offset_z: 0,
      drop_to_bed: true,
    };
  });
}

function SingleInstancePreview({
  loaded,
  inst,
  isSelected,
  fitsInVolume,
  ghostMode,
  extruderColors,
  multimaterialParts,
  partExtruderMap,
  activeCadTool,
  isDraggingGizmo,
  onSelectInstance,
  onSurfaceClick,
  onCommitOffset,
  onDraggingChange,
}: {
  loaded: LoadedRawModel;
  inst: ModelInstanceTransform;
  isSelected: boolean;
  fitsInVolume: boolean;
  ghostMode: boolean;
  extruderColors?: string[];
  multimaterialParts?: MultimaterialPartInfo[];
  partExtruderMap?: Record<string, number>;
  activeCadTool: CadToolMode | null;
  isDraggingGizmo: boolean;
  onSelectInstance: () => void;
  onSurfaceClick?: (point: THREE.Vector3) => void;
  onCommitOffset: (next: { offset_x?: number; offset_y?: number; offset_z?: number; rot_x?: number; rot_y?: number; rot_z?: number }) => void;
  onDraggingChange: (dragging: boolean) => void;
}) {
  const groupRef = useRef<THREE.Group | null>(null);
  const [gizmoTarget, setGizmoTarget] = useState<THREE.Group | null>(null);
  const handleGroupRef = useCallback((el: THREE.Group | null) => {
    groupRef.current = el;
    setGizmoTarget((prev) => (prev === el ? prev : el));
  }, []);

  const sx = Math.max(0.01, (inst.scale_x ?? inst.scale_percent) / 100);
  const sy = Math.max(0.01, (inst.scale_y ?? inst.scale_percent) / 100);
  const sz = Math.max(0.01, (inst.scale_z ?? inst.scale_percent) / 100);
  const isUniform = Math.abs(sx - sy) < 1e-4 && Math.abs(sy - sz) < 1e-4;
  const hasRotation = inst.rot_x !== 0 || inst.rot_y !== 0 || inst.rot_z !== 0;

  // Geometría STL base en rotación actual (100% escala) para re-escalar instantáneamente en GPU
  const stlBaseResult = useMemo(() => {
    if (!loaded.stlGeo) return null;
    if (!isUniform && hasRotation) {
      return buildTransformedInstanceGeometry(loaded.stlGeo, inst);
    }
    return buildTransformedInstanceGeometry(loaded.stlGeo, {
      ...inst,
      scale_percent: 100,
      scale_x: null,
      scale_y: null,
      scale_z: null,
    });
  }, [
    loaded.stlGeo,
    inst.rot_x,
    inst.rot_y,
    inst.rot_z,
    isUniform,
    hasRotation,
    !isUniform && hasRotation ? sx : 1,
    !isUniform && hasRotation ? sy : 1,
    !isUniform && hasRotation ? sz : 1,
  ]);

  // Grupo .3MF rotado a escala 100%; la escala se aplica directamente en GPU (<group scale=...>)
  const threeMfBaseResult = useMemo(() => {
    if (!loaded.threeMfGroup) return null;
    const root = new THREE.Group();
    const inner = loaded.threeMfGroup.clone(true);
    const mat = new THREE.Matrix4();

    if (inst.rot_x !== 0 || inst.rot_y !== 0 || inst.rot_z !== 0) {
      const euler = new THREE.Euler(
        THREE.MathUtils.degToRad(inst.rot_x),
        THREE.MathUtils.degToRad(inst.rot_y),
        THREE.MathUtils.degToRad(inst.rot_z),
        'ZYX',
      );
      mat.premultiply(new THREE.Matrix4().makeRotationFromEuler(euler));
    }
    mat.premultiply(new THREE.Matrix4().makeRotationX(-Math.PI / 2));

    let meshIdx = 0;
    inner.traverse((child) => {
      const m = child as THREE.Mesh;
      if (!m.isMesh || !m.geometry) return;
      m.castShadow = !ghostMode;
      m.receiveShadow = !ghostMode;

      if (ghostMode) {
        m.material = new THREE.MeshBasicMaterial({
          color: '#22c55e',
          transparent: true,
          opacity: 0.16,
          depthWrite: false,
          side: THREE.DoubleSide,
        });
        return;
      }

      if (m.userData?.paintedExtruderGroups) {
        const paintedPalette = (m.userData.paintedPalette as string[] | undefined) || [];
        const fallbackPalette = ['#EC8B20', '#1C1A18', '#E1DDDC', '#DB3B25'];
        m.material = [0, 1, 2, 3].map((slotIdx) => {
          const hex = !fitsInVolume
            ? '#f87171'
            : extruderColors?.[slotIdx] || paintedPalette[slotIdx] || fallbackPalette[slotIdx];
          return new THREE.MeshStandardMaterial({
            color: hex,
            roughness: 0.42,
            metalness: 0.12,
          });
        });
        meshIdx += 1;
        return;
      }

      const partInfo = multimaterialParts?.[meshIdx];
      meshIdx += 1;
      const mappedExt =
        partInfo && partExtruderMap?.[partInfo.part_id]
          ? partExtruderMap[partInfo.part_id]
          : partInfo?.extruder;

      let hexColor: string | null = null;
      if (!fitsInVolume) {
        hexColor = '#f87171';
      } else if (mappedExt && extruderColors && extruderColors[mappedExt - 1]) {
        hexColor = extruderColors[mappedExt - 1];
      } else if (partInfo?.color_hex) {
        hexColor = partInfo.color_hex;
      }

      if (hexColor) {
        m.material = new THREE.MeshStandardMaterial({
          color: hexColor,
          roughness: 0.42,
          metalness: 0.12,
        });
      }
    });

    inner.applyMatrix4(mat);
    inner.updateMatrixWorld(true);
    const box = new THREE.Box3().setFromObject(inner);
    if (!box.isEmpty()) {
      const cx = (box.min.x + box.max.x) / 2;
      const cz = (box.min.z + box.max.z) / 2;
      const minY = box.min.y;
      inner.position.set(-cx, -minY, -cz);
    }

    root.add(inner);
    return root;
  }, [
    loaded.threeMfGroup,
    inst.rot_x,
    inst.rot_y,
    inst.rot_z,
    ghostMode,
    fitsInVolume,
    extruderColors,
    multimaterialParts,
    partExtruderMap,
  ]);

  useEffect(() => {
    return () => {
      stlBaseResult?.geo.dispose();
    };
  }, [stlBaseResult]);

  useEffect(() => {
    return () => {
      threeMfBaseResult?.traverse((child) => {
        const m = child as THREE.Mesh;
        if (m.isMesh && m.material) {
          if (Array.isArray(m.material)) m.material.forEach((mt) => mt.dispose());
          else m.material.dispose();
        }
      });
    };
  }, [threeMfBaseResult]);

  const gpuScale: [number, number, number] =
    loaded.stlGeo && !isUniform && hasRotation ? [1, 1, 1] : [sx, sz, sy];

  const worldPos: [number, number, number] = [
    inst.offset_x,
    inst.drop_to_bed ? 0 : Math.max(0, inst.offset_z),
    -inst.offset_y,
  ];

  const showMoveGizmo = !ghostMode && isSelected && activeCadTool === 'move';
  const showRotateGizmo = !ghostMode && isSelected && activeCadTool === 'rotate';

  const handleClick = (e: ThreeEvent<MouseEvent>) => {
    if (ghostMode) return;
    e.stopPropagation();
    if (activeCadTool === 'measure' && onSurfaceClick) {
      onSurfaceClick(e.point.clone());
    } else if (!isDraggingGizmo) {
      onSelectInstance();
    }
  };

  const commitGizmo = () => {
    onDraggingChange(false);
    const grp = groupRef.current;
    if (!grp) return;

    if (activeCadTool === 'move') {
      const nextX = Math.round(grp.position.x * 10) / 10;
      const nextY = Math.round(-grp.position.z * 10) / 10;
      const nextZ = inst.drop_to_bed ? 0 : Math.max(0, Math.round(grp.position.y * 10) / 10);
      grp.position.set(nextX, nextZ, -nextY);
      onCommitOffset({ offset_x: nextX, offset_y: nextY, offset_z: nextZ });
    } else if (activeCadTool === 'rotate') {
      // Convertir rotación incremental de gizmo Three.js (Y-up) al marco Z-up de Slicer
      const qThree = grp.quaternion.clone();
      const qZ2Y = new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
      const qY2Z = qZ2Y.clone().invert();
      const qSlicerDelta = qY2Z.multiply(qThree).multiply(qZ2Y);

      const qCur = new THREE.Quaternion().setFromEuler(
        new THREE.Euler(
          THREE.MathUtils.degToRad(inst.rot_x),
          THREE.MathUtils.degToRad(inst.rot_y),
          THREE.MathUtils.degToRad(inst.rot_z),
          'ZYX',
        ),
      );
      const qTotal = qSlicerDelta.multiply(qCur);
      const eOut = new THREE.Euler().setFromQuaternion(qTotal, 'ZYX');
      const normDeg = (rad: number) =>
        Math.round((((THREE.MathUtils.radToDeg(rad) % 360) + 360) % 360) * 10) / 10;
      grp.rotation.set(0, 0, 0);
      grp.position.set(...worldPos);
      onCommitOffset({
        rot_x: normDeg(eOut.x),
        rot_y: normDeg(eOut.y),
        rot_z: normDeg(eOut.z),
      });
    }
  };

  const innerContent = threeMfBaseResult ? (
    <primitive object={threeMfBaseResult} scale={gpuScale} onClick={handleClick} />
  ) : stlBaseResult ? (
    <mesh
      geometry={stlBaseResult.geo}
      scale={gpuScale}
      castShadow={!ghostMode}
      receiveShadow={!ghostMode}
      onClick={handleClick}
    >
      {ghostMode ? (
        <meshBasicMaterial
          color="#22c55e"
          transparent
          opacity={0.16}
          depthWrite={false}
          side={THREE.DoubleSide}
        />
      ) : (
        <meshStandardMaterial
          color={fitsInVolume ? (isSelected ? '#cbd5e1' : '#94a3b8') : '#f87171'}
          emissive={fitsInVolume ? (isSelected ? '#083344' : '#0f172a') : '#450a0a'}
          emissiveIntensity={fitsInVolume ? (isSelected ? 0.22 : 0.08) : 0.25}
          roughness={0.42}
          metalness={0.18}
        />
      )}
    </mesh>
  ) : null;

  return (
    <>
      <group ref={handleGroupRef} position={worldPos}>
        {innerContent}
      </group>
      {(showMoveGizmo || showRotateGizmo) && gizmoTarget && (
        <TransformControls
          object={gizmoTarget}
          mode={showMoveGizmo ? 'translate' : 'rotate'}
          showY={showRotateGizmo || !inst.drop_to_bed}
          size={0.75}
          onMouseDown={() => onDraggingChange(true)}
          onMouseUp={commitGizmo}
        />
      )}
    </>
  );
}

function CutPlaneOverlay({
  cutZMm,
  tiltXDeg,
  tiltYDeg,
  bedSpan,
}: {
  cutZMm: number;
  tiltXDeg: number;
  tiltYDeg: number;
  bedSpan: number;
}) {
  const rotEuler = useMemo(() => {
    const qSlicer = new THREE.Quaternion().setFromEuler(
      new THREE.Euler(THREE.MathUtils.degToRad(tiltXDeg), THREE.MathUtils.degToRad(tiltYDeg), 0, 'XYZ'),
    );
    const qZ2Y = new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0));
    const qThree = qZ2Y.clone().multiply(qSlicer).multiply(qZ2Y.clone().invert());
    return new THREE.Euler().setFromQuaternion(qThree);
  }, [tiltXDeg, tiltYDeg]);

  const boxEdgeGeo = useMemo(() => {
    const b = new THREE.BoxGeometry(bedSpan * 0.85, 0.2, bedSpan * 0.85);
    const e = new THREE.EdgesGeometry(b);
    b.dispose();
    return e;
  }, [bedSpan]);

  useEffect(() => {
    return () => {
      boxEdgeGeo.dispose();
    };
  }, [boxEdgeGeo]);

  return (
    <group position={[0, cutZMm, 0]} rotation={rotEuler}>
      <mesh rotation={[-Math.PI / 2, 0, 0]}>
        <planeGeometry args={[bedSpan * 0.85, bedSpan * 0.85]} />
        <meshBasicMaterial
          color="#06b6d4"
          transparent
          opacity={0.22}
          side={THREE.DoubleSide}
          depthWrite={false}
        />
      </mesh>
      <lineSegments geometry={boxEdgeGeo}>
        <lineBasicMaterial color="#22d3ee" />
      </lineSegments>
    </group>
  );
}

function LayOnFaceMarkers({
  candidates,
  offsetX,
  offsetY,
  offsetZ,
  onPickCandidate,
}: {
  candidates: LayOnFaceCandidate[];
  offsetX: number;
  offsetY: number;
  offsetZ: number;
  onPickCandidate: (cand: LayOnFaceCandidate) => void;
}) {
  const [hoveredId, setHoveredId] = useState<number | null>(null);
  return (
    <group position={[offsetX, offsetZ, -offsetY]}>
      {candidates.map((cand) => {
        const pos = new THREE.Vector3(cand.center[0], cand.center[2], -cand.center[1]);
        const nrm = new THREE.Vector3(
          cand.normal[0],
          cand.normal[2],
          -cand.normal[1],
        ).normalize();
        const quat = new THREE.Quaternion().setFromUnitVectors(
          new THREE.Vector3(0, 0, 1),
          nrm,
        );
        const radius = Math.min(18, Math.max(4.5, Math.sqrt(cand.area_mm2 / Math.PI) * 0.35));
        const isHov = hoveredId === cand.face_id;
        return (
          <mesh
            key={cand.face_id}
            position={pos.clone().addScaledVector(nrm, 0.8)}
            quaternion={quat}
            onPointerOver={(e) => {
              e.stopPropagation();
              setHoveredId(cand.face_id);
            }}
            onPointerOut={() => setHoveredId(null)}
            onClick={(e) => {
              e.stopPropagation();
              onPickCandidate(cand);
            }}
          >
            <circleGeometry args={[radius, 28]} />
            <meshBasicMaterial
              color={isHov ? '#34d399' : '#22d3ee'}
              transparent
              opacity={isHov ? 0.85 : 0.55}
              side={THREE.DoubleSide}
              depthWrite={false}
            />
          </mesh>
        );
      })}
    </group>
  );
}

function MeasureOverlay({ points }: { points: THREE.Vector3[] }) {
  const lineObj = useMemo(() => {
    const g = new THREE.BufferGeometry();
    if (points.length === 2) {
      g.setFromPoints(points);
    }
    const m = new THREE.LineBasicMaterial({ color: '#facc15' });
    return new THREE.Line(g, m);
  }, [points]);

  useEffect(() => {
    return () => {
      lineObj.geometry.dispose();
      (lineObj.material as THREE.Material).dispose();
    };
  }, [lineObj]);

  return (
    <group>
      {points.map((pt, i) => (
        <mesh key={i} position={pt}>
          <sphereGeometry args={[2.2, 16, 16]} />
          <meshBasicMaterial color={i === 0 ? '#22d3ee' : '#f59e0b'} />
        </mesh>
      ))}
      {points.length === 2 && <primitive object={lineObj} />}
    </group>
  );
}

function GcodePreview({
  parsed,
  maxVisibleLayer,
  showTravel,
  colorScheme,
  visibleRoles,
}: {
  parsed: ParsedGcode;
  maxVisibleLayer: number;
  showTravel: boolean;
  colorScheme: GcodeColorScheme;
  visibleRoles: Record<ExtrusionRoleId, boolean>;
}) {
  const activeLayer =
    parsed.layers.length > 0
      ? parsed.layers[Math.min(parsed.layers.length - 1, Math.max(0, maxVisibleLayer - 1))]
      : null;

  useEffect(() => {
    const endIdx = activeLayer ? activeLayer.endIndex : 0;
    parsed.geometry.setDrawRange(0, endIdx);
  }, [parsed, activeLayer]);

  useEffect(() => {
    const attr = parsed.geometry.getAttribute('color') as THREE.BufferAttribute | undefined;
    if (!attr) return;
    let targetArr = parsed.typeColors;
    if (colorScheme === 'tool') targetArr = parsed.toolColors;
    else if (colorScheme === 'speed') targetArr = parsed.speedColors;
    else if (colorScheme === 'flow') targetArr = parsed.flowColors;
    else if (colorScheme === 'temp') targetArr = parsed.tempColors;
    (attr.array as Float32Array).set(targetArr);
    attr.needsUpdate = true;
  }, [parsed, colorScheme]);

  useEffect(() => {
    applyVisibleRolesToGeometry(parsed, visibleRoles);
  }, [parsed, visibleRoles]);

  useEffect(() => {
    return () => {
      parsed.geometry.dispose();
    };
  }, [parsed]);

  const travelGeo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute(
      'position',
      new THREE.BufferAttribute(
        showTravel && activeLayer ? activeLayer.travelPositions : new Float32Array(0),
        3,
      ),
    );
    return g;
  }, [activeLayer, showTravel]);

  useEffect(() => {
    return () => {
      travelGeo.dispose();
    };
  }, [travelGeo]);

  return (
    <group>
      <mesh geometry={parsed.geometry} castShadow receiveShadow>
        <meshStandardMaterial
          vertexColors
          roughness={0.38}
          metalness={0.04}
          side={THREE.DoubleSide}
        />
      </mesh>
      {showTravel && (
        <lineSegments geometry={travelGeo}>
          <lineBasicMaterial color="#94a3b8" transparent opacity={0.45} />
        </lineSegments>
      )}
    </group>
  );
}

export function Viewport3D({
  printer,
  stlFile,
  meshId,
  fitsInVolume,
  recommendedScalePercent,
  transform,
  onChangeTransform,
  onAutoOrient,
  isAutoOrienting = false,
  autoOrientMessage = null,
  orientationsData = null,
  selectedOrientationId = null,
  onSelectOrientation,
  onCloseOrientations,
  onAutoArrange,
  isAutoArranging = false,
  onFetchLayOnFaces,
  onCutMesh,
  isCuttingMesh = false,
  extruderColors,
  multimaterialParts,
  partExtruderMap,
  gcodeText,
  isAnalyzing = false,
  layerPauses = [],
  onAddLayerPause,
  onRemoveLayerPause,
  sceneObjects = [],
  selectedObjectIds = [],
  onSelectObjects,
  onChangeSceneObjects,
  onSplitObjects,
  isSplittingObjects = false,
}: Viewport3DProps) {
  const { t } = useI18n();
  const [viewMode, setViewMode] = useState<'stl' | 'gcode'>('stl');
  const [pauseNoteDraft, setPauseNoteDraft] = useState<string>('');
  const [showPauseInput, setShowPauseInput] = useState<boolean>(false);
  const [isParsingModel, setIsParsingModel] = useState<boolean>(false);
  const [currentLayer, setCurrentLayer] = useState<number>(1);
  const [showTravel, setShowTravel] = useState<boolean>(false);
  const [showGhostMesh, setShowGhostMesh] = useState<boolean>(true);
  const [colorScheme, setColorScheme] = useState<GcodeColorScheme>('type');
  const [visibleRoles, setVisibleRoles] = useState<Record<ExtrusionRoleId, boolean>>({
    0: true,
    1: true,
    2: true,
    3: true,
    4: true,
    5: true,
    6: true,
    7: true,
  });

  // Estado CAD 3D (Vista STL / 3MF)
  const [loadedModel, setLoadedModel] = useState<LoadedRawModel | null>(null);
  const [activeCadTool, setActiveCadTool] = useState<CadToolMode | null>('select');
  const [activeInstanceIdx, setActiveInstanceIdx] = useState<number>(0);
  const [isDraggingGizmo, setIsDraggingGizmo] = useState<boolean>(false);
  const [cloneCount, setCloneCount] = useState<number>(2);
  const [layCandidates, setLayCandidates] = useState<LayOnFaceCandidate[]>([]);
  const [isLoadingFaces, setIsLoadingFaces] = useState<boolean>(false);
  const [cutZMm, setCutZMm] = useState<number>(10);
  const [cutTiltX, setCutTiltX] = useState<number>(0);
  const [cutTiltY, setCutTiltY] = useState<number>(0);
  const [cutKeepMode, setCutKeepMode] = useState<'upper' | 'lower' | 'both'>('both');
  const [measurePoints, setMeasurePoints] = useState<THREE.Vector3[]>([]);

  const [groupScalePct, setGroupScalePct] = useState<number>(100);
  const [marqueeRect, setMarqueeRect] = useState<{
    startX: number;
    startY: number;
    curX: number;
    curY: number;
  } | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const projectorRef = useRef<
    ((pos: [number, number, number]) => { x: number; y: number } | null) | null
  >(null);

  const selectedSet = useMemo(() => new Set(selectedObjectIds), [selectedObjectIds]);
  const selectedSceneObjs = useMemo(
    () => sceneObjects.filter((o) => selectedSet.has(o.object_id)),
    [sceneObjects, selectedSet],
  );
  const groupCentroid = useMemo(() => {
    if (selectedSceneObjs.length === 0) return { x: 0, y: 0, z: 0 };
    const sx = selectedSceneObjs.reduce((acc, o) => acc + o.offset_x, 0);
    const sy = selectedSceneObjs.reduce((acc, o) => acc + o.offset_y, 0);
    const sz = selectedSceneObjs.reduce(
      (acc, o) => acc + (o.drop_to_bed ? 0 : o.offset_z),
      0,
    );
    return {
      x: Math.round((sx / selectedSceneObjs.length) * 10) / 10,
      y: Math.round((sy / selectedSceneObjs.length) * 10) / 10,
      z: Math.round((sz / selectedSceneObjs.length) * 10) / 10,
    };
  }, [selectedSceneObjs]);

  useEffect(() => {
    setGroupScalePct(100);
  }, [selectedObjectIds.join(',')]);

  const handleDeleteSelectedObjects = useCallback(() => {
    if (sceneObjects.length <= 1 || selectedObjectIds.length === 0 || !onChangeSceneObjects) return;
    const rem = sceneObjects.filter((o) => !selectedSet.has(o.object_id));
    if (rem.length === 0) return;
    onChangeSceneObjects(rem);
    onSelectObjects?.([rem[0].object_id]);
  }, [sceneObjects, selectedObjectIds.length, selectedSet, onChangeSceneObjects, onSelectObjects]);

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key !== 'Delete' && ev.key !== 'Backspace') return;
      const tag = (ev.target as HTMLElement | null)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (sceneObjects.length > 1 && selectedObjectIds.length > 0) {
        ev.preventDefault();
        handleDeleteSelectedObjects();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [sceneObjects.length, selectedObjectIds.length, handleDeleteSelectedObjects]);

  const instances = useMemo(() => buildInitialInstances(transform), [transform]);
  const safeIdx = Math.min(instances.length - 1, Math.max(0, activeInstanceIdx));
  const selectedSceneObj =
    selectedSceneObjs.length === 1 ? selectedSceneObjs[0] : null;
  const activeInstance: ModelInstanceTransform = selectedSceneObj
    ? {
        instance_id: selectedSceneObj.object_id,
        offset_x: selectedSceneObj.offset_x,
        offset_y: selectedSceneObj.offset_y,
        offset_z: selectedSceneObj.offset_z,
        scale_percent: selectedSceneObj.scale_percent,
        scale_x: selectedSceneObj.scale_x ?? null,
        scale_y: selectedSceneObj.scale_y ?? null,
        scale_z: selectedSceneObj.scale_z ?? null,
        rot_x: selectedSceneObj.rot_x,
        rot_y: selectedSceneObj.rot_y,
        rot_z: selectedSceneObj.rot_z,
        drop_to_bed: selectedSceneObj.drop_to_bed,
      }
    : instances[safeIdx];
  const uniformScale = transform.uniformScale ?? true;

  // Cargar geometría raw del STL / 3MF una vez por archivo
  useEffect(() => {
    setMeasurePoints([]);
    setLayCandidates([]);
    if (!stlFile) {
      setLoadedModel(null);
      setIsParsingModel(false);
      return;
    }
    let cancelled = false;
    let parsedGeo: THREE.BufferGeometry | null = null;
    let parsedGroup: THREE.Group | null = null;
    const is3mf = stlFile.name.toLowerCase().endsWith('.3mf');
    setIsParsingModel(true);

    stlFile
      .arrayBuffer()
      .then((buffer) => {
        if (cancelled) return;
        if (is3mf) {
          const loader = new ThreeMFLoader();
          const grp = loader.parse(buffer);
          applyThreeMfTrianglePaintGroups(buffer, grp);
          const normRot = new THREE.Matrix4().makeRotationX(-Math.PI / 2);
          const cloneCheck = grp.clone(true);
          cloneCheck.applyMatrix4(normRot);
          cloneCheck.updateMatrixWorld(true);
          const box = new THREE.Box3().setFromObject(cloneCheck);
          const ex: [number, number, number] = !box.isEmpty()
            ? [box.max.x - box.min.x, box.max.z - box.min.z, box.max.y - box.min.y]
            : [50, 50, 50];
          grp.traverse((child) => {
            const m = child as THREE.Mesh;
            if (m.isMesh && m.geometry) m.geometry.computeVertexNormals();
          });
          parsedGroup = grp;
          setLoadedModel({ stlGeo: null, threeMfGroup: grp, baseExtents: ex });
          setCutZMm(Math.max(1, Math.round(ex[2] * 5) / 10));
        } else {
          const loader = new STLLoader();
          const geo = loader.parse(buffer);
          geo.computeBoundingBox();
          const b = geo.boundingBox;
          const ex: [number, number, number] = b
            ? [b.max.x - b.min.x, b.max.y - b.min.y, b.max.z - b.min.z]
            : [50, 50, 50];
          parsedGeo = geo;
          setLoadedModel({ stlGeo: geo, threeMfGroup: null, baseExtents: ex });
          setCutZMm(Math.max(1, Math.round(ex[2] * 5) / 10));
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsParsingModel(false);
        }
      });

    return () => {
      cancelled = true;
      parsedGeo?.dispose();
      parsedGroup?.traverse((child) => {
        const m = child as THREE.Mesh;
        if (m.isMesh) m.geometry?.dispose();
      });
    };
  }, [stlFile]);

  // Dimensiones base (escala 100%) en la rotación actual para convertir % ↔ mm sin clonar mallas al escalar
  const baseDimensionsMm = useMemo<[number, number, number]>(() => {
    if (!loadedModel) return [0, 0, 0];
    if (loadedModel.stlGeo) {
      const { geo, size } = buildTransformedInstanceGeometry(loadedModel.stlGeo, {
        ...activeInstance,
        scale_percent: 100,
        scale_x: null,
        scale_y: null,
        scale_z: null,
      });
      geo.dispose();
      return size;
    }
    if (
      loadedModel.threeMfGroup &&
      (activeInstance.rot_x !== 0 || activeInstance.rot_y !== 0 || activeInstance.rot_z !== 0)
    ) {
      const temp = loadedModel.threeMfGroup.clone(true);
      const euler = new THREE.Euler(
        THREE.MathUtils.degToRad(activeInstance.rot_x),
        THREE.MathUtils.degToRad(activeInstance.rot_y),
        THREE.MathUtils.degToRad(activeInstance.rot_z),
        'ZYX',
      );
      const mat = new THREE.Matrix4()
        .makeRotationX(-Math.PI / 2)
        .multiply(new THREE.Matrix4().makeRotationFromEuler(euler));
      temp.applyMatrix4(mat);
      temp.updateMatrixWorld(true);
      const box = new THREE.Box3().setFromObject(temp);
      if (!box.isEmpty()) {
        return [
          Math.round((box.max.x - box.min.x) * 100) / 100,
          Math.round((box.max.z - box.min.z) * 100) / 100,
          Math.round((box.max.y - box.min.y) * 100) / 100,
        ];
      }
    }
    return loadedModel.baseExtents;
  }, [
    loadedModel,
    activeInstance.rot_x,
    activeInstance.rot_y,
    activeInstance.rot_z,
  ]);

  const activeSizeMm = useMemo<[number, number, number]>(() => {
    const sx = (activeInstance.scale_x ?? activeInstance.scale_percent) / 100;
    const sy = (activeInstance.scale_y ?? activeInstance.scale_percent) / 100;
    const sz = (activeInstance.scale_z ?? activeInstance.scale_percent) / 100;
    return [
      Math.round(baseDimensionsMm[0] * sx * 100) / 100,
      Math.round(baseDimensionsMm[1] * sy * 100) / 100,
      Math.round(baseDimensionsMm[2] * sz * 100) / 100,
    ];
  }, [
    baseDimensionsMm,
    activeInstance.scale_percent,
    activeInstance.scale_x,
    activeInstance.scale_y,
    activeInstance.scale_z,
  ]);

  // Borradores locales tipo string para Redimensionar (evitan llamadas al backend mientras se escribe)
  const formatPctStr = (val: number) => String(Math.round(val * 10) / 10);
  const formatMmStr = (val: number) => String(Math.round(val * 10) / 10);
  const parseDraftNum = (raw: string): number | null => {
    const normalized = raw.trim().replace(',', '.');
    if (!normalized) return null;
    const num = Number(normalized);
    return Number.isFinite(num) ? num : null;
  };

  const [draftGlobalPct, setDraftGlobalPct] = useState<string>(
    formatPctStr(activeInstance.scale_percent),
  );
  const [draftAxisPct, setDraftAxisPct] = useState<[string, string, string]>([
    formatPctStr(activeInstance.scale_x ?? activeInstance.scale_percent),
    formatPctStr(activeInstance.scale_y ?? activeInstance.scale_percent),
    formatPctStr(activeInstance.scale_z ?? activeInstance.scale_percent),
  ]);
  const [draftAxisMm, setDraftAxisMm] = useState<[string, string, string]>([
    formatMmStr(activeSizeMm[0]),
    formatMmStr(activeSizeMm[1]),
    formatMmStr(activeSizeMm[2]),
  ]);

  const syncScaleDraftsFromState = useCallback(() => {
    const pX = activeInstance.scale_x ?? activeInstance.scale_percent;
    const pY = activeInstance.scale_y ?? activeInstance.scale_percent;
    const pZ = activeInstance.scale_z ?? activeInstance.scale_percent;
    setDraftGlobalPct(formatPctStr(activeInstance.scale_percent));
    setDraftAxisPct([formatPctStr(pX), formatPctStr(pY), formatPctStr(pZ)]);
    setDraftAxisMm([
      formatMmStr((baseDimensionsMm[0] * pX) / 100),
      formatMmStr((baseDimensionsMm[1] * pY) / 100),
      formatMmStr((baseDimensionsMm[2] * pZ) / 100),
    ]);
  }, [
    activeInstance.scale_percent,
    activeInstance.scale_x,
    activeInstance.scale_y,
    activeInstance.scale_z,
    baseDimensionsMm,
  ]);

  useEffect(() => {
    syncScaleDraftsFromState();
  }, [safeIdx, uniformScale, syncScaleDraftsFromState]);

  // Refrescar facetas planas cuando se abre Lay on Face o cambia rotación/malla
  useEffect(() => {
    if (activeCadTool === 'lay_on_face' && onFetchLayOnFaces && stlFile) {
      setIsLoadingFaces(true);
      onFetchLayOnFaces()
        .then((cands) => setLayCandidates(cands))
        .catch(() => setLayCandidates([]))
        .finally(() => setIsLoadingFaces(false));
    }
  }, [activeCadTool, meshId, activeInstance.rot_x, activeInstance.rot_y, activeInstance.rot_z]);

  const parsedGcode = useMemo<ParsedGcode | null>(() => {
    if (!gcodeText || !printer) return null;
    const bedX = printer.origin === 'center' ? (printer.diameter_mm ?? 260) : (printer.bed_mm?.[0] ?? 220);
    const bedY = printer.origin === 'center' ? (printer.diameter_mm ?? 260) : (printer.bed_mm?.[1] ?? 220);
    const offX = printer.origin === 'center' ? 0 : bedX / 2;
    const offY = printer.origin === 'center' ? 0 : bedY / 2;
    return parseGcodeLayers(gcodeText, offX, offY, bedX, bedY, extruderColors);
  }, [gcodeText, printer, extruderColors]);

  useEffect(() => {
    if (parsedGcode && parsedGcode.layers.length > 0) {
      setCurrentLayer(parsedGcode.layers.length);
      setViewMode('gcode');
      const isCreator =
        printer?.profile_id === 'creator5_pro' || printer?.printer_id === 'creator5_pro';
      setColorScheme(isCreator ? 'tool' : 'type');
      setVisibleRoles({ 0: true, 1: true, 2: true, 3: true, 4: true, 5: true, 6: true, 7: true });
    } else {
      setViewMode('stl');
    }
  }, [parsedGcode, printer?.profile_id, printer?.printer_id]);

  const applyGroupMoveDelta = useCallback(
    (dx: number, dy: number, dz = 0) => {
      if (sceneObjects.length === 0 || !onChangeSceneObjects) return;
      const targetAll = selectedObjectIds.length === 0;
      onChangeSceneObjects(
        sceneObjects.map((o) => {
          if (!targetAll && !selectedSet.has(o.object_id)) return o;
          return {
            ...o,
            offset_x: Math.round((o.offset_x + dx) * 10) / 10,
            offset_y: Math.round((o.offset_y + dy) * 10) / 10,
            ...(dz !== 0 && !o.drop_to_bed
              ? { offset_z: Math.max(0, Math.round((o.offset_z + dz) * 10) / 10) }
              : {}),
          };
        }),
      );
    },
    [sceneObjects, selectedObjectIds.length, selectedSet, onChangeSceneObjects],
  );

  const applyGroupScaleFactor = useCallback(
    (factor: number, nextGroupPct: number) => {
      if (sceneObjects.length === 0 || !onChangeSceneObjects || factor <= 0) return;
      setGroupScalePct(nextGroupPct);
      const targetAll = selectedObjectIds.length === 0;
      onChangeSceneObjects(
        sceneObjects.map((o) => {
          if (!targetAll && !selectedSet.has(o.object_id)) return o;
          const nextSp = Math.max(5, Math.min(2000, Math.round(o.scale_percent * factor * 10) / 10));
          return {
            ...o,
            scale_percent: nextSp,
            scale_x: o.scale_x ? Math.round(o.scale_x * factor * 10) / 10 : null,
            scale_y: o.scale_y ? Math.round(o.scale_y * factor * 10) / 10 : null,
            scale_z: o.scale_z ? Math.round(o.scale_z * factor * 10) / 10 : null,
            offset_x: Math.round((groupCentroid.x + (o.offset_x - groupCentroid.x) * factor) * 10) / 10,
            offset_y: Math.round((groupCentroid.y + (o.offset_y - groupCentroid.y) * factor) * 10) / 10,
            drop_to_bed: true,
            offset_z: 0,
          };
        }),
      );
    },
    [sceneObjects, selectedObjectIds.length, selectedSet, groupCentroid.x, groupCentroid.y, onChangeSceneObjects],
  );

  const updateActiveInstance = useCallback(
    (patch: Partial<ModelInstanceTransform>, extraRootPatch?: Partial<ModelTransform>) => {
      if (sceneObjects.length > 0 && onChangeSceneObjects) {
        const targetAll = selectedObjectIds.length === 0;
        const nextObjs = sceneObjects.map((o) => {
          if (!targetAll && !selectedSet.has(o.object_id)) return o;
          return {
            ...o,
            ...(patch.offset_x !== undefined ? { offset_x: patch.offset_x } : {}),
            ...(patch.offset_y !== undefined ? { offset_y: patch.offset_y } : {}),
            ...(patch.offset_z !== undefined ? { offset_z: patch.offset_z } : {}),
            ...(patch.rot_x !== undefined ? { rot_x: patch.rot_x } : {}),
            ...(patch.rot_y !== undefined ? { rot_y: patch.rot_y } : {}),
            ...(patch.rot_z !== undefined ? { rot_z: patch.rot_z } : {}),
            ...(patch.scale_percent !== undefined ? { scale_percent: patch.scale_percent } : {}),
            ...(patch.scale_x !== undefined ? { scale_x: patch.scale_x } : {}),
            ...(patch.scale_y !== undefined ? { scale_y: patch.scale_y } : {}),
            ...(patch.scale_z !== undefined ? { scale_z: patch.scale_z } : {}),
            ...(patch.drop_to_bed !== undefined ? { drop_to_bed: patch.drop_to_bed } : {}),
          };
        });
        onChangeSceneObjects(nextObjs);
        return;
      }
      const updated = instances.map((it, idx) =>
        idx === safeIdx ? { ...it, ...patch } : it,
      );
      const act = updated[safeIdx];
      onChangeTransform({
        ...transform,
        ...extraRootPatch,
        scalePercent: act.scale_percent,
        scaleX: act.scale_x ?? undefined,
        scaleY: act.scale_y ?? undefined,
        scaleZ: act.scale_z ?? undefined,
        rotX: act.rot_x,
        rotY: act.rot_y,
        rotZ: act.rot_z,
        offsetX: act.offset_x,
        offsetY: act.offset_y,
        offsetZ: act.drop_to_bed ? 0 : act.offset_z,
        dropToBed: act.drop_to_bed,
        instances: updated,
      });
    },
    [
      sceneObjects,
      selectedObjectIds.length,
      selectedSet,
      onChangeSceneObjects,
      instances,
      safeIdx,
      transform,
      onChangeTransform,
    ],
  );

  const rotateAxis = (axis: 'rot_x' | 'rot_y' | 'rot_z', delta: number) => {
    if (sceneObjects.length > 0 && selectedSceneObjs.length >= 2 && onChangeSceneObjects) {
      onChangeSceneObjects(
        sceneObjects.map((o) => {
          if (!selectedSet.has(o.object_id)) return o;
          const nextVal = Math.round((((o[axis] + delta) % 360) + 360) % 360 * 10) / 10;
          return { ...o, [axis]: nextVal, drop_to_bed: true, offset_z: 0 };
        }),
      );
      return;
    }
    const nextVal = Math.round((((activeInstance[axis] + delta) % 360) + 360) % 360 * 10) / 10;
    updateActiveInstance({
      [axis]: nextVal,
      ...(activeInstance.drop_to_bed ? { offset_z: 0 } : {}),
    });
  };

  const adjustUniformScale = (nextScale: number) => {
    const clamped = Math.max(1.1, Math.min(2000, Math.round(nextScale * 10) / 10));
    updateActiveInstance({
      scale_percent: clamped,
      scale_x: null,
      scale_y: null,
      scale_z: null,
    });
  };

  const handleEditGlobalPct = (raw: string) => {
    setDraftGlobalPct(raw);
    const val = parseDraftNum(raw);
    if (val !== null && val > 0) {
      setDraftAxisPct([raw, raw, raw]);
      setDraftAxisMm([
        formatMmStr((baseDimensionsMm[0] * val) / 100),
        formatMmStr((baseDimensionsMm[1] * val) / 100),
        formatMmStr((baseDimensionsMm[2] * val) / 100),
      ]);
    }
  };

  const handleEditAxisPct = (idx: 0 | 1 | 2, raw: string) => {
    const val = parseDraftNum(raw);
    if (uniformScale) {
      setDraftGlobalPct(raw);
      setDraftAxisPct([raw, raw, raw]);
      if (val !== null && val > 0) {
        setDraftAxisMm([
          formatMmStr((baseDimensionsMm[0] * val) / 100),
          formatMmStr((baseDimensionsMm[1] * val) / 100),
          formatMmStr((baseDimensionsMm[2] * val) / 100),
        ]);
      }
      return;
    }
    setDraftAxisPct((prev) => {
      const next: [string, string, string] = [...prev];
      next[idx] = raw;
      return next;
    });
    if (val !== null && val > 0) {
      setDraftAxisMm((prev) => {
        const next: [string, string, string] = [...prev];
        next[idx] = formatMmStr((baseDimensionsMm[idx] * val) / 100);
        return next;
      });
    }
  };

  const handleEditAxisMm = (idx: 0 | 1 | 2, raw: string) => {
    const mmVal = parseDraftNum(raw);
    const baseMm = Math.max(0.1, baseDimensionsMm[idx]);
    if (uniformScale) {
      if (mmVal !== null && mmVal > 0) {
        const pct = (mmVal / baseMm) * 100;
        const pctStr = formatPctStr(pct);
        setDraftGlobalPct(pctStr);
        setDraftAxisPct([pctStr, pctStr, pctStr]);
        setDraftAxisMm([
          idx === 0 ? raw : formatMmStr((baseDimensionsMm[0] * pct) / 100),
          idx === 1 ? raw : formatMmStr((baseDimensionsMm[1] * pct) / 100),
          idx === 2 ? raw : formatMmStr((baseDimensionsMm[2] * pct) / 100),
        ]);
      } else {
        setDraftAxisMm((prev) => {
          const next: [string, string, string] = [...prev];
          next[idx] = raw;
          return next;
        });
      }
      return;
    }
    setDraftAxisMm((prev) => {
      const next: [string, string, string] = [...prev];
      next[idx] = raw;
      return next;
    });
    if (mmVal !== null && mmVal > 0) {
      const pctStr = formatPctStr((mmVal / baseMm) * 100);
      setDraftAxisPct((prev) => {
        const next: [string, string, string] = [...prev];
        next[idx] = pctStr;
        return next;
      });
    }
  };

  const commitDraftScale = (source?: { kind: 'global' | 'axisPct' | 'axisMm' | 'apply'; idx?: 0 | 1 | 2 }) => {
    if (uniformScale) {
      let targetPct = parseDraftNum(draftGlobalPct);
      if (source?.kind === 'axisPct' && source.idx !== undefined) {
        targetPct = parseDraftNum(draftAxisPct[source.idx]);
      } else if (source?.kind === 'axisMm' && source.idx !== undefined) {
        const mmVal = parseDraftNum(draftAxisMm[source.idx]);
        const baseMm = Math.max(0.1, baseDimensionsMm[source.idx]);
        targetPct = mmVal !== null && mmVal > 0 ? (mmVal / baseMm) * 100 : null;
      }
      if (targetPct === null || targetPct <= 1 || targetPct > 2000) {
        syncScaleDraftsFromState();
        return;
      }
      const rounded = Math.round(targetPct * 10) / 10;
      if (rounded <= 1 || rounded > 2000) {
        syncScaleDraftsFromState();
        return;
      }
      if (
        Math.abs(rounded - activeInstance.scale_percent) > 0.05 ||
        activeInstance.scale_x !== null
      ) {
        adjustUniformScale(rounded);
      } else {
        syncScaleDraftsFromState();
      }
      return;
    }

    const curVec: [number, number, number] = [
      activeInstance.scale_x ?? activeInstance.scale_percent,
      activeInstance.scale_y ?? activeInstance.scale_percent,
      activeInstance.scale_z ?? activeInstance.scale_percent,
    ];
    const parsedVec = [0, 1, 2].map((i) => {
      if (source?.kind === 'axisMm' && source.idx === i) {
        const mmVal = parseDraftNum(draftAxisMm[i]);
        const baseMm = Math.max(0.1, baseDimensionsMm[i]);
        return mmVal !== null && mmVal > 0 ? (mmVal / baseMm) * 100 : null;
      }
      return parseDraftNum(draftAxisPct[i]);
    });
    if (parsedVec.some((v) => v === null || v <= 1 || v > 2000)) {
      syncScaleDraftsFromState();
      return;
    }
    const nextVec = parsedVec.map((v) => Math.round((v as number) * 10) / 10) as [number, number, number];
    if (nextVec.some((v) => v <= 1 || v > 2000)) {
      syncScaleDraftsFromState();
      return;
    }
    const changed = nextVec.some((v, i) => Math.abs(v - curVec[i]) > 0.05);
    if (changed) {
      updateActiveInstance({
        scale_x: nextVec[0],
        scale_y: nextVec[1],
        scale_z: nextVec[2],
      });
    } else {
      syncScaleDraftsFromState();
    }
  };

  const isAllDropToBed =
    sceneObjects.length > 0 && selectedSceneObjs.length > 0
      ? selectedSceneObjs.every((o) => o.drop_to_bed)
      : activeInstance.drop_to_bed;

  const handleToggleGravity = () => {
    const nextDrop = !isAllDropToBed;
    if (sceneObjects.length > 0 && onChangeSceneObjects) {
      const targetAll = selectedObjectIds.length === 0;
      onChangeSceneObjects(
        sceneObjects.map((o) => {
          if (!targetAll && !selectedSet.has(o.object_id)) return o;
          return {
            ...o,
            drop_to_bed: nextDrop,
            ...(nextDrop ? { offset_z: 0 } : {}),
          };
        }),
      );
      return;
    }
    updateActiveInstance({
      drop_to_bed: nextDrop,
      offset_z: nextDrop ? 0 : activeInstance.offset_z,
    });
  };

  const handleCloneCopies = (countToAdd: number) => {
    const n = Math.max(1, Math.min(20, countToAdd));
    const additions: ModelInstanceTransform[] = [];
    for (let k = 0; k < n; k++) {
      const idx = instances.length + k + 1;
      const col = (idx - 1) % 3;
      const row = Math.floor((idx - 1) / 3);
      additions.push({
        ...activeInstance,
        instance_id: `inst_${Date.now()}_${idx}`,
        offset_x: Math.round((activeInstance.offset_x + (col - 1) * (activeSizeMm[0] + 10)) * 10) / 10,
        offset_y: Math.round((activeInstance.offset_y + row * (activeSizeMm[1] + 10)) * 10) / 10,
      });
    }
    const nextInstances = [...instances, ...additions];
    onChangeTransform({ ...transform, instances: nextInstances });
    if (onAutoArrange) {
      void onAutoArrange(nextInstances);
    }
  };

  const handleRemoveInstance = (idxToRemove: number) => {
    if (instances.length <= 1) return;
    const next = instances.filter((_, i) => i !== idxToRemove);
    setActiveInstanceIdx(Math.max(0, Math.min(next.length - 1, idxToRemove)));
    onChangeTransform({ ...transform, instances: next });
  };

  const handleMeasureClick = (pt: THREE.Vector3) => {
    setMeasurePoints((prev) => (prev.length >= 2 ? [pt] : [...prev, pt]));
  };

  const measureMetrics = useMemo(() => {
    if (measurePoints.length !== 2) return null;
    const [p1, p2] = measurePoints;
    const dx = Math.abs(p2.x - p1.x);
    const dy = Math.abs(-(p2.z - p1.z));
    const dz = Math.abs(p2.y - p1.y);
    const dist = Math.hypot(dx, dy, dz);
    const angle = (Math.atan2(dz, Math.hypot(dx, dy)) * 180) / Math.PI;
    return {
      dist: dist.toFixed(2),
      dx: dx.toFixed(2),
      dy: dy.toFixed(2),
      dz: dz.toFixed(2),
      angle: angle.toFixed(1),
    };
  }, [measurePoints]);

  const totalLayers = parsedGcode?.layers.length ?? 0;
  const activeLayerData =
    parsedGcode && currentLayer >= 1 && currentLayer <= totalLayers
      ? parsedGcode.layers[currentLayer - 1]
      : null;

  const bedSpan =
    printer?.origin === 'center'
      ? (printer?.diameter_mm ?? 260)
      : Math.max(printer?.bed_mm?.[0] ?? 220, printer?.bed_mm?.[1] ?? 220);

  return (
    <div
      ref={containerRef}
      onPointerDown={(e) => {
        if (e.button !== 0 || viewMode !== 'stl' || sceneObjects.length === 0) return;
        if (e.shiftKey && e.target instanceof HTMLCanvasElement) {
          const rect = containerRef.current?.getBoundingClientRect();
          if (!rect) return;
          const x = e.clientX - rect.left;
          const y = e.clientY - rect.top;
          setMarqueeRect({ startX: x, startY: y, curX: x, curY: y });
        }
      }}
      onPointerMove={(e) => {
        if (!marqueeRect) return;
        const rect = containerRef.current?.getBoundingClientRect();
        if (!rect) return;
        setMarqueeRect((prev) =>
          prev ? { ...prev, curX: e.clientX - rect.left, curY: e.clientY - rect.top } : null,
        );
      }}
      onPointerUp={() => {
        if (!marqueeRect) return;
        const minX = Math.min(marqueeRect.startX, marqueeRect.curX);
        const maxX = Math.max(marqueeRect.startX, marqueeRect.curX);
        const minY = Math.min(marqueeRect.startY, marqueeRect.curY);
        const maxY = Math.max(marqueeRect.startY, marqueeRect.curY);
        if (maxX - minX > 6 || maxY - minY > 6) {
          const proj = projectorRef.current;
          if (proj) {
            const hits = sceneObjects
              .filter((obj) => {
                const pt = proj([obj.offset_x, (obj.dimensions_mm?.[2] || 10) * 0.4, -obj.offset_y]);
                return pt && pt.x >= minX && pt.x <= maxX && pt.y >= minY && pt.y <= maxY;
              })
              .map((obj) => obj.object_id);
            if (hits.length > 0) {
              onSelectObjects?.(hits);
            }
          }
        }
        setMarqueeRect(null);
      }}
      className="relative h-full w-full overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl"
    >
      {marqueeRect && (
        <div
          style={{
            left: Math.min(marqueeRect.startX, marqueeRect.curX),
            top: Math.min(marqueeRect.startY, marqueeRect.curY),
            width: Math.abs(marqueeRect.curX - marqueeRect.startX),
            height: Math.abs(marqueeRect.curY - marqueeRect.startY),
          }}
          className="pointer-events-none absolute z-30 border border-dashed border-cyan-400 bg-cyan-400/15"
        />
      )}
      {/* Contenedor superior HUD + Submenú CAD (flujo vertical para evitar solapamientos) */}
      <div className="pointer-events-none absolute inset-x-4 top-4 z-20 flex flex-col items-start gap-2.5">
        {/* Barra superior HUD */}
        <div className="flex w-full flex-wrap items-center justify-between gap-2">
        <div className="pointer-events-auto flex items-center gap-2 rounded-xl border border-slate-800/90 bg-slate-900/90 px-3 py-1.5 backdrop-blur">
          <span className="h-2 w-2 rounded-full bg-cyan-400" />
          <span className="text-xs font-medium text-slate-200">
            {printer ? printer.display_name : 'Cargando impresora...'}
            {printer?.ip ? (
              <span className="ml-1.5 font-mono text-[11px] text-emerald-300">
                · {printer.ip}
              </span>
            ) : null}
          </span>
          {printer && (
            <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[11px] text-slate-400">
              {printer.kinematics === 'delta'
                ? `Ø${printer.diameter_mm}×${printer.height_mm} mm`
                : `${printer.bed_mm?.join('×')} mm`}
            </span>
          )}
        </div>

        {/* Barra de Herramientas CAD 3D (activa en Vista STL / 3MF cuando hay archivo) */}
        {stlFile && viewMode === 'stl' && (
          <div className="pointer-events-auto flex flex-wrap items-center gap-1 rounded-xl border border-slate-800/95 bg-slate-900/90 p-1 backdrop-blur">
            {(
              [
                ['select', t.step2.select, MousePointerClick],
                ['move', t.step2.move, Move],
                ['rotate', t.step2.rotate, RotateCw],
                ['scale', t.step2.scale, Scaling],
                ['lay_on_face', t.step2.place, FlipVertical2],
                ['cut', t.step2.cut, Scissors],
                ['measure', t.step2.measure, Ruler],
              ] as const
            ).map(([toolId, label, Icon]) => {
              const active = activeCadTool === toolId;
              return (
                <button
                  key={toolId}
                  type="button"
                  title={label}
                  onClick={() =>
                    setActiveCadTool((cur) => (cur === toolId ? null : toolId))
                  }
                  className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-medium transition ${
                    active
                      ? 'bg-cyan-500/25 text-cyan-200 ring-1 ring-cyan-500/50'
                      : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span className="hidden xl:inline">{label.split(' ')[0]}</span>
                </button>
              );
            })}

            <div className="mx-0.5 h-4 w-px bg-slate-700" />

            <button
              type="button"
              onClick={handleToggleGravity}
              title="Gravedad: caer automáticamente sobre Z = 0.0 mm"
              className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold transition ${
                isAllDropToBed
                  ? 'bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40'
                  : 'bg-slate-800 text-slate-300 ring-1 ring-slate-600/60'
              }`}
            >
              <ArrowDownToLine className="h-3.5 w-3.5" />
              <span>Z=0 {isAllDropToBed ? 'ON' : 'OFF'}</span>
            </button>

            {onSplitObjects && (
              <button
                type="button"
                disabled={isSplittingObjects}
                onClick={() => void onSplitObjects()}
                title="Dividir malla en objetos independientes"
                className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950/70 px-2 py-1 text-[11px] font-medium text-purple-200 hover:border-purple-500/60 disabled:opacity-50"
              >
                {isSplittingObjects ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Layers className="h-3.5 w-3.5" />
                )}
                <span>{t.step2.splitObjects}</span>
              </button>
            )}

            {(onAutoArrange || sceneObjects.length > 1) && (
              <button
                type="button"
                disabled={isAutoArranging}
                onClick={() => {
                  if (sceneObjects.length > 1 && onChangeSceneObjects) {
                    const useSelection =
                      selectedObjectIds.length >= 2 &&
                      selectedObjectIds.length < sceneObjects.length;
                    const targetSetIds = useSelection
                      ? new Set(selectedObjectIds)
                      : new Set(sceneObjects.map((o) => o.object_id));
                    onChangeSceneObjects(
                      arrangeSceneObjectsOnBed(sceneObjects, targetSetIds, printer),
                    );
                  } else if (onAutoArrange) {
                    void onAutoArrange(instances);
                  }
                }}
                title="Auto-Ordenar piezas en la cama"
                className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950/70 px-2 py-1 text-[11px] font-medium text-cyan-200 hover:border-cyan-500/60 disabled:opacity-50"
              >
                {isAutoArranging ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <LayoutGrid className="h-3.5 w-3.5" />
                )}
                <span>Ordenar</span>
              </button>
            )}
          </div>
        )}

        {parsedGcode && totalLayers > 0 && (
          <div className="pointer-events-auto flex items-center gap-1.5 rounded-xl border border-slate-800/90 bg-slate-900/90 p-1 backdrop-blur">
            <button
              type="button"
              onClick={() => setViewMode('stl')}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                viewMode === 'stl'
                  ? 'bg-cyan-500/20 text-cyan-300'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Box className="h-3.5 w-3.5" />
              Vista STL / 3MF
            </button>
            <button
              type="button"
              onClick={() => setViewMode('gcode')}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                viewMode === 'gcode'
                  ? 'bg-orange-500/20 text-orange-300'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layers className="h-3.5 w-3.5" />
              Vista de laminado ({totalLayers})
            </button>
          </div>
        )}
      </div>

        {/* Submenú flotante CAD activo (Vista STL / 3MF) */}
        {stlFile && viewMode === 'stl' && activeCadTool && (
          <div className="pointer-events-auto max-h-[60vh] w-72 space-y-2 overflow-y-auto rounded-2xl border border-slate-800/95 bg-slate-900/92 p-3 text-xs shadow-2xl backdrop-blur">
            <div className="flex items-center justify-between border-b border-slate-800/80 pb-1.5">
              <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Herramienta CAD
              </span>
              <button
                type="button"
                onClick={() => setActiveCadTool(null)}
                title="Cerrar panel de herramienta"
                aria-label="Cerrar panel de herramienta"
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-slate-400 transition hover:bg-slate-800 hover:text-slate-100"
              >
                <span>Cerrar</span>
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          {activeCadTool === 'select' && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">
                  Instancias en Plato ({instances.length})
                </span>
                <button
                  type="button"
                  onClick={() => handleCloneCopies(1)}
                  className="flex items-center gap-1 rounded-md border border-cyan-500/40 bg-cyan-500/15 px-2 py-0.5 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
                >
                  <CopyPlus className="h-3 w-3" />
                  +1
                </button>
              </div>

              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-slate-400">Clonar</span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={cloneCount}
                  onChange={(e) => setCloneCount(Math.max(1, Number(e.target.value) || 1))}
                  className="w-12 rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-center font-mono text-xs text-slate-100"
                />
                <button
                  type="button"
                  onClick={() => handleCloneCopies(cloneCount)}
                  className="flex-1 rounded-lg bg-cyan-500/20 py-1 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/30"
                >
                  Multiplicar + Ordenar
                </button>
              </div>

              <div className="max-h-36 space-y-1 overflow-y-auto pr-0.5">
                {sceneObjects.length > 0 ? (
                  <>
                    <div className="mb-1 flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => onSelectObjects?.(sceneObjects.map((o) => o.object_id))}
                        className="flex-1 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-1.5 py-1 text-[10px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
                      >
                        Seleccionar Todo ({sceneObjects.length})
                      </button>
                      <button
                        type="button"
                        onClick={() => onSelectObjects?.([])}
                        className="rounded-lg border border-slate-700 bg-slate-950 px-1.5 py-1 text-[10px] text-slate-300 hover:border-slate-500"
                      >
                        Deseleccionar
                      </button>
                      {selectedObjectIds.length > 0 && sceneObjects.length > 1 && (
                        <button
                          type="button"
                          onClick={handleDeleteSelectedObjects}
                          title="Eliminar piezas seleccionadas (Supr)"
                          className="rounded-lg border border-rose-500/45 bg-rose-500/15 px-1.5 py-1 text-[10px] font-semibold text-rose-200 hover:bg-rose-500/25"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                    {sceneObjects.map((obj) => {
                      const isSel = selectedSet.has(obj.object_id);
                      return (
                        <div
                          key={obj.object_id}
                          onClick={(e) => {
                            if (e.shiftKey || e.metaKey || e.ctrlKey) {
                              onSelectObjects?.(
                                isSel
                                  ? selectedObjectIds.filter((id) => id !== obj.object_id)
                                  : [...selectedObjectIds, obj.object_id],
                              );
                            } else {
                              onSelectObjects?.([obj.object_id]);
                            }
                          }}
                          className={`flex cursor-pointer items-center justify-between gap-1.5 rounded-lg border px-2 py-1 text-[11px] ${
                            isSel
                              ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-100'
                              : 'border-slate-800 bg-slate-950/70 text-slate-300'
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={isSel}
                            onChange={(e) => {
                              e.stopPropagation();
                              onSelectObjects?.(
                                isSel
                                  ? selectedObjectIds.filter((id) => id !== obj.object_id)
                                  : [...selectedObjectIds, obj.object_id],
                              );
                            }}
                            onClick={(e) => e.stopPropagation()}
                            className="accent-cyan-400"
                          />
                          <span className="min-w-0 flex-1 truncate">
                            {obj.name} · ({obj.offset_x}, {obj.offset_y})
                          </span>
                        </div>
                      );
                    })}
                  </>
                ) : (
                  instances.map((it, idx) => (
                  <div
                    key={it.instance_id}
                    onClick={() => setActiveInstanceIdx(idx)}
                    className={`flex cursor-pointer items-center justify-between rounded-lg border px-2 py-1 text-[11px] ${
                      idx === safeIdx
                        ? 'border-cyan-500/60 bg-cyan-500/15 text-cyan-100'
                        : 'border-slate-800 bg-slate-950/70 text-slate-300'
                    }`}
                  >
                    <span>
                      Pieza #{idx + 1} · ({it.offset_x}, {it.offset_y}) mm
                    </span>
                    {instances.length > 1 && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleRemoveInstance(idx);
                        }}
                        className="text-slate-500 hover:text-rose-400"
                        title="Eliminar copia"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                ))
                )}
              </div>
            </>
          )}

          {activeCadTool === 'move' && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">
                  {selectedSceneObjs.length >= 2
                    ? `Mover ${selectedSceneObjs.length} piezas seleccionadas`
                    : `Mover Pieza (mm)`}
                </span>
                <button
                  type="button"
                  onClick={() => {
                    if (selectedSceneObjs.length >= 2) {
                      applyGroupMoveDelta(-groupCentroid.x, -groupCentroid.y);
                    } else {
                      updateActiveInstance({ offset_x: 0, offset_y: 0, offset_z: 0 });
                    }
                  }}
                  className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500"
                >
                  {selectedSceneObjs.length >= 2 ? 'Centrar grupo' : 'Centrar'}
                </button>
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">
                    {selectedSceneObjs.length >= 2 ? 'Cx (mm)' : 'X (mm)'}
                  </label>
                  <input
                    type="number"
                    step={1}
                    value={selectedSceneObjs.length >= 2 ? groupCentroid.x : activeInstance.offset_x}
                    onChange={(e) => {
                      const val = Number(e.target.value) || 0;
                      if (selectedSceneObjs.length >= 2) {
                        applyGroupMoveDelta(val - groupCentroid.x, 0);
                      } else {
                        updateActiveInstance({ offset_x: val });
                      }
                    }}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-1.5 py-1 font-mono text-xs text-slate-100"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">
                    {selectedSceneObjs.length >= 2 ? 'Cy (mm)' : 'Y (mm)'}
                  </label>
                  <input
                    type="number"
                    step={1}
                    value={selectedSceneObjs.length >= 2 ? groupCentroid.y : activeInstance.offset_y}
                    onChange={(e) => {
                      const val = Number(e.target.value) || 0;
                      if (selectedSceneObjs.length >= 2) {
                        applyGroupMoveDelta(0, val - groupCentroid.y);
                      } else {
                        updateActiveInstance({ offset_y: val });
                      }
                    }}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-1.5 py-1 font-mono text-xs text-slate-100"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">
                    {selectedSceneObjs.length >= 2
                      ? isAllDropToBed
                        ? 'Cz (Fija)'
                        : 'Cz (mm)'
                      : `Z ${isAllDropToBed ? '(Fija)' : '(mm)'}`}
                  </label>
                  <input
                    type="number"
                    min={0}
                    step={1}
                    disabled={isAllDropToBed}
                    value={
                      isAllDropToBed
                        ? 0
                        : selectedSceneObjs.length >= 2
                          ? groupCentroid.z
                          : activeInstance.offset_z
                    }
                    onChange={(e) => {
                      const val = Math.max(0, Number(e.target.value) || 0);
                      if (selectedSceneObjs.length >= 2) {
                        applyGroupMoveDelta(0, 0, val - groupCentroid.z);
                      } else {
                        updateActiveInstance({ offset_z: val });
                      }
                    }}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-1.5 py-1 font-mono text-xs text-slate-100 disabled:opacity-45"
                  />
                </div>
              </div>
              <p className="text-[10px] text-slate-400">
                Usa el gizmo 3D sobre la pieza o ajusta coordenadas exactas.
              </p>
            </>
          )}

          {activeCadTool === 'rotate' && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">Rotar (°)</span>
                <button
                  type="button"
                  onClick={() => updateActiveInstance({ rot_x: 0, rot_y: 0, rot_z: 0 })}
                  className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300"
                >
                  Reset 0°
                </button>
              </div>
              {(
                [
                  ['rot_x', 'Eje X'],
                  ['rot_y', 'Eje Y'],
                  ['rot_z', 'Eje Z'],
                ] as const
              ).map(([axisKey, label]) => (
                <div key={axisKey} className="flex items-center justify-between gap-1.5">
                  <span className="w-10 text-[11px] text-slate-400">{label}</span>
                  <button
                    type="button"
                    onClick={() => rotateAxis(axisKey, -90)}
                    className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500"
                  >
                    -90°
                  </button>
                  <button
                    type="button"
                    onClick={() => rotateAxis(axisKey, -45)}
                    className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500"
                  >
                    -45°
                  </button>
                  <input
                    type="number"
                    step={5}
                    value={Math.round(activeInstance[axisKey] * 10) / 10}
                    onChange={(e) =>
                      updateActiveInstance({
                        [axisKey]: (((Number(e.target.value) || 0) % 360) + 360) % 360,
                      })
                    }
                    className="w-14 rounded border border-slate-700 bg-slate-950 px-1 py-0.5 text-center font-mono text-xs text-cyan-300"
                  />
                  <button
                    type="button"
                    onClick={() => rotateAxis(axisKey, 45)}
                    className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500"
                  >
                    +45°
                  </button>
                  <button
                    type="button"
                    onClick={() => rotateAxis(axisKey, 90)}
                    className="rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 text-[10px] text-slate-300 hover:border-cyan-500"
                  >
                    +90°
                  </button>
                </div>
              ))}
              <button
                type="button"
                disabled={isAutoOrienting}
                onClick={onAutoOrient}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg border border-emerald-500/45 bg-emerald-500/15 py-1.5 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/25 disabled:opacity-50"
              >
                {isAutoOrienting ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Compass className="h-3.5 w-3.5" />
                )}
                Auto-Orientar sin Escalar
              </button>
            </>
          )}

          {activeCadTool === 'scale' && selectedSceneObjs.length >= 2 && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">
                  Redimensionar {selectedSceneObjs.length} piezas
                </span>
                <span className="font-mono text-[10px] text-cyan-300">
                  {groupScalePct}%
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <button
                  type="button"
                  onClick={() => {
                    const nextPct = Math.max(10, groupScalePct - 10);
                    applyGroupScaleFactor(nextPct / groupScalePct, nextPct);
                  }}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300 hover:border-cyan-500/60"
                >
                  -10%
                </button>
                <input
                  type="number"
                  min={10}
                  max={500}
                  step={5}
                  value={groupScalePct}
                  onChange={(e) => {
                    const nextPct = Math.max(10, Math.min(500, Number(e.target.value) || 100));
                    applyGroupScaleFactor(nextPct / groupScalePct, nextPct);
                  }}
                  className="w-full rounded border border-slate-700 bg-slate-950 px-2 py-1 text-center font-mono text-xs text-cyan-300"
                />
                <button
                  type="button"
                  onClick={() => {
                    const nextPct = Math.min(500, groupScalePct + 10);
                    applyGroupScaleFactor(nextPct / groupScalePct, nextPct);
                  }}
                  className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300 hover:border-cyan-500/60"
                >
                  +10%
                </button>
              </div>
              <p className="text-[10px] text-slate-400">
                Escala proporcionalmente alrededor del centroide manteniendo separación.
              </p>
            </>
          )}

          {activeCadTool === 'scale' && selectedSceneObjs.length < 2 && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">Redimensionar</span>
                <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-slate-300">
                  <input
                    type="checkbox"
                    checked={uniformScale}
                    onChange={(e) => {
                      const uni = e.target.checked;
                      updateActiveInstance(
                        uni
                          ? { scale_x: null, scale_y: null, scale_z: null }
                          : {
                              scale_x: activeInstance.scale_percent,
                              scale_y: activeInstance.scale_percent,
                              scale_z: activeInstance.scale_percent,
                            },
                        { uniformScale: uni },
                      );
                    }}
                    className="accent-cyan-500"
                  />
                  Escala uniforme
                </label>
              </div>

              {uniformScale ? (
                <div className="flex items-center gap-1.5">
                  <button
                    type="button"
                    onClick={() => adjustUniformScale(activeInstance.scale_percent - 10)}
                    className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300 hover:border-cyan-500/60"
                  >
                    -10%
                  </button>
                  <div className="flex flex-1 items-center rounded border border-slate-700 bg-slate-950 px-2 py-1 focus-within:border-cyan-400">
                    <input
                      type="text"
                      inputMode="decimal"
                      aria-label="Escala global (%)"
                      value={draftGlobalPct}
                      onChange={(e) => handleEditGlobalPct(e.target.value)}
                      onBlur={() => commitDraftScale({ kind: 'global' })}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          commitDraftScale({ kind: 'global' });
                        } else if (e.key === 'Escape') {
                          syncScaleDraftsFromState();
                        }
                      }}
                      className="w-full bg-transparent text-right font-mono text-xs text-slate-100 focus:outline-none"
                    />
                    <span className="ml-1 text-[11px] text-slate-400">%</span>
                  </div>
                  <button
                    type="button"
                    onClick={() => adjustUniformScale(activeInstance.scale_percent + 10)}
                    className="rounded border border-slate-700 bg-slate-950 px-2 py-1 text-slate-300 hover:border-cyan-500/60"
                  >
                    +10%
                  </button>
                </div>
              ) : null}

              <div className="space-y-1.5">
                {(['X', 'Y', 'Z'] as const).map((label, rawIdx) => {
                  const idx = rawIdx as 0 | 1 | 2;
                  return (
                    <div key={label} className="grid grid-cols-[20px_1fr_1fr] items-center gap-1.5">
                      <span className="font-mono text-[11px] text-slate-400">{label}</span>
                      <div className="flex items-center rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 focus-within:border-cyan-400">
                        <input
                          type="text"
                          inputMode="decimal"
                          aria-label={`Escala ${label} (%)`}
                          value={draftAxisPct[idx]}
                          onChange={(e) => handleEditAxisPct(idx, e.target.value)}
                          onBlur={() => commitDraftScale({ kind: 'axisPct', idx })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              commitDraftScale({ kind: 'axisPct', idx });
                            } else if (e.key === 'Escape') {
                              syncScaleDraftsFromState();
                            }
                          }}
                          className="w-full bg-transparent text-right font-mono text-[11px] text-slate-100 focus:outline-none"
                        />
                        <span className="ml-0.5 text-[10px] text-slate-500">%</span>
                      </div>
                      <div className="flex items-center rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 focus-within:border-cyan-400">
                        <input
                          type="text"
                          inputMode="decimal"
                          aria-label={`Tamaño ${label} (mm)`}
                          value={draftAxisMm[idx]}
                          onChange={(e) => handleEditAxisMm(idx, e.target.value)}
                          onBlur={() => commitDraftScale({ kind: 'axisMm', idx })}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              e.preventDefault();
                              commitDraftScale({ kind: 'axisMm', idx });
                            } else if (e.key === 'Escape') {
                              syncScaleDraftsFromState();
                            }
                          }}
                          className="w-full bg-transparent text-right font-mono text-[11px] text-cyan-300 focus:outline-none"
                        />
                        <span className="ml-0.5 text-[10px] text-slate-500">mm</span>
                      </div>
                    </div>
                  );
                })}
              </div>

              <div className="grid grid-cols-[auto_1fr] gap-1.5">
                <button
                  type="button"
                  onClick={() => commitDraftScale({ kind: 'apply' })}
                  className="rounded-lg border border-emerald-500/50 bg-emerald-500/20 px-3 py-1.5 text-[11px] font-semibold text-emerald-100 hover:bg-emerald-500/30"
                >
                  Aplicar
                </button>
                <button
                  type="button"
                  onClick={() => adjustUniformScale(recommendedScalePercent)}
                  className="flex items-center justify-center gap-1.5 rounded-lg border border-cyan-500/45 bg-cyan-500/15 py-1.5 text-[11px] font-semibold text-cyan-200 hover:bg-cyan-500/25"
                >
                  <Maximize2 className="h-3.5 w-3.5" />
                  Auto-Ajustar ({recommendedScalePercent}%)
                </button>
              </div>
            </>
          )}

          {activeCadTool === 'lay_on_face' && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">
                  Colocar en Cara (Casco Convexo)
                </span>
                {isLoadingFaces && <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />}
              </div>
              <p className="text-[10px] text-slate-400">
                Haz clic en una faceta iluminada en el 3D o en la lista para apoyarla plana sobre Z = 0.
              </p>
              <div className="max-h-36 space-y-1 overflow-y-auto pr-0.5">
                {layCandidates.slice(0, 8).map((cand) => (
                  <button
                    key={cand.face_id}
                    type="button"
                    onClick={() =>
                      updateActiveInstance({
                        rot_x: cand.rot_x,
                        rot_y: cand.rot_y,
                        rot_z: cand.rot_z,
                        drop_to_bed: true,
                        offset_z: 0,
                      })
                    }
                    className="flex w-full items-center justify-between rounded-lg border border-slate-800 bg-slate-950 px-2 py-1 text-left text-[11px] text-slate-200 hover:border-emerald-500/60"
                  >
                    <span>Cara #{cand.face_id + 1}</span>
                    <span className="font-mono text-[10px] text-emerald-300">
                      {cand.area_mm2.toFixed(0)} mm²
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}

          {activeCadTool === 'cut' && (
            <>
              <span className="block font-semibold text-slate-100">
                Cortar Modelo por Plano
              </span>
              <div>
                <div className="mb-0.5 flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">Altura Z (mm)</span>
                  <span className="font-mono text-cyan-300">
                    {cutZMm.toFixed(1)} / {activeSizeMm[2].toFixed(1)} mm
                  </span>
                </div>
                <input
                  type="range"
                  min={0.5}
                  max={Math.max(1, activeSizeMm[2] - 0.5)}
                  step={0.5}
                  value={cutZMm}
                  onChange={(e) => setCutZMm(Number(e.target.value))}
                  className="w-full cursor-pointer accent-cyan-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-1.5">
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Inclin. X (°)</label>
                  <input
                    type="number"
                    min={-45}
                    max={45}
                    value={cutTiltX}
                    onChange={(e) => setCutTiltX(Number(e.target.value) || 0)}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono text-xs text-slate-100"
                  />
                </div>
                <div>
                  <label className="mb-0.5 block text-[10px] text-slate-400">Inclin. Y (°)</label>
                  <input
                    type="number"
                    min={-45}
                    max={45}
                    value={cutTiltY}
                    onChange={(e) => setCutTiltY(Number(e.target.value) || 0)}
                    className="w-full rounded border border-slate-700 bg-slate-950 px-1.5 py-0.5 font-mono text-xs text-slate-100"
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-1">
                {(
                  [
                    ['upper', 'Superior'],
                    ['lower', 'Inferior'],
                    ['both', 'Ambas'],
                  ] as const
                ).map(([m, lbl]) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setCutKeepMode(m)}
                    className={`rounded-md border py-1 text-[10px] font-semibold ${
                      cutKeepMode === m
                        ? 'border-cyan-500 bg-cyan-500/20 text-cyan-200'
                        : 'border-slate-800 bg-slate-950 text-slate-400'
                    }`}
                  >
                    {lbl}
                  </button>
                ))}
              </div>

              {onCutMesh && (
                <button
                  type="button"
                  disabled={isCuttingMesh}
                  onClick={() =>
                    void onCutMesh({
                      cutZMm,
                      tiltXDeg: cutTiltX,
                      tiltYDeg: cutTiltY,
                      keepMode: cutKeepMode,
                    })
                  }
                  className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-cyan-500/25 py-1.5 text-[11px] font-semibold text-cyan-100 hover:bg-cyan-500/35 disabled:opacity-50"
                >
                  {isCuttingMesh ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Scissors className="h-3.5 w-3.5" />
                  )}
                  Ejecutar Corte Cerrado
                </button>
              )}
            </>
          )}

          {activeCadTool === 'measure' && (
            <>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-slate-100">Medir (Regla 3D)</span>
                <button
                  type="button"
                  onClick={() => setMeasurePoints([])}
                  className="rounded border border-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300"
                >
                  Limpiar
                </button>
              </div>
              <p className="text-[10px] text-slate-400">
                Haz clic en 2 puntos de la superficie del modelo ({measurePoints.length}/2).
              </p>
              {measureMetrics && (
                <div className="space-y-1 rounded-lg border border-amber-500/35 bg-amber-500/10 p-2 font-mono text-[11px] text-amber-100">
                  <div className="flex justify-between font-bold text-amber-300">
                    <span>Distancia:</span>
                    <span>{measureMetrics.dist} mm</span>
                  </div>
                  <div className="flex justify-between text-[10px] text-slate-300">
                    <span>ΔX {measureMetrics.dx}</span>
                    <span>ΔY {measureMetrics.dy}</span>
                    <span>ΔZ {measureMetrics.dz}</span>
                  </div>
                  <div className="flex justify-between text-[10px] text-cyan-300">
                    <span>Ángulo plano XY:</span>
                    <span>{measureMetrics.angle}°</span>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
      </div>

      {/* Barra inferior compacta cuando está en Vista STL */}
      {stlFile && viewMode === 'stl' && (
        <div className="pointer-events-auto absolute inset-x-4 bottom-4 z-10 flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-slate-800/95 bg-slate-900/90 px-3 py-2 backdrop-blur">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-mono text-[11px] text-slate-300">
              {activeSizeMm[0]}×{activeSizeMm[1]}×{activeSizeMm[2]} mm
            </span>
            {autoOrientMessage && (
              <span className="rounded bg-cyan-500/15 px-2 py-0.5 text-[11px] text-cyan-200">
                {autoOrientMessage}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => adjustUniformScale(recommendedScalePercent)}
              className={`flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs font-semibold transition ${
                !fitsInVolume
                  ? 'border-amber-400/70 bg-amber-500/20 text-amber-200'
                  : 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20'
              }`}
            >
              <Maximize2 className="h-3.5 w-3.5" />
              Auto-Ajustar a Cama
            </button>
            <button
              type="button"
              disabled={isAutoOrienting}
              onClick={onAutoOrient}
              className="flex items-center gap-1 rounded-lg border border-emerald-500/45 bg-emerald-500/10 px-2.5 py-1 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20 disabled:opacity-50"
            >
              {isAutoOrienting ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Compass className="h-3.5 w-3.5" />
              )}
              Auto-Orientar
            </button>
            <button
              type="button"
              onClick={() =>
                onChangeTransform({
                  scalePercent: 100,
                  rotX: 0,
                  rotY: 0,
                  rotZ: 0,
                  offsetX: 0,
                  offsetY: 0,
                  offsetZ: 0,
                  dropToBed: true,
                  uniformScale: true,
                  instances: undefined,
                })
              }
              className="flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-[11px] text-slate-300 hover:border-slate-500"
            >
              <RotateCcw className="h-3 w-3" />
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Panel Flotante "Resultado del Corte" en Vista Capas G-code */}
      {viewMode === 'gcode' && parsedGcode && totalLayers > 0 && (
        <>
          <div className="pointer-events-auto absolute left-4 top-16 z-20 w-80 space-y-2.5 rounded-2xl border border-slate-800/95 bg-slate-900/92 p-3 text-xs shadow-2xl backdrop-blur">
            <div className="flex items-center justify-between border-b border-slate-800 pb-2">
              <span className="font-semibold text-slate-100">Resultado del Corte</span>
              <button
                type="button"
                onClick={() => setShowGhostMesh((v) => !v)}
                className={`rounded-md border px-2 py-0.5 text-[10px] font-medium transition ${
                  showGhostMesh
                    ? 'border-emerald-500/50 bg-emerald-500/15 text-emerald-300'
                    : 'border-slate-700 bg-slate-950 text-slate-400'
                }`}
              >
                Silueta {showGhostMesh ? 'ON' : 'OFF'}
              </button>
            </div>

            <div className="grid grid-cols-3 gap-1.5 text-center text-[11px]">
              <div className="rounded-lg bg-slate-950/80 px-1.5 py-1">
                <span className="block text-[9px] uppercase text-slate-500">Tiempo</span>
                <span className="font-mono font-bold text-slate-100">
                  {formatDurationCompact(parsedGcode.stats.totalTimeSec)}
                </span>
              </div>
              <div className="rounded-lg bg-slate-950/80 px-1.5 py-1">
                <span className="block text-[9px] uppercase text-slate-500">Metros</span>
                <span className="font-mono font-bold text-cyan-300">
                  {parsedGcode.stats.totalMeters.toFixed(2)} m
                </span>
              </div>
              <div className="rounded-lg bg-slate-950/80 px-1.5 py-1">
                <span className="block text-[9px] uppercase text-slate-500">Gramos</span>
                <span className="font-mono font-bold text-orange-300">
                  {parsedGcode.stats.totalGrams.toFixed(1)} g
                </span>
              </div>
            </div>

            <div>
              <label className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-slate-400">
                Esquema de colores
              </label>
              <select
                value={colorScheme}
                onChange={(e) => setColorScheme(e.target.value as GcodeColorScheme)}
                className="w-full rounded-lg border border-slate-700 bg-slate-950 px-2.5 py-1.5 text-xs font-medium text-slate-100 focus:border-cyan-400 focus:outline-none"
              >
                <option value="type">Tipo de línea</option>
                <option value="tool">Filamento (T0–T3)</option>
                <option value="speed">Velocidad (mm/s)</option>
                <option value="flow">Flujo volumétrico (mm³/s)</option>
                <option value="temp">Temperatura (°C)</option>
              </select>
            </div>

            {colorScheme === 'type' && (
              <div className="max-h-56 overflow-y-auto pr-0.5">
                <table className="w-full text-left text-[10px]">
                  <thead>
                    <tr className="border-b border-slate-800 text-slate-500">
                      <th className="py-1 font-medium">Tipo</th>
                      <th className="py-1 text-right font-medium">Tiempo</th>
                      <th className="py-1 text-right font-medium">%</th>
                      <th className="py-1 text-right font-medium">m / g</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-800/60">
                    {parsedGcode.stats.roleStats.map((row) => {
                      const checked = visibleRoles[row.id] !== false;
                      return (
                        <tr key={row.id} className="hover:bg-slate-800/40">
                          <td className="py-1 pr-1">
                            <label className="flex cursor-pointer items-center gap-1.5">
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={(e) =>
                                  setVisibleRoles((prev) => ({
                                    ...prev,
                                    [row.id]: e.target.checked,
                                  }))
                                }
                                className="accent-cyan-500"
                              />
                              <span
                                className="h-2.5 w-2.5 shrink-0 rounded-sm border border-white/20"
                                style={{ backgroundColor: row.color }}
                              />
                              <span className="truncate text-slate-200">{row.label}</span>
                            </label>
                          </td>
                          <td className="py-1 text-right font-mono text-slate-300">
                            {formatDurationCompact(row.timeSec)}
                          </td>
                          <td className="py-1 text-right font-mono text-slate-400">
                            {row.percentTime.toFixed(1)}%
                          </td>
                          <td className="py-1 text-right font-mono text-slate-300">
                            {row.meters.toFixed(1)}m/{row.grams.toFixed(1)}g
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            {colorScheme === 'tool' && (
              <div className="grid grid-cols-2 gap-1.5 pt-0.5">
                {parsedGcode.extruderColors.map((col, idx) => (
                  <div
                    key={idx}
                    className="flex items-center gap-2 rounded-lg border border-slate-800 bg-slate-950 px-2 py-1 text-[11px]"
                  >
                    <span
                      className="h-3 w-3 rounded-sm border border-white/25"
                      style={{ backgroundColor: col }}
                    />
                    <span className="font-mono font-semibold text-slate-200">T{idx}</span>
                    <span className="ml-auto font-mono text-[10px] text-slate-500">
                      {col.toUpperCase()}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {(colorScheme === 'speed' || colorScheme === 'flow' || colorScheme === 'temp') && (
              <div className="space-y-1.5 rounded-lg border border-slate-800 bg-slate-950 p-2">
                <div
                  className="h-2.5 w-full rounded-full"
                  style={{
                    background:
                      'linear-gradient(90deg, #2563EB 0%, #06B6D4 20%, #22C55E 40%, #FACC15 65%, #F97316 82%, #DC2626 100%)',
                  }}
                />
                <div className="flex justify-between font-mono text-[10px] text-slate-300">
                  {colorScheme === 'speed' && (
                    <>
                      <span>{parsedGcode.stats.minSpeed} mm/s</span>
                      <span>
                        {((parsedGcode.stats.minSpeed + parsedGcode.stats.maxSpeed) * 0.5).toFixed(0)} mm/s
                      </span>
                      <span>{parsedGcode.stats.maxSpeed} mm/s</span>
                    </>
                  )}
                  {colorScheme === 'flow' && (
                    <>
                      <span>{parsedGcode.stats.minFlow} mm³/s</span>
                      <span>
                        {((parsedGcode.stats.minFlow + parsedGcode.stats.maxFlow) * 0.5).toFixed(1)} mm³/s
                      </span>
                      <span>{parsedGcode.stats.maxFlow} mm³/s</span>
                    </>
                  )}
                  {colorScheme === 'temp' && (
                    <>
                      <span>{parsedGcode.stats.minTemp} °C</span>
                      <span>
                        {((parsedGcode.stats.minTemp + parsedGcode.stats.maxTemp) * 0.5).toFixed(0)} °C
                      </span>
                      <span>{parsedGcode.stats.maxTemp} °C</span>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* Slider vertical de capas en borde derecho */}
          <div className="absolute bottom-4 right-4 top-20 z-10 flex flex-col items-center justify-between gap-3 rounded-2xl border border-slate-800/90 bg-slate-900/85 px-3 py-3 backdrop-blur">
            <div className="text-center">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                Capa
              </p>
              <p className="font-mono text-sm font-bold text-orange-400">
                {currentLayer}/{totalLayers}
              </p>
              {activeLayerData && (
                <p className="font-mono text-[10px] text-slate-400">
                  Z {activeLayerData.z.toFixed(2)}mm
                </p>
              )}
            </div>

            <div className="relative flex flex-1 items-center justify-center py-2">
              <input
                type="range"
                min={1}
                max={totalLayers}
                value={currentLayer}
                onChange={(e) => setCurrentLayer(Number(e.target.value))}
                aria-label="Selector de capa G-code"
                className="h-44 cursor-pointer accent-orange-500 [writing-mode:vertical-lr] [direction:rtl]"
              />
              {layerPauses.map((p) => {
                const clamped = Math.max(1, Math.min(totalLayers, p.layer));
                const bottomPct =
                  totalLayers > 1 ? ((clamped - 1) / (totalLayers - 1)) * 100 : 0;
                return (
                  <button
                    key={p.layer}
                    type="button"
                    onClick={() => setCurrentLayer(clamped)}
                    title={`Pausa Capa ${p.layer}${p.note ? ` · ${p.note}` : ''}`}
                    style={{ bottom: `calc(${bottomPct}% * 0.88 + 6%)` }}
                    className="absolute right-0.5 h-2.5 w-2.5 rounded-full border border-amber-200 bg-amber-400 shadow"
                  />
                );
              })}
            </div>

            {onAddLayerPause && (
              <div className="flex w-full flex-col items-center gap-1">
                {(() => {
                  const existingHere = layerPauses.find((p) => p.layer === currentLayer);
                  if (existingHere && onRemoveLayerPause) {
                    return (
                      <button
                        type="button"
                        onClick={() => onRemoveLayerPause(currentLayer)}
                        title="Quitar pausa en esta capa"
                        className="flex w-full items-center justify-center gap-1 rounded-lg border border-amber-400/60 bg-amber-500/20 px-2 py-1 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/30"
                      >
                        <Pause className="h-3 w-3" />
                        Quitar Pausa
                      </button>
                    );
                  }
                  return (
                    <>
                      <button
                        type="button"
                        onClick={() => {
                          if (!showPauseInput) {
                            setShowPauseInput(true);
                          } else {
                            onAddLayerPause(
                              currentLayer,
                              activeLayerData?.z ?? 0,
                              pauseNoteDraft.trim(),
                            );
                            setPauseNoteDraft('');
                            setShowPauseInput(false);
                          }
                        }}
                        title="Agregar pausa en la capa actual"
                        className="flex w-full items-center justify-center gap-1 rounded-lg border border-amber-500/45 bg-amber-500/15 px-2 py-1 text-[10px] font-semibold text-amber-200 hover:bg-amber-500/25"
                      >
                        <Plus className="h-3 w-3" />
                        + Pausa aquí
                      </button>
                      {showPauseInput && (
                        <div className="flex w-28 flex-col gap-1 rounded-lg border border-slate-700 bg-slate-950 p-1.5">
                          <input
                            type="text"
                            value={pauseNoteDraft}
                            onChange={(e) => setPauseNoteDraft(e.target.value)}
                            placeholder="Ej. Insertar imán"
                            className="w-full rounded border border-slate-700 bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-100 placeholder:text-slate-500"
                          />
                          <div className="flex gap-1">
                            <button
                              type="button"
                              onClick={() => {
                                onAddLayerPause(
                                  currentLayer,
                                  activeLayerData?.z ?? 0,
                                  pauseNoteDraft.trim(),
                                );
                                setPauseNoteDraft('');
                                setShowPauseInput(false);
                              }}
                              className="flex-1 rounded bg-amber-500/30 py-0.5 text-[9px] font-semibold text-amber-100 hover:bg-amber-500/45"
                            >
                              Guardar
                            </button>
                            <button
                              type="button"
                              onClick={() => setShowPauseInput(false)}
                              className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] text-slate-400"
                            >
                              ×
                            </button>
                          </div>
                        </div>
                      )}
                    </>
                  );
                })()}
              </div>
            )}

            <button
              type="button"
              onClick={() => setShowTravel((prev) => !prev)}
              title="Mostrar/ocultar viajes en vacío"
              className={`flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium transition ${
                showTravel
                  ? 'border-slate-600 bg-slate-800 text-slate-100'
                  : 'border-slate-800 bg-slate-950/60 text-slate-400 hover:text-slate-200'
              }`}
            >
              {showTravel ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
              Viajes
            </button>
          </div>
        </>
      )}

      {/* Escena 3D */}
      <Canvas
        shadows
        gl={{ preserveDrawingBuffer: true }}
        camera={{ position: [230, 210, 250], fov: 42, near: 0.5, far: 5000 }}
        onPointerMissed={() => {
          if (!marqueeRect) onSelectObjects?.([]);
        }}
      >
        <MarqueeProjector projectorRef={projectorRef} />
        <color attach="background" args={['#070b14']} />
        <hemisphereLight
          args={['#f8fafc', '#334155', viewMode === 'gcode' ? 1.35 : 0.9]}
        />
        <ambientLight intensity={viewMode === 'gcode' ? 0.85 : 0.32} />
        <directionalLight
          position={[220, 320, 180]}
          intensity={viewMode === 'gcode' ? 1.45 : 1.1}
          castShadow
        />
        <directionalLight
          position={[-200, 180, -180]}
          intensity={viewMode === 'gcode' ? 0.95 : 0.65}
        />

        <BuildPlate printer={printer} />

        {/* Objetos independientes de .3MF / Dividir Objetos o Instancias STL normales */}
        {sceneObjects.length > 0 &&
        (viewMode === 'stl' || (viewMode === 'gcode' && showGhostMesh)) ? (
          <>
            {sceneObjects.map((obj) => {
              const isSel = selectedSet.has(obj.object_id);
              return (
                <SceneObjectItemPreview
                  key={obj.object_id}
                  obj={obj}
                  isSelected={isSel}
                  fitsInVolume={fitsInVolume}
                  ghostMode={viewMode === 'gcode'}
                  extruderColors={extruderColors}
                  partExtruderMap={partExtruderMap}
                  activeCadTool={
                    viewMode === 'stl' && selectedSceneObjs.length === 1
                      ? activeCadTool
                      : null
                  }
                  onSelect={(ev) => {
                    if (ev.shiftKey || ev.metaKey || ev.ctrlKey) {
                      onSelectObjects?.(
                        isSel
                          ? selectedObjectIds.filter((id) => id !== obj.object_id)
                          : [...selectedObjectIds, obj.object_id],
                      );
                    } else {
                      onSelectObjects?.([obj.object_id]);
                    }
                  }}
                  onCommitOffset={(patch) => {
                    if (!onChangeSceneObjects) return;
                    onChangeSceneObjects(
                      sceneObjects.map((o) =>
                        o.object_id === obj.object_id ? { ...o, ...patch } : o,
                      ),
                    );
                  }}
                  onDraggingChange={setIsDraggingGizmo}
                />
              );
            })}
            {viewMode === 'stl' &&
              selectedSceneObjs.length >= 2 &&
              activeCadTool === 'move' && (
                <GroupMoveGizmo
                  centroid={groupCentroid}
                  allowZ={!isAllDropToBed}
                  onCommitDelta={applyGroupMoveDelta}
                  onDraggingChange={setIsDraggingGizmo}
                />
              )}
          </>
        ) : (
          loadedModel &&
          (viewMode === 'stl' || (viewMode === 'gcode' && showGhostMesh)) &&
          instances.map((inst, idx) => (
            <SingleInstancePreview
              key={inst.instance_id}
              loaded={loadedModel}
              inst={inst}
              isSelected={idx === safeIdx}
              fitsInVolume={fitsInVolume}
              ghostMode={viewMode === 'gcode'}
              extruderColors={extruderColors}
              multimaterialParts={multimaterialParts}
              partExtruderMap={partExtruderMap}
              activeCadTool={viewMode === 'stl' ? activeCadTool : null}
              isDraggingGizmo={isDraggingGizmo}
              onSelectInstance={() => setActiveInstanceIdx(idx)}
              onSurfaceClick={handleMeasureClick}
              onCommitOffset={(patch) => updateActiveInstance(patch)}
              onDraggingChange={setIsDraggingGizmo}
            />
          ))
        )}

        {/* Plano de corte 3D cuando está activa la herramienta Cortar */}
        {viewMode === 'stl' && stlFile && activeCadTool === 'cut' && (
          <CutPlaneOverlay
            cutZMm={cutZMm}
            tiltXDeg={cutTiltX}
            tiltYDeg={cutTiltY}
            bedSpan={bedSpan}
          />
        )}

        {/* Facetas iluminadas de Colocar en Cara */}
        {viewMode === 'stl' &&
          stlFile &&
          activeCadTool === 'lay_on_face' &&
          layCandidates.length > 0 && (
            <LayOnFaceMarkers
              candidates={layCandidates}
              offsetX={activeInstance.offset_x}
              offsetY={activeInstance.offset_y}
              offsetZ={activeInstance.drop_to_bed ? 0 : activeInstance.offset_z}
              onPickCandidate={(cand) =>
                updateActiveInstance({
                  rot_x: cand.rot_x,
                  rot_y: cand.rot_y,
                  rot_z: cand.rot_z,
                  drop_to_bed: true,
                  offset_z: 0,
                })
              }
            />
          )}

        {/* Marcadores y línea cotada de Medición 3D */}
        {viewMode === 'stl' && stlFile && activeCadTool === 'measure' && measurePoints.length > 0 && (
          <MeasureOverlay points={measurePoints} />
        )}

        {/* Capas G-Code */}
        {viewMode === 'gcode' && parsedGcode && totalLayers > 0 && (
          <GcodePreview
            parsed={parsedGcode}
            maxVisibleLayer={currentLayer}
            showTravel={showTravel}
            colorScheme={colorScheme}
            visibleRoles={visibleRoles}
          />
        )}

        <OrbitControls
          makeDefault
          enabled={!isDraggingGizmo && !marqueeRect}
          enableDamping
          dampingFactor={0.08}
          minDistance={25}
          maxDistance={1400}
        />
      </Canvas>

      {/* Overlay de carga UX solo en la carga inicial de un archivo nuevo (nunca al re-escalar o rotar) */}
      {stlFile &&
        viewMode === 'stl' &&
        (isParsingModel || (isAnalyzing && !meshId)) && (
          <div className="pointer-events-none absolute inset-0 z-30 flex items-center justify-center bg-slate-950/65 backdrop-blur-md transition-opacity duration-300">
            <div className="flex flex-col items-center gap-3 rounded-2xl border border-cyan-500/35 bg-slate-900/90 px-6 py-5 shadow-2xl shadow-cyan-500/15">
              <Loader2 className="h-8 w-8 animate-spin text-cyan-400" />
              <p className="font-mono text-xs font-semibold tracking-wider text-cyan-100">
                {stlFile.name.toLowerCase().endsWith('.3mf')
                  ? 'CARGANDO MODELO 3MF Y EXTRUSORES...'
                  : 'CARGANDO MALLA 3D...'}
              </p>
              <span className="max-w-xs truncate text-[11px] text-slate-400">
                {stlFile.name}
              </span>
            </div>
          </div>
        )}

      {stlFile && viewMode === 'stl' && isAutoOrienting && (
        <div className="pointer-events-auto absolute inset-0 z-30 flex items-center justify-center bg-slate-950/60 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-2.5 rounded-2xl border border-emerald-500/40 bg-slate-900/95 px-6 py-4 shadow-2xl">
            <Loader2 className="h-7 w-7 animate-spin text-emerald-400" />
            <p className="text-xs font-semibold text-emerald-100">
              Calculando orientaciones óptimas con IA...
            </p>
            <span className="text-[11px] text-slate-400">
              Evaluando altura Z, voladizos y estabilidad en cama
            </span>
          </div>
        </div>
      )}

      {stlFile &&
        viewMode === 'stl' &&
        !isAutoOrienting &&
        orientationsData &&
        orientationsData.options.length > 0 && (
          <div className="pointer-events-auto absolute inset-x-3 bottom-3 z-20 rounded-2xl border border-emerald-500/35 bg-slate-900/94 p-3 text-xs shadow-2xl backdrop-blur">
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 pb-2">
              <div className="flex items-center gap-2">
                <Compass className="h-4 w-4 text-emerald-400" />
                <span className="font-semibold text-slate-100">
                  Orientaciones IA · Previsualización en Vivo
                </span>
                {orientationsData.is_multicolor && (
                  <span className="rounded-full border border-purple-500/40 bg-purple-500/15 px-2 py-0.5 text-[10px] font-semibold text-purple-200">
                    Multicolor ({orientationsData.multicolor_parts_count} partes)
                  </span>
                )}
                <span className="rounded-full border border-slate-700 bg-slate-950 px-2 py-0.5 text-[10px] text-slate-400">
                  {orientationsData.ai_provider}
                </span>
              </div>
              <button
                type="button"
                onClick={onCloseOrientations}
                className="flex items-center gap-1 rounded-lg border border-emerald-500/45 bg-emerald-500/15 px-2.5 py-1 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/25"
              >
                Usar Orientación Seleccionada
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5">
              {orientationsData.options.map((opt) => {
                const isSelected = selectedOrientationId === opt.id;
                return (
                  <button
                    key={opt.id}
                    type="button"
                    onClick={() => onSelectOrientation?.(opt)}
                    className={`flex flex-col justify-between rounded-xl border p-2.5 text-left transition ${
                      isSelected
                        ? 'border-emerald-400 bg-emerald-500/15 ring-1 ring-emerald-400/50'
                        : 'border-slate-800 bg-slate-950/80 hover:border-slate-600'
                    }`}
                  >
                    <div className="space-y-1">
                      <div className="flex items-start justify-between gap-1">
                        <span className="text-[11px] font-semibold leading-tight text-slate-100">
                          {opt.title}
                        </span>
                        <span
                          className={`shrink-0 rounded-md px-1.5 py-0.5 text-[9px] font-semibold ${
                            opt.is_recommended
                              ? 'bg-amber-500/25 text-amber-200 border border-amber-400/40'
                              : 'bg-slate-800 text-slate-300'
                          }`}
                        >
                          {opt.is_recommended ? (
                            <span className="inline-flex items-center gap-0.5">
                              <Sparkles className="h-2.5 w-2.5" />
                              {opt.badge}
                            </span>
                          ) : (
                            opt.badge
                          )}
                        </span>
                      </div>
                      <p className="line-clamp-2 text-[10px] leading-snug text-slate-400">
                        {opt.explanation}
                      </p>
                      {opt.stability_warning && (
                        <p className="rounded-md border border-amber-500/35 bg-amber-500/10 px-1.5 py-0.5 text-[9px] font-medium text-amber-200">
                          {opt.stability_warning}
                        </p>
                      )}
                    </div>

                    <div className="mt-2 space-y-1 border-t border-slate-800/80 pt-1.5 font-mono text-[10px]">
                      <div className="flex items-center justify-between text-slate-300">
                        <span>
                          X/Y/Z: {opt.rotation.rx}°/{opt.rotation.ry}°/{opt.rotation.rz}°
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-slate-400">
                        <span>Z: {opt.z_height_mm} mm</span>
                        <span>Voladizos: {opt.overhang_ratio_pct}%</span>
                      </div>
                      <div
                        className={`text-[10px] font-semibold ${
                          opt.estimated_time_delta_pct.startsWith('-')
                            ? 'text-emerald-300'
                            : opt.estimated_time_delta_pct.startsWith('+')
                              ? 'text-amber-300'
                              : 'text-slate-400'
                        }`}
                      >
                        {opt.estimated_time_delta_pct}
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}

      {/* Placeholder con mascota Nikk Slider cuando aún no hay STL */}
      {!stlFile && (
        <div className="pointer-events-none absolute inset-x-0 bottom-5 flex justify-center px-4">
          <div className="flex items-center gap-3 rounded-2xl border border-cyan-500/25 bg-slate-900/90 px-4 py-2 text-xs text-slate-300 shadow-xl backdrop-blur">
            <img
              src="/nikk-mascot.jpg"
              alt="Nikk Slider Mascot"
              className="h-11 w-11 rounded-xl object-cover object-top ring-1 ring-cyan-500/40"
            />
            <div>
              <p className="font-semibold text-cyan-200">Nikk Slider 3D</p>
              <p className="text-[11px] text-slate-400">
                Arrastra un archivo <span className="font-mono text-cyan-300">.stl</span> o{' '}
                <span className="font-mono text-purple-300">.3mf</span> en el Paso 2 para previsualizarlo
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
