"""Analizador, centrador, extractor `.3mf` multicolor y auto-orientador geométrico."""

from __future__ import annotations

import itertools
import json
import math
import os
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import numpy as np
import trimesh

from app.config import MESH_CACHE_DIR, PrinterConfig
from app.models.schemas import (
    AutoArrangeResponse,
    AutoOrientResponse,
    DetectedColorInfo,
    DimensionsMM,
    LayOnFaceCandidate,
    LayOnFaceResponse,
    MeshAnalysisResponse,
    ModelInstanceTransform,
    MultimaterialPartInfo,
    SceneObjectInfo,
    SceneObjectTransform,
)

CRITICAL_OVERHANG_COS = math.cos(math.radians(50.0))  # ~0.6428 -> nz < -0.6428 implica >50°


def sanitize_euler_rotation(
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
) -> tuple[float, float, float]:
    """Sanitiza ángulos Euler [rx, ry, rz]: reemplaza NaN/Inf y suprime micro-ángulos < 0.01°."""
    cleaned: list[float] = []
    for raw in (rot_x, rot_y, rot_z):
        try:
            val = float(raw)
        except (TypeError, ValueError):
            val = 0.0
        if not math.isfinite(val):
            val = 0.0
        mod = val % 360.0
        if mod < 0.01 or abs(mod - 360.0) < 0.01:
            cleaned.append(0.0)
        elif abs(val) < 0.01:
            cleaned.append(0.0)
        else:
            cleaned.append(round(val, 2))
    return (cleaned[0], cleaned[1], cleaned[2])


def _bed_center_xy(printer: PrinterConfig | None) -> tuple[float, float]:
    """Retorna el centro objetivo XY del plato según el origen de coordenadas del firmware."""
    if printer is not None and printer.origin == "bottom_left" and printer.bed_mm is not None:
        return printer.bed_mm[0] / 2.0, printer.bed_mm[1] / 2.0
    return 0.0, 0.0


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _norm_zip_path(path_str: str) -> str:
    return path_str.lstrip("/").replace("\\", "/")


def _normalize_hex(raw: str | None) -> str | None:
    if not raw:
        return None
    clean = raw.strip().lstrip("#")
    if len(clean) >= 6:
        return f"#{clean[:6].upper()}"
    return None


def _parse_3mf_transform(attr: str | None) -> np.ndarray:
    mat = np.eye(4, dtype=float)
    if not attr:
        return mat
    vals = [float(v) for v in attr.strip().split()]
    if len(vals) != 12:
        return mat
    mat[0, :3] = [vals[0], vals[3], vals[6]]
    mat[1, :3] = [vals[1], vals[4], vals[7]]
    mat[2, :3] = [vals[2], vals[5], vals[8]]
    mat[:3, 3] = [vals[9], vals[10], vals[11]]
    return mat


_PAINT_DIRECT_CODE: dict[int, str] = {
    1: "4",
    2: "8",
    3: "0C",
    4: "1C",
}
_PAINT_FAST_MAP: dict[str, int] = {
    "4": 1,
    "8": 2,
    "0C": 3,
    "1C": 4,
    "2C": 4,  # fallback clamp to 4
}


def decode_paint_color_extruder(paint_hex: str | None) -> int:
    """Decodifica el atributo `paint_color` (árbol nibbles Orca/Bambu) a extrusor 1..16."""
    if not paint_hex:
        return 1
    code = paint_hex.strip().upper()
    if not code:
        return 1
    fast = _PAINT_FAST_MAP.get(code)
    if fast is not None:
        return fast

    # Recorrido derecha->izquierda del árbol cuaternario codificado en nibbles hex
    idx = len(code) - 1
    counts: dict[int, int] = {}  # índice 0 = sin pintar, 1..N = T0..T(N-1)
    stack = [1]  # número de hijos restantes en el nodo actual (raíz = 1)
    while idx >= 0 and stack:
        ch = code[idx]
        idx -= 1
        try:
            nib = int(ch, 16)
        except ValueError:
            break
        split_sides = nib & 0x3
        if split_sides == 0:
            state = nib >> 2
            if state == 3 and idx >= 0:
                try:
                    ext_off = int(code[idx], 16)
                    idx -= 1
                    state = 3 + ext_off
                except ValueError:
                    state = 3
            slot = max(0, min(16, state))
            counts[slot] = counts.get(slot, 0) + 1
        else:
            # Nodo dividido en 4 sub-triángulos
            stack.append(4)
            continue

        while stack:
            stack[-1] -= 1
            if stack[-1] == 0:
                stack.pop()
            else:
                break

    painted_keys = [k for k in counts if k >= 1 and counts[k] > 0]
    if not painted_keys:
        return 1
    return max(painted_keys, key=lambda e: counts[e])


def inspect_3mf_multicolor_info(threemf_path: Path) -> dict[str, object]:
    """Inspecciona pintado por triángulo (`paint_color` o `pid`/`p1`) y paleta embebida en `.3mf` (1..N colores)."""
    counts: dict[int, int] = {}  # 0..N-1 (T0..T(N-1))
    total_paint_tris = 0
    has_paint_color_attr = False
    has_tri_pid_attr = False
    project_palette: list[str] = []

    with zipfile.ZipFile(threemf_path, "r") as zf:
        names = zf.namelist()
        names_lower = {n.lower(): n for n in names}

        if "metadata/project_settings.config" in names_lower:
            try:
                proj = json.loads(
                    zf.read(names_lower["metadata/project_settings.config"]).decode(
                        "utf-8", errors="ignore"
                    )
                )
                for col in proj.get("filament_colour", []):
                    norm = _normalize_hex(str(col))
                    if norm:
                        project_palette.append(norm)
            except (ValueError, KeyError):
                pass

        objects_by_key: dict[tuple[str, str], ET.Element] = {}
        colors_by_group: dict[tuple[str, str], list[str]] = {}
        root_model_path: str | None = None
        root_tree: ET.Element | None = None

        for mf in [n for n in names if n.lower().endswith(".model")]:
            norm_mf = _norm_zip_path(mf)
            el_root = ET.fromstring(zf.read(mf))
            if norm_mf.lower() == "3d/3dmodel.model" or root_model_path is None:
                root_model_path = norm_mf
                root_tree = el_root

            for res_el in el_root:
                if _strip_ns(res_el.tag) != "resources":
                    continue
                for child in res_el:
                    cname = _strip_ns(child.tag)
                    cid = child.attrib.get("id", "")
                    if cname == "object" and cid:
                        objects_by_key[(norm_mf, cid)] = child
                    elif cname in ("colorgroup", "basematerials") and cid:
                        cols = [
                            c
                            for c in (
                                _normalize_hex(ce.attrib.get("color") or ce.attrib.get("displaycolor"))
                                for ce in child
                            )
                            if c
                        ]
                        if cols:
                            colors_by_group[(norm_mf, cid)] = cols

        if root_tree is not None and root_model_path is not None:
            visited_meshes: set[tuple[str, str]] = set()
            tri_pids_seen: set[int] = set()

            def walk_paint(model_path: str, obj_id: str) -> None:
                nonlocal total_paint_tris, has_paint_color_attr, has_tri_pid_attr
                obj_el = objects_by_key.get((model_path, obj_id))
                if obj_el is None:
                    return
                for ch in obj_el:
                    tn = _strip_ns(ch.tag)
                    if tn == "mesh" and (model_path, obj_id) not in visited_meshes:
                        visited_meshes.add((model_path, obj_id))
                        for sub in ch:
                            if _strip_ns(sub.tag) != "triangles":
                                continue
                            for tri in sub:
                                total_paint_tris += 1
                                pc = tri.attrib.get("paint_color")
                                if pc is not None:
                                    has_paint_color_attr = True
                                    ext = decode_paint_color_extruder(pc)
                                    counts[ext - 1] = counts.get(ext - 1, 0) + 1
                                elif "pid" in tri.attrib and "p1" in tri.attrib:
                                    has_tri_pid_attr = True
                                    try:
                                        p1_idx = int(tri.attrib["p1"])
                                    except ValueError:
                                        p1_idx = 0
                                    tri_pids_seen.add(p1_idx)
                                    counts[p1_idx] = counts.get(p1_idx, 0) + 1
                                else:
                                    counts[0] = counts.get(0, 0) + 1
                    elif tn == "components":
                        for comp in ch:
                            c_id = comp.attrib.get("objectid")
                            if not c_id:
                                continue
                            p_attr = next(
                                (v for k, v in comp.attrib.items() if k == "path" or k.endswith("}path")),
                                None,
                            )
                            next_mp = _norm_zip_path(p_attr) if p_attr else model_path
                            walk_paint(next_mp, c_id)

            for child in root_tree:
                if _strip_ns(child.tag) == "build":
                    for item in child:
                        if _strip_ns(item.tag) == "item" and item.attrib.get("objectid"):
                            walk_paint(root_model_path, item.attrib["objectid"])

            if not project_palette and colors_by_group:
                first_group = next(iter(colors_by_group.values()))
                project_palette = list(first_group)

    active_slots = sum(1 for c in counts.values() if c > 0)
    percentages: dict[str, float] = {}
    if total_paint_tris > 0 and (has_paint_color_attr or (has_tri_pid_attr and active_slots > 1)):
        for i in sorted(counts.keys()):
            c = counts[i]
            if c > 0:
                percentages[f"T{i}"] = round((c / total_paint_tris) * 100.0, 1)

    return {
        "has_triangle_painting": bool(
            total_paint_tris > 0 and (has_paint_color_attr or (has_tri_pid_attr and active_slots > 1))
        ),
        "active_painted_extruders": active_slots,
        "extruder_triangle_percentages": percentages,
        "detected_filament_colors": project_palette,
    }


def extract_3mf_parts_and_meshes(
    threemf_path: Path,
) -> list[tuple[MultimaterialPartInfo, trimesh.Trimesh]]:
    """Extrae sub-mallas, nombres, colores y extrusores (`1..4`) de archivos `.3mf`."""
    with zipfile.ZipFile(threemf_path, "r") as zf:
        names = zf.namelist()
        names_lower = {n.lower(): n for n in names}

        project_palette: list[str] = []
        if "metadata/project_settings.config" in names_lower:
            try:
                proj = json.loads(
                    zf.read(names_lower["metadata/project_settings.config"]).decode(
                        "utf-8", errors="ignore"
                    )
                )
                for col in proj.get("filament_colour", []):
                    norm = _normalize_hex(str(col))
                    if norm:
                        project_palette.append(norm)
            except (ValueError, KeyError):
                pass

        # Mapear part_id -> (name, extruder) desde Metadata/model_settings.config
        settings_by_id: dict[str, tuple[str | None, int | None]] = {}
        settings_by_name: dict[str, int] = {}
        if "metadata/model_settings.config" in names_lower:
            ms_root = ET.fromstring(zf.read(names_lower["metadata/model_settings.config"]))
            for part_el in ms_root.iter("part"):
                pid = part_el.attrib.get("id", "")
                pname: str | None = None
                pext: int | None = None
                for md in part_el.findall("metadata"):
                    k = md.attrib.get("key")
                    v = md.attrib.get("value")
                    if k == "name" and v:
                        pname = v
                    elif k == "extruder" and v and v.isdigit():
                        pext = max(1, min(4, int(v)))
                if pid:
                    settings_by_id[pid] = (pname, pext)
                if pname and pext is not None:
                    settings_by_name[pname] = pext

        # Parsear todos los documentos .model dentro del paquete 3MF
        objects_by_key: dict[tuple[str, str], ET.Element] = {}
        colors_by_group: dict[tuple[str, str], list[str]] = {}
        root_model_path: str | None = None
        root_tree: ET.Element | None = None

        model_files = [n for n in names if n.lower().endswith(".model")]
        for mf in model_files:
            norm_mf = _norm_zip_path(mf)
            el_root = ET.fromstring(zf.read(mf))
            if norm_mf.lower() == "3d/3dmodel.model" or root_model_path is None:
                root_model_path = norm_mf
                root_tree = el_root

            for res_el in el_root:
                if _strip_ns(res_el.tag) != "resources":
                    continue
                for child in res_el:
                    cname = _strip_ns(child.tag)
                    cid = child.attrib.get("id", "")
                    if cname == "object" and cid:
                        objects_by_key[(norm_mf, cid)] = child
                    elif cname in ("colorgroup", "basematerials") and cid:
                        cols: list[str] = []
                        for col_el in child:
                            raw_c = col_el.attrib.get("color") or col_el.attrib.get("displaycolor")
                            norm_c = _normalize_hex(raw_c)
                            if norm_c:
                                cols.append(norm_c)
                        if cols:
                            colors_by_group[(norm_mf, cid)] = cols

        if root_tree is None or root_model_path is None:
            raise ValueError("Archivo .3mf sin 3D/3dmodel.model válido.")

        extracted: list[tuple[MultimaterialPartInfo, trimesh.Trimesh]] = []
        seen_idx = 0

        def walk_object(model_path: str, obj_id: str, cur_mat: np.ndarray) -> None:
            nonlocal seen_idx
            obj_el = objects_by_key.get((model_path, obj_id))
            if obj_el is None:
                return

            mesh_el: ET.Element | None = None
            comps_el: ET.Element | None = None
            for ch in obj_el:
                tn = _strip_ns(ch.tag)
                if tn == "mesh":
                    mesh_el = ch
                elif tn == "components":
                    comps_el = ch

            if mesh_el is not None:
                verts_el: ET.Element | None = None
                tris_el: ET.Element | None = None
                for ch in mesh_el:
                    tn = _strip_ns(ch.tag)
                    if tn == "vertices":
                        verts_el = ch
                    elif tn == "triangles":
                        tris_el = ch

                if verts_el is not None and tris_el is not None:
                    verts = np.array(
                        [
                            (
                                float(v.attrib["x"]),
                                float(v.attrib["y"]),
                                float(v.attrib["z"]),
                            )
                            for v in verts_el
                        ],
                        dtype=np.float64,
                    )
                    tri_rows: list[tuple[int, int, int]] = []
                    tri_pid: str | None = None
                    tri_p1: int | None = None
                    for t in tris_el:
                        tri_rows.append(
                            (int(t.attrib["v1"]), int(t.attrib["v2"]), int(t.attrib["v3"]))
                        )
                        if tri_pid is None and "pid" in t.attrib and "p1" in t.attrib:
                            tri_pid = t.attrib["pid"]
                            tri_p1 = int(t.attrib["p1"])

                    if len(verts) > 0 and len(tri_rows) > 0:
                        faces = np.array(tri_rows, dtype=np.int64)
                        sub_mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
                        if not np.allclose(cur_mat, np.eye(4)):
                            sub_mesh.apply_transform(cur_mat)

                        seen_idx += 1
                        obj_name = obj_el.attrib.get("name")
                        ms_name, ms_ext = settings_by_id.get(obj_id, (None, None))
                        part_name = ms_name or obj_name or f"Parte_{seen_idx}"

                        # Determinar extrusor (1..4) y color hex
                        pid_attr = obj_el.attrib.get("pid") or tri_pid
                        pidx_attr = obj_el.attrib.get("pindex")
                        pidx = int(pidx_attr) if pidx_attr is not None else tri_p1

                        color_hex: str | None = None
                        extruder: int | None = ms_ext or settings_by_name.get(part_name)

                        if pid_attr and (model_path, pid_attr) in colors_by_group and pidx is not None:
                            cg = colors_by_group[(model_path, pid_attr)]
                            if 0 <= pidx < len(cg):
                                color_hex = cg[pidx]
                            if extruder is None:
                                extruder = (pidx % 4) + 1

                        if extruder is None:
                            extruder = ((seen_idx - 1) % 4) + 1

                        if color_hex is None and 0 <= extruder - 1 < len(project_palette):
                            color_hex = project_palette[extruder - 1]

                        info = MultimaterialPartInfo(
                            part_id=f"{obj_id}_{seen_idx}",
                            name=part_name,
                            extruder=extruder,
                            color_hex=color_hex,
                            triangle_count=int(len(faces)),
                        )
                        extracted.append((info, sub_mesh))

            if comps_el is not None:
                for comp in comps_el:
                    c_id = comp.attrib.get("objectid")
                    if not c_id:
                        continue
                    p_attr = None
                    for ak, av in comp.attrib.items():
                        if _strip_ns(ak) == "path":
                            p_attr = _norm_zip_path(av)
                            break
                    target_model = p_attr or model_path
                    c_mat = _parse_3mf_transform(comp.attrib.get("transform"))
                    walk_object(target_model, c_id, cur_mat @ c_mat)

        # Recorrer todos los elementos <item> en <build>
        for ch in root_tree:
            if _strip_ns(ch.tag) == "build":
                for item in ch:
                    oid = item.attrib.get("objectid")
                    if oid:
                        walk_object(
                            root_model_path,
                            oid,
                            _parse_3mf_transform(item.attrib.get("transform")),
                        )

        if not extracted:
            # Fallback a cargador genérico Trimesh si el 3MF no usó <build> estándar
            loaded = trimesh.load(str(threemf_path), force="scene")
            if isinstance(loaded, trimesh.Scene):
                for idx, (gname, geom) in enumerate(loaded.geometry.items(), start=1):
                    if isinstance(geom, trimesh.Trimesh) and len(geom.faces) > 0:
                        extracted.append(
                            (
                                MultimaterialPartInfo(
                                    part_id=str(idx),
                                    name=gname,
                                    extruder=((idx - 1) % 4) + 1,
                                    triangle_count=int(len(geom.faces)),
                                ),
                                geom,
                            )
                        )

        if not extracted:
            raise ValueError("El archivo .3mf no contiene mallas triangulares válidas.")
        return extracted


def load_raw_mesh(model_path: Path) -> trimesh.Trimesh:
    """Carga un `.stl` o `.3mf` y lo unifica en una única malla triangular válida."""
    if model_path.suffix.lower() == ".3mf":
        parts = extract_3mf_parts_and_meshes(model_path)
        meshes = [m for _, m in parts]
        return meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)

    loaded = trimesh.load(str(model_path), force="mesh")
    mesh = loaded.dump(concatenate=True) if isinstance(loaded, trimesh.Scene) else loaded
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError("El archivo STL no contiene una malla triangular válida.")
    return mesh


def _resolve_scale_vec(
    scale_percent: float = 100.0,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
) -> tuple[float, float, float]:
    sx = (scale_x if scale_x is not None else scale_percent) / 100.0
    sy = (scale_y if scale_y is not None else scale_percent) / 100.0
    sz = (scale_z if scale_z is not None else scale_percent) / 100.0
    return max(0.001, sx), max(0.001, sy), max(0.001, sz)


def apply_transform_to_mesh(
    mesh: trimesh.Trimesh,
    printer: PrinterConfig | None = None,
    scale_percent: float = 100.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    drop_to_bed: bool = True,
    copy: bool = False,
) -> trimesh.Trimesh:
    """Aplica escala (uniforme o XYZ), rotación Euler XYZ, centra/desplaza en plato y aplica gravedad."""
    target = mesh.copy() if copy else mesh

    sx, sy, sz = _resolve_scale_vec(scale_percent, scale_x, scale_y, scale_z)
    if abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4:
        target.apply_transform(np.diag([sx, sy, sz, 1.0]))

    rot_x, rot_y, rot_z = sanitize_euler_rotation(rot_x, rot_y, rot_z)
    if abs(rot_x) >= 0.01 or abs(rot_y) >= 0.01 or abs(rot_z) >= 0.01:
        rot_mat = trimesh.transformations.euler_matrix(
            math.radians(rot_x),
            math.radians(rot_y),
            math.radians(rot_z),
            axes="sxyz",
        )
        target.apply_transform(rot_mat)

    bounds = target.bounds
    cx = float((bounds[0][0] + bounds[1][0]) / 2.0)
    cy = float((bounds[0][1] + bounds[1][1]) / 2.0)
    min_z = float(bounds[0][2])
    target_cx, target_cy = _bed_center_xy(printer)
    z_lift = 0.0 if drop_to_bed else max(0.0, float(offset_z))
    target.apply_translation(
        [target_cx + float(offset_x) - cx, target_cy + float(offset_y) - cy, -min_z + z_lift]
    )
    return target


def transform_and_export_3mf_parts(
    threemf_path: Path,
    out_dir: Path,
    printer: PrinterConfig,
    scale_percent: float = 100.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
    part_extruder_map: dict[str, int] | None = None,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    drop_to_bed: bool = True,
    instances: list[ModelInstanceTransform] | None = None,
) -> tuple[Path, list[int]]:
    """Transforma las partes del `.3mf` solidariamente (1 o N instancias) y empaqueta un `.3mf` limpio."""
    parts = extract_3mf_parts_and_meshes(threemf_path)
    eff_instances = instances if instances else [
        ModelInstanceTransform(
            instance_id="inst_1",
            offset_x=offset_x,
            offset_y=offset_y,
            offset_z=offset_z,
            scale_percent=scale_percent,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            drop_to_bed=drop_to_bed,
        )
    ]

    override_map = part_extruder_map or {}
    filament_ids: list[int] = []
    target_cx, target_cy = _bed_center_xy(printer)

    model_chunks: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
        " <resources>",
    ]
    all_part_settings: list[tuple[int, str, int]] = []
    next_obj_id = 1
    comp_ids: list[int] = []

    for inst_idx, inst in enumerate(eff_instances, start=1):
        sx, sy, sz = _resolve_scale_vec(
            inst.scale_percent, inst.scale_x, inst.scale_y, inst.scale_z
        )
        has_scale = abs(sx - 1.0) > 1e-4 or abs(sy - 1.0) > 1e-4 or abs(sz - 1.0) > 1e-4
        has_rot = abs(inst.rot_x) > 1e-3 or abs(inst.rot_y) > 1e-3 or abs(inst.rot_z) > 1e-3
        rot_mat = (
            trimesh.transformations.euler_matrix(
                math.radians(inst.rot_x),
                math.radians(inst.rot_y),
                math.radians(inst.rot_z),
                axes="sxyz",
            )
            if has_rot
            else None
        )

        transformed: list[tuple[MultimaterialPartInfo, trimesh.Trimesh]] = []
        min_pts: list[np.ndarray] = []
        max_pts: list[np.ndarray] = []

        for info, sub in parts:
            m = sub.copy()
            if has_scale:
                m.apply_transform(np.diag([sx, sy, sz, 1.0]))
            if rot_mat is not None:
                m.apply_transform(rot_mat)
            b = m.bounds
            min_pts.append(b[0])
            max_pts.append(b[1])
            transformed.append((info, m))

        g_min = np.min(np.vstack(min_pts), axis=0)
        g_max = np.max(np.vstack(max_pts), axis=0)
        z_lift = 0.0 if inst.drop_to_bed else max(0.0, float(inst.offset_z))
        shift = [
            target_cx + float(inst.offset_x) - float((g_min[0] + g_max[0]) / 2.0),
            target_cy + float(inst.offset_y) - float((g_min[1] + g_max[1]) / 2.0),
            -float(g_min[2]) + z_lift,
        ]

        for info, m in transformed:
            oid = next_obj_id
            next_obj_id += 1
            comp_ids.append(oid)
            m.apply_translation(shift)
            assigned = override_map.get(info.part_id, info.extruder)
            assigned_ext = max(1, min(4, int(assigned)))
            filament_ids.append(assigned_ext)

            part_label = f"{info.name}" if len(eff_instances) == 1 else f"{info.name}_{inst_idx}"
            safe_name = xml_escape(part_label, {'"': "&quot;", "'": "&apos;"})
            v_lines = [f'     <vertex x="{v[0]:.5f}" y="{v[1]:.5f}" z="{v[2]:.5f}"/>' for v in m.vertices]
            f_lines = [f'     <triangle v1="{int(f[0])}" v2="{int(f[1])}" v3="{int(f[2])}"/>' for f in m.faces]

            model_chunks.append(f'  <object id="{oid}" name="{safe_name}" type="model">')
            model_chunks.append("   <mesh>")
            model_chunks.append("    <vertices>")
            model_chunks.extend(v_lines)
            model_chunks.append("    </vertices>")
            model_chunks.append("    <triangles>")
            model_chunks.extend(f_lines)
            model_chunks.append("    </triangles>")
            model_chunks.append("   </mesh>")
            model_chunks.append("  </object>")
            all_part_settings.append((oid, safe_name, assigned_ext))

    asm_id = next_obj_id
    model_chunks.append(f'  <object id="{asm_id}" name="Assembly" type="model">')
    model_chunks.append("   <components>")
    for oid in comp_ids:
        model_chunks.append(f'    <component objectid="{oid}"/>')
    model_chunks.extend([
        "   </components>",
        "  </object>",
        " </resources>",
        " <build>",
        f'  <item objectid="{asm_id}"/>',
        " </build>",
        "</model>",
    ])

    settings_chunks: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<config>",
        f' <object id="{asm_id}">',
        '  <metadata key="name" value="Assembly"/>',
    ]
    for oid, safe_name, assigned_ext in all_part_settings:
        settings_chunks.extend([
            f'  <part id="{oid}" subtype="normal_part">',
            f'   <metadata key="name" value="{safe_name}"/>',
            f'   <metadata key="extruder" value="{assigned_ext}"/>',
            "  </part>",
        ])
    settings_chunks.extend([" </object>", "</config>"])

    out_3mf = out_dir / "assembled_multicolor.3mf"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="config" ContentType="text/xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )

    tmp_3mf = out_3mf.with_suffix(".3mf.tmp")
    with tmp_3mf.open("wb") as raw_fh:
        with zipfile.ZipFile(raw_fh, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", rels_xml)
            zf.writestr("3D/3dmodel.model", "\n".join(model_chunks))
            zf.writestr("Metadata/model_settings.config", "\n".join(settings_chunks))
        raw_fh.flush()
        os.fsync(raw_fh.fileno())
    os.replace(tmp_3mf, out_3mf)

    return out_3mf, filament_ids


def prepare_painted_3mf_for_slicer(
    threemf_path: Path,
    out_dir: Path,
    printer: PrinterConfig,
    scale_percent: float = 100.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    drop_to_bed: bool = True,
    instances: list[ModelInstanceTransform] | None = None,
    part_extruder_map: dict[str, int] | None = None,
) -> Path:
    """Reempaqueta un `.3mf` pintado por triángulo transformado al plato, preservando o remapeando `paint_color`."""
    zone_map: dict[int, int] = {}
    if part_extruder_map:
        for key, val in part_extruder_map.items():
            if key.startswith("zone_"):
                try:
                    z_idx = int(key.split("_", 1)[1])
                    target_ext = max(0, min(3, int(val))) + 1
                    zone_map[z_idx + 1] = target_ext
                except (ValueError, TypeError):
                    pass

    raw_parts: list[tuple[str, np.ndarray, list[tuple[int, int, int, str | None]]]] = []

    with zipfile.ZipFile(threemf_path, "r") as zf:
        names = zf.namelist()
        objects_by_key: dict[tuple[str, str], ET.Element] = {}
        root_model_path: str | None = None
        root_tree: ET.Element | None = None

        for mf in [n for n in names if n.lower().endswith(".model")]:
            norm_mf = _norm_zip_path(mf)
            el_root = ET.fromstring(zf.read(mf))
            if norm_mf.lower() == "3d/3dmodel.model" or root_model_path is None:
                root_model_path = norm_mf
                root_tree = el_root
            for res_el in el_root:
                if _strip_ns(res_el.tag) != "resources":
                    continue
                for child in res_el:
                    if _strip_ns(child.tag) == "object" and child.attrib.get("id"):
                        objects_by_key[(norm_mf, child.attrib["id"])] = child

        if root_tree is None or root_model_path is None:
            raise ValueError("Archivo .3mf sin 3D/3dmodel.model válido.")

        def walk_raw(model_path: str, obj_id: str, cur_mat: np.ndarray) -> None:
            obj_el = objects_by_key.get((model_path, obj_id))
            if obj_el is None:
                return
            mesh_el: ET.Element | None = None
            comps_el: ET.Element | None = None
            for ch in obj_el:
                tn = _strip_ns(ch.tag)
                if tn == "mesh":
                    mesh_el = ch
                elif tn == "components":
                    comps_el = ch

            if mesh_el is not None:
                verts_el: ET.Element | None = None
                tris_el: ET.Element | None = None
                for ch in mesh_el:
                    tn = _strip_ns(ch.tag)
                    if tn == "vertices":
                        verts_el = ch
                    elif tn == "triangles":
                        tris_el = ch
                if verts_el is not None and tris_el is not None:
                    verts = np.array(
                        [(float(v.attrib["x"]), float(v.attrib["y"]), float(v.attrib["z"])) for v in verts_el],
                        dtype=np.float64,
                    )
                    if not np.allclose(cur_mat, np.eye(4)):
                        verts = verts @ cur_mat[:3, :3].T + cur_mat[:3, 3]
                    tri_rows: list[tuple[int, int, int, str | None]] = []
                    for t in tris_el:
                        pc = t.attrib.get("paint_color")
                        if pc is None and "pid" in t.attrib and "p1" in t.attrib:
                            try:
                                ext = (int(t.attrib["p1"]) % 4) + 1
                            except ValueError:
                                ext = 1
                            ext = zone_map.get(ext, ext)
                            pc = _PAINT_DIRECT_CODE.get(ext, "4")
                        elif pc is not None and zone_map:
                            ext = decode_paint_color_extruder(pc)
                            mapped_ext = zone_map.get(ext, ext)
                            if mapped_ext != ext:
                                pc = _PAINT_DIRECT_CODE.get(mapped_ext, pc)
                        tri_rows.append(
                            (int(t.attrib["v1"]), int(t.attrib["v2"]), int(t.attrib["v3"]), pc)
                        )
                    if len(verts) > 0 and tri_rows:
                        pname = obj_el.attrib.get("name") or f"Object_{len(raw_parts) + 1}"
                        raw_parts.append((pname, verts, tri_rows))

            if comps_el is not None:
                for comp in comps_el:
                    c_id = comp.attrib.get("objectid")
                    if not c_id:
                        continue
                    c_mat = _parse_3mf_transform(comp.attrib.get("transform"))
                    p_attr = next(
                        (v for k, v in comp.attrib.items() if k == "path" or k.endswith("}path")),
                        None,
                    )
                    next_mp = _norm_zip_path(p_attr) if p_attr else model_path
                    walk_raw(next_mp, c_id, cur_mat @ c_mat)

        for child in root_tree:
            if _strip_ns(child.tag) == "build":
                for item in child:
                    if _strip_ns(item.tag) == "item" and item.attrib.get("objectid"):
                        walk_raw(
                            root_model_path,
                            item.attrib["objectid"],
                            _parse_3mf_transform(item.attrib.get("transform")),
                        )

    if not raw_parts:
        raise ValueError("No se encontraron mallas pintadas válidas en el archivo .3mf.")

    eff_instances = instances if instances else [
        ModelInstanceTransform(
            instance_id="inst_1",
            offset_x=offset_x,
            offset_y=offset_y,
            offset_z=offset_z,
            scale_percent=scale_percent,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            drop_to_bed=drop_to_bed,
        )
    ]

    target_cx, target_cy = _bed_center_xy(printer)
    model_chunks: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">',
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>',
        ' <metadata name="BambuStudio:MmPaintingVersion">1</metadata>',
        " <resources>",
    ]
    next_oid = 1
    build_ids: list[int] = []
    settings_parts: list[tuple[int, str]] = []

    for inst_idx, inst in enumerate(eff_instances, start=1):
        sx, sy, sz = _resolve_scale_vec(
            inst.scale_percent, inst.scale_x, inst.scale_y, inst.scale_z
        )
        has_rot = abs(inst.rot_x) > 1e-3 or abs(inst.rot_y) > 1e-3 or abs(inst.rot_z) > 1e-3
        rot_mat3 = (
            trimesh.transformations.euler_matrix(
                math.radians(inst.rot_x),
                math.radians(inst.rot_y),
                math.radians(inst.rot_z),
                axes="sxyz",
            )[:3, :3]
            if has_rot
            else np.eye(3, dtype=np.float64)
        )

        transformed_parts: list[tuple[str, np.ndarray, list[tuple[int, int, int, str | None]]]] = []
        min_pts: list[np.ndarray] = []
        max_pts: list[np.ndarray] = []
        scale_vec = np.array([sx, sy, sz], dtype=np.float64)

        for pname, verts, tri_rows in raw_parts:
            v_tx = (verts * scale_vec) @ rot_mat3.T
            min_pts.append(v_tx.min(axis=0))
            max_pts.append(v_tx.max(axis=0))
            transformed_parts.append((pname, v_tx, tri_rows))

        g_min = np.min(np.vstack(min_pts), axis=0)
        g_max = np.max(np.vstack(max_pts), axis=0)
        z_lift = 0.0 if inst.drop_to_bed else max(0.0, float(inst.offset_z))
        shift = np.array(
            [
                target_cx + float(inst.offset_x) - float((g_min[0] + g_max[0]) / 2.0),
                target_cy + float(inst.offset_y) - float((g_min[1] + g_max[1]) / 2.0),
                -float(g_min[2]) + z_lift,
            ],
            dtype=np.float64,
        )

        for pname, v_tx, tri_rows in transformed_parts:
            oid = next_oid
            next_oid += 1
            build_ids.append(oid)
            v_final = v_tx + shift
            part_label = pname if len(eff_instances) == 1 else f"{pname}_{inst_idx}"
            safe_name = xml_escape(part_label, {'"': "&quot;", "'": "&apos;"})
            settings_parts.append((oid, safe_name))

            v_lines = [
                f'     <vertex x="{vx:.5f}" y="{vy:.5f}" z="{vz:.5f}"/>'
                for vx, vy, vz in v_final
            ]
            f_lines = [
                (
                    f'     <triangle v1="{v1}" v2="{v2}" v3="{v3}" paint_color="{pc}"/>'
                    if pc
                    else f'     <triangle v1="{v1}" v2="{v2}" v3="{v3}"/>'
                )
                for v1, v2, v3, pc in tri_rows
            ]

            model_chunks.append(f'  <object id="{oid}" name="{safe_name}" type="model">')
            model_chunks.append("   <mesh>")
            model_chunks.append("    <vertices>")
            model_chunks.extend(v_lines)
            model_chunks.append("    </vertices>")
            model_chunks.append("    <triangles>")
            model_chunks.extend(f_lines)
            model_chunks.append("    </triangles>")
            model_chunks.append("   </mesh>")
            model_chunks.append("  </object>")

    model_chunks.append(" </resources>")
    model_chunks.append(" <build>")
    for oid in build_ids:
        model_chunks.append(f'  <item objectid="{oid}"/>')
    model_chunks.extend([" </build>", "</model>"])

    settings_chunks: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<config>",
    ]
    for oid, safe_name in settings_parts:
        settings_chunks.extend([
            f' <object id="{oid}">',
            f'  <metadata key="name" value="{safe_name}"/>',
            f'  <part id="{oid}" subtype="normal_part">',
            f'   <metadata key="name" value="{safe_name}"/>',
            '   <metadata key="extruder" value="1"/>',
            "  </part>",
            " </object>",
        ])
    settings_chunks.append("</config>")

    out_3mf = out_dir / "painted_multicolor.3mf"
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
        '<Default Extension="config" ContentType="text/xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Target="/3D/3dmodel.model" Id="rel-1" '
        'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
        "</Relationships>"
    )

    tmp_3mf = out_3mf.with_suffix(".3mf.tmp")
    with tmp_3mf.open("wb") as raw_fh:
        with zipfile.ZipFile(raw_fh, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", content_types)
            zf.writestr("_rels/.rels", rels_xml)
            zf.writestr("3D/3dmodel.model", "\n".join(model_chunks))
            zf.writestr("Metadata/model_settings.config", "\n".join(settings_chunks))
        raw_fh.flush()
        os.fsync(raw_fh.fileno())
    os.replace(tmp_3mf, out_3mf)

    return out_3mf


def load_and_transform_mesh(
    model_path: Path,
    printer: PrinterConfig | None = None,
    scale_percent: float = 100.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    drop_to_bed: bool = True,
    instances: list[ModelInstanceTransform] | None = None,
) -> trimesh.Trimesh:
    """Carga `.stl`/`.3mf` y ensambla 1 o N instancias transformadas sobre el plato."""
    raw = load_raw_mesh(model_path)
    if instances and len(instances) > 0:
        parts = [
            apply_transform_to_mesh(
                raw,
                printer=printer,
                scale_percent=inst.scale_percent,
                rot_x=inst.rot_x,
                rot_y=inst.rot_y,
                rot_z=inst.rot_z,
                scale_x=inst.scale_x,
                scale_y=inst.scale_y,
                scale_z=inst.scale_z,
                offset_x=inst.offset_x,
                offset_y=inst.offset_y,
                offset_z=inst.offset_z,
                drop_to_bed=inst.drop_to_bed,
                copy=True,
            )
            for inst in instances
        ]
        return parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)

    return apply_transform_to_mesh(
        raw,
        printer=printer,
        scale_percent=scale_percent,
        rot_x=rot_x,
        rot_y=rot_y,
        rot_z=rot_z,
        scale_x=scale_x,
        scale_y=scale_y,
        scale_z=scale_z,
        offset_x=offset_x,
        offset_y=offset_y,
        offset_z=offset_z,
        drop_to_bed=drop_to_bed,
        copy=False,
    )


def analyze_mesh_object(
    mesh: trimesh.Trimesh,
    printer: PrinterConfig,
    mesh_id: str,
    scale_percent: float = 100.0,
    file_format: str = "stl",
    multimaterial_parts: list[MultimaterialPartInfo] | None = None,
    detected_extruder_count: int = 1,
    is_multicolor: bool = False,
    extruder_triangle_percentages: dict[str, float] | None = None,
    detected_filament_colors: list[str] | None = None,
    detected_colors: list[DetectedColorInfo] | None = None,
    scene_objects: list[SceneObjectInfo] | None = None,
) -> MeshAnalysisResponse:
    """Evalúa dimensiones, encaje en cama, auto-escala 95%, área base y voladizos > 50°."""
    extents = mesh.extents
    dim_x = round(float(extents[0]), 2)
    dim_y = round(float(extents[1]), 2)
    dim_z = round(float(extents[2]), 2)
    dimensions = DimensionsMM(x=dim_x, y=dim_y, z=dim_z)

    warnings: list[str] = []
    fits = True
    recommended_scale_percent = round(scale_percent, 1)

    if not mesh.is_watertight:
        warnings.append("Malla non-manifold (el laminador la reparará automáticamente).")

    # Validación de envolvente física por cinemática respecto al plato real
    b_min, b_max = mesh.bounds
    max_z_pos = float(b_max[2])
    min_z_pos = float(b_min[2])

    if printer.kinematics == "delta" and printer.diameter_mm is not None:
        max_radius = printer.diameter_mm / 2.0
        verts_xy = mesh.vertices[:, :2]
        model_radius = float(np.linalg.norm(verts_xy, axis=1).max())
        xy_center = (verts_xy.min(axis=0) + verts_xy.max(axis=0)) / 2.0
        centered_radius = float(np.linalg.norm(verts_xy - xy_center, axis=1).max())

        fit_ratio_r = (max_radius * 0.95) / max(centered_radius, 1e-6)
        fit_ratio_z = (printer.height_mm * 0.95) / max(dim_z, 1e-6)
        fit_ratio = min(fit_ratio_r, fit_ratio_z)
        recommended_scale_percent = max(1.0, round(scale_percent * fit_ratio, 1))

        if model_radius > max_radius + 0.05:
            fits = False
            warnings.append(
                f"Radio XY ({model_radius:.1f} mm) excede la cama de {printer.display_name} ({max_radius:.1f} mm)."
            )
        if max_z_pos > printer.height_mm + 0.05:
            fits = False
            warnings.append(
                f"Altura Z ({max_z_pos:.1f} mm) supera el máximo de {printer.display_name} ({printer.height_mm:.0f} mm)."
            )
        elif (
            printer.usable_edge_z_mm
            and max_z_pos > printer.usable_edge_z_mm
            and model_radius > max_radius * 0.65
        ):
            warnings.append(
                f"Advertencia Delta: Z={max_z_pos:.1f} mm con radio={model_radius:.1f} mm cerca del límite útil ({printer.usable_edge_z_mm:.0f} mm)."
            )
    elif printer.bed_mm is not None:
        bed_x, bed_y, bed_z = printer.bed_mm
        fit_ratio = min(
            (bed_x * 0.95) / max(dim_x, 1e-6),
            (bed_y * 0.95) / max(dim_y, 1e-6),
            (bed_z * 0.95) / max(dim_z, 1e-6),
        )
        recommended_scale_percent = max(1.0, round(scale_percent * fit_ratio, 1))

        if dim_x > bed_x + 0.05 or dim_y > bed_y + 0.05 or dim_z > bed_z + 0.05:
            fits = False
            warnings.append(
                f"Dimensiones ({dim_x:.1f}×{dim_y:.1f}×{dim_z:.1f} mm) exceden {printer.display_name} ({bed_x:.0f}×{bed_y:.0f}×{bed_z:.0f} mm)."
            )
        elif (
            b_min[0] < -0.05
            or b_max[0] > bed_x + 0.05
            or b_min[1] < -0.05
            or b_max[1] > bed_y + 0.05
            or max_z_pos > bed_z + 0.05
            or min_z_pos < -0.05
        ):
            fits = False
            warnings.append(
                f"Posición/instancias fuera del volumen de {printer.display_name} ({bed_x:.0f}×{bed_y:.0f}×{bed_z:.0f} mm)."
            )

    # Detección de voladizos críticos (> 50°) y área de apoyo en la base Z=0
    min_z = float(mesh.bounds[0][2])
    face_centers_z = mesh.triangles_center[:, 2]
    normals_z = mesh.face_normals[:, 2]
    areas = mesh.area_faces
    total_area = float(areas.sum()) or 1.0

    critical_mask = (normals_z < -CRITICAL_OVERHANG_COS) & (face_centers_z > min_z + 0.25)
    overhang_area = float(areas[critical_mask].sum())
    overhang_ratio = round(overhang_area / total_area, 4)
    suggests_supports = overhang_ratio > 0.015

    base_faces_mask = (normals_z < -0.75) & (face_centers_z <= min_z + 0.6)
    flat_contact_area = float(areas[base_faces_mask].sum())
    if flat_contact_area < 20.0:
        low_verts = mesh.vertices[mesh.vertices[:, 2] <= min_z + 0.8, :2]
        if len(low_verts) >= 3:
            span = low_verts.max(axis=0) - low_verts.min(axis=0)
            flat_contact_area = max(flat_contact_area, float(span[0] * span[1]) * 0.25)
    base_contact_area_mm2 = round(flat_contact_area, 2)

    slenderness = dim_z / max(math.sqrt(base_contact_area_mm2), 1.0)
    suggests_raft = (dim_z > 45.0 and base_contact_area_mm2 < 320.0) or (
        dim_z > 70.0 and slenderness > 4.5
    )

    if suggests_supports:
        warnings.append(
            f"Voladizos > 50° ({overhang_ratio * 100:.1f}% del área); se sugiere activar soportes."
        )
    if suggests_raft:
        warnings.append(
            f"Base de contacto reducida ({base_contact_area_mm2:.0f} mm² para Z={dim_z:.1f} mm); se recomienda Balsa (Raft) o Brim."
        )

    fmt_literal = "3mf" if file_format == "3mf" else "stl"
    return MeshAnalysisResponse(
        mesh_id=mesh_id,
        file_format=fmt_literal,
        fits_in_volume=fits,
        dimensions_mm=dimensions,
        triangle_count=int(len(mesh.faces)),
        is_watertight=bool(mesh.is_watertight),
        overhang_ratio=overhang_ratio,
        suggests_supports=suggests_supports,
        base_contact_area_mm2=base_contact_area_mm2,
        suggests_raft=suggests_raft,
        recommended_scale_percent=recommended_scale_percent,
        multimaterial_parts=multimaterial_parts or [],
        detected_extruder_count=detected_extruder_count,
        is_multicolor=is_multicolor,
        extruder_triangle_percentages=extruder_triangle_percentages or {},
        detected_filament_colors=detected_filament_colors or [],
        detected_colors=detected_colors or [],
        scene_objects=scene_objects or [],
        warnings=warnings,
    )


def _compute_3mf_color_z_ranges(
    threemf_path: Path,
    rot_mat: np.ndarray,
    s_vec: np.ndarray,
) -> dict[int, tuple[float, float]]:
    """Calcula `(z_min_mm, z_max_mm)` relativo a la cama por cada zona de color `0..N-1` en `.3mf`."""
    z_bounds: dict[int, list[float]] = {}
    global_z_min = float("inf")

    with zipfile.ZipFile(threemf_path, "r") as zf:
        names = zf.namelist()
        objects_by_key: dict[tuple[str, str], ET.Element] = {}
        root_model_path: str | None = None
        root_tree: ET.Element | None = None

        for mf in [n for n in names if n.lower().endswith(".model")]:
            norm_mf = _norm_zip_path(mf)
            el_root = ET.fromstring(zf.read(mf))
            if norm_mf.lower() == "3d/3dmodel.model" or root_model_path is None:
                root_model_path = norm_mf
                root_tree = el_root
            for res_el in el_root:
                if _strip_ns(res_el.tag) != "resources":
                    continue
                for child in res_el:
                    if _strip_ns(child.tag) == "object" and child.attrib.get("id"):
                        objects_by_key[(norm_mf, child.attrib["id"])] = child

        if root_tree is None or root_model_path is None:
            return {}

        def walk_z(model_path: str, obj_id: str, cur_mat: np.ndarray) -> None:
            nonlocal global_z_min
            obj_el = objects_by_key.get((model_path, obj_id))
            if obj_el is None:
                return
            for ch in obj_el:
                tn = _strip_ns(ch.tag)
                if tn == "mesh":
                    verts_raw: list[list[float]] = []
                    tris_el: ET.Element | None = None
                    for sub in ch:
                        stn = _strip_ns(sub.tag)
                        if stn == "vertices":
                            for v in sub:
                                verts_raw.append(
                                    [
                                        float(v.attrib.get("x", 0.0)),
                                        float(v.attrib.get("y", 0.0)),
                                        float(v.attrib.get("z", 0.0)),
                                    ]
                                )
                        elif stn == "triangles":
                            tris_el = sub
                    if not verts_raw or tris_el is None:
                        continue
                    v_arr = np.asarray(verts_raw, dtype=np.float64)
                    ones = np.ones((len(v_arr), 1), dtype=np.float64)
                    v_world = (np.hstack([v_arr, ones]) @ cur_mat.T)[:, :3]
                    z_vals = ((v_world * s_vec) @ rot_mat[2, :].T)
                    if len(z_vals) > 0:
                        g_min = float(z_vals.min())
                        if g_min < global_z_min:
                            global_z_min = g_min
                    for tri in tris_el:
                        v1 = int(tri.attrib["v1"])
                        v2 = int(tri.attrib["v2"])
                        v3 = int(tri.attrib["v3"])
                        pc = tri.attrib.get("paint_color")
                        if pc is not None:
                            c_idx = decode_paint_color_extruder(pc) - 1
                        elif "pid" in tri.attrib and "p1" in tri.attrib:
                            try:
                                c_idx = int(tri.attrib["p1"])
                            except ValueError:
                                c_idx = 0
                        else:
                            c_idx = 0
                        t_z0 = float(min(z_vals[v1], z_vals[v2], z_vals[v3]))
                        t_z1 = float(max(z_vals[v1], z_vals[v2], z_vals[v3]))
                        if c_idx not in z_bounds:
                            z_bounds[c_idx] = [t_z0, t_z1]
                        else:
                            if t_z0 < z_bounds[c_idx][0]:
                                z_bounds[c_idx][0] = t_z0
                            if t_z1 > z_bounds[c_idx][1]:
                                z_bounds[c_idx][1] = t_z1
                elif tn == "components":
                    for comp in ch:
                        c_id = comp.attrib.get("objectid")
                        if not c_id:
                            continue
                        comp_mat = cur_mat @ _parse_3mf_transform(comp.attrib.get("transform"))
                        p_attr = next(
                            (v for k, v in comp.attrib.items() if k == "path" or k.endswith("}path")),
                            None,
                        )
                        next_mp = _norm_zip_path(p_attr) if p_attr else model_path
                        walk_z(next_mp, c_id, comp_mat)

        for child in root_tree:
            if _strip_ns(child.tag) == "build":
                for item in child:
                    if _strip_ns(item.tag) == "item" and item.attrib.get("objectid"):
                        item_mat = _parse_3mf_transform(item.attrib.get("transform"))
                        walk_z(root_model_path, item.attrib["objectid"], item_mat)

    if not math.isfinite(global_z_min):
        global_z_min = 0.0
    return {
        c_idx: (
            round(max(0.0, b[0] - global_z_min), 2),
            round(max(0.0, b[1] - global_z_min), 2),
        )
        for c_idx, b in z_bounds.items()
    }


def analyze_model_file(
    model_path: Path,
    printer: PrinterConfig,
    mesh_id: str = "",
    scale_percent: float = 100.0,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
    offset_z: float = 0.0,
    drop_to_bed: bool = True,
    instances: list[ModelInstanceTransform] | None = None,
) -> MeshAnalysisResponse:
    """Lee un `.stl` o `.3mf`, extrae partes multicolor, ensambla instancias y evalúa geometría."""
    is_3mf = model_path.suffix.lower() == ".3mf"
    parts_info: list[MultimaterialPartInfo] = []
    detected_extruder_count = 1
    is_multicolor = False
    extruder_triangle_percentages: dict[str, float] = {}
    detected_filament_colors: list[str] = []
    detected_colors_list: list[DetectedColorInfo] = []
    scene_objects_list: list[SceneObjectInfo] = []

    if is_3mf:
        extracted = extract_3mf_parts_and_meshes(model_path)
        parts_info = [p for p, _ in extracted]
        raw = extracted[0][1] if len(extracted) == 1 else trimesh.util.concatenate([m for _, m in extracted])

        paint_info = inspect_3mf_multicolor_info(model_path)
        part_extruders = {p.extruder for p in parts_info}
        painted_exts = int(paint_info.get("active_painted_extruders", 1))
        has_tri_paint = bool(paint_info.get("has_triangle_painting", False))
        detected_extruder_count = max(
            1,
            painted_exts if has_tri_paint else 1,
            len(part_extruders),
            len(parts_info) if len(parts_info) > 1 and len(part_extruders) > 1 else 1,
        )
        is_multicolor = detected_extruder_count >= 2 or has_tri_paint and painted_exts >= 2
        extruder_triangle_percentages = dict(paint_info.get("extruder_triangle_percentages", {}))  # type: ignore[arg-type]
        detected_filament_colors = list(paint_info.get("detected_filament_colors", []))  # type: ignore[arg-type]

        if not detected_filament_colors and parts_info:
            slot_colors: list[str] = [""] * 4
            for p in parts_info:
                if p.color_hex and 1 <= p.extruder <= 4 and not slot_colors[p.extruder - 1]:
                    slot_colors[p.extruder - 1] = p.color_hex
            detected_filament_colors = [c for c in slot_colors if c]

        # Calcular rangos verticales [z_min_mm, z_max_mm] por parte tras rotación/escala activa
        if extracted:
            eff_inst = instances[0] if (instances and len(instances) > 0) else None
            p_rx = eff_inst.rot_x if eff_inst else rot_x
            p_ry = eff_inst.rot_y if eff_inst else rot_y
            p_rz = eff_inst.rot_z if eff_inst else rot_z
            p_sp = eff_inst.scale_percent if eff_inst else scale_percent
            p_sx = eff_inst.scale_x if eff_inst else scale_x
            p_sy = eff_inst.scale_y if eff_inst else scale_y
            p_sz = eff_inst.scale_z if eff_inst else scale_z
            rot_mat = trimesh.transformations.euler_matrix(
                math.radians(p_rx),
                math.radians(p_ry),
                math.radians(p_rz),
                axes="sxyz",
            )[:3, :3]
            s_vec = _resolve_scale_vec(p_sp, p_sx, p_sy, p_sz)
            raw_z_bounds: list[tuple[float, float]] = []
            global_z_min = float("inf")
            for _, p_mesh in extracted:
                if len(p_mesh.vertices) == 0:
                    raw_z_bounds.append((0.0, 0.0))
                    continue
                pts = (p_mesh.vertices * s_vec) @ rot_mat.T
                z0 = float(pts[:, 2].min())
                z1 = float(pts[:, 2].max())
                raw_z_bounds.append((z0, z1))
                if z0 < global_z_min:
                    global_z_min = z0
            if not math.isfinite(global_z_min):
                global_z_min = 0.0
            for idx, (z0, z1) in enumerate(raw_z_bounds):
                parts_info[idx].z_min_mm = round(max(0.0, z0 - global_z_min), 2)
                parts_info[idx].z_max_mm = round(max(0.0, z1 - global_z_min), 2)

            if len(parts_info) > 4:
                slot_intervals: dict[int, list[tuple[float, float]]] = {0: [], 1: [], 2: [], 3: []}
                for idx, p in enumerate(parts_info):
                    if idx < 4:
                        base_slot = max(0, min(3, p.extruder - 1))
                        p.suggested_slot = base_slot
                        slot_intervals[base_slot].append((p.z_min_mm, p.z_max_mm))
                    else:
                        chosen_slot: int | None = None
                        for cand in range(4):
                            if all(ex_max < p.z_min_mm for _, ex_max in slot_intervals[cand]):
                                chosen_slot = cand
                                break
                        if chosen_slot is None:
                            chosen_slot = 0
                        p.suggested_slot = chosen_slot
                        slot_intervals[chosen_slot].append((p.z_min_mm, p.z_max_mm))

            # Construir lista unificada `detected_colors` (Color #1 .. Color #N) con rangos Z
            color_z_map = _compute_3mf_color_z_ranges(model_path, rot_mat, s_vec) if has_tri_paint else {}
            if extruder_triangle_percentages:
                sorted_zones = sorted(
                    extruder_triangle_percentages.items(),
                    key=lambda kv: int(kv[0][1:]) if kv[0].startswith("T") and kv[0][1:].isdigit() else 999,
                )
                slot_int_colors: dict[int, list[tuple[float, float]]] = {0: [], 1: [], 2: [], 3: []}
                for order_idx, (t_key, pct_val) in enumerate(sorted_zones):
                    z_num = int(t_key[1:]) if t_key.startswith("T") and t_key[1:].isdigit() else order_idx
                    z_min_c, z_max_c = color_z_map.get(z_num, (0.0, round(float(max((p.z_max_mm for p in parts_info), default=0.0)), 2)))
                    hex_c = (
                        detected_filament_colors[z_num]
                        if z_num < len(detected_filament_colors)
                        else "#94A3B8"
                    )
                    if order_idx < 4:
                        sug_slot = order_idx
                    else:
                        sug_slot = next(
                            (
                                cand
                                for cand in range(4)
                                if all(ex_max + 0.4 <= z_min_c for _, ex_max in slot_int_colors[cand])
                            ),
                            0,
                        )
                    slot_int_colors[sug_slot].append((z_min_c, z_max_c))
                    detected_colors_list.append(
                        DetectedColorInfo(
                            index=order_idx + 1,
                            zone_key=f"zone_{z_num}",
                            name=f"Color #{order_idx + 1}",
                            hex_color=hex_c,
                            percentage=float(pct_val),
                            z_min_mm=z_min_c,
                            z_max_mm=z_max_c,
                            suggested_slot=sug_slot,
                        )
                    )
            elif len(parts_info) > 1:
                total_tris = max(1, sum(p.triangle_count for p in parts_info))
                for order_idx, p in enumerate(parts_info):
                    sug = p.suggested_slot if p.suggested_slot is not None else min(3, max(0, p.extruder - 1))
                    detected_colors_list.append(
                        DetectedColorInfo(
                            index=order_idx + 1,
                            zone_key=p.part_id,
                            name=p.name or f"Color #{order_idx + 1}",
                            hex_color=p.color_hex or "#94A3B8",
                            percentage=round((p.triangle_count / total_tris) * 100.0, 1),
                            z_min_mm=p.z_min_mm,
                            z_max_mm=p.z_max_mm,
                            suggested_slot=sug,
                        )
                    )

        if len(extracted) > 1 and mesh_id:
            scene_objects_list = _export_scene_objects_to_cache(mesh_id, extracted)
    else:
        raw = load_raw_mesh(model_path)

    if instances and len(instances) > 0:
        inst_meshes = [
            apply_transform_to_mesh(
                raw,
                printer=printer,
                scale_percent=inst.scale_percent,
                rot_x=inst.rot_x,
                rot_y=inst.rot_y,
                rot_z=inst.rot_z,
                scale_x=inst.scale_x,
                scale_y=inst.scale_y,
                scale_z=inst.scale_z,
                offset_x=inst.offset_x,
                offset_y=inst.offset_y,
                offset_z=inst.offset_z,
                drop_to_bed=inst.drop_to_bed,
                copy=True,
            )
            for inst in instances
        ]
        mesh = inst_meshes[0] if len(inst_meshes) == 1 else trimesh.util.concatenate(inst_meshes)
    else:
        mesh = apply_transform_to_mesh(
            raw,
            printer=printer,
            scale_percent=scale_percent,
            rot_x=rot_x,
            rot_y=rot_y,
            rot_z=rot_z,
            scale_x=scale_x,
            scale_y=scale_y,
            scale_z=scale_z,
            offset_x=offset_x,
            offset_y=offset_y,
            offset_z=offset_z,
            drop_to_bed=drop_to_bed,
            copy=False,
        )

    return analyze_mesh_object(
        mesh,
        printer,
        mesh_id=mesh_id,
        scale_percent=scale_percent,
        file_format="3mf" if is_3mf else "stl",
        multimaterial_parts=parts_info,
        detected_extruder_count=detected_extruder_count,
        is_multicolor=is_multicolor,
        extruder_triangle_percentages=extruder_triangle_percentages,
        detected_filament_colors=detected_filament_colors,
        detected_colors=detected_colors_list,
        scene_objects=scene_objects_list,
    )


def _rot_z_mat(deg: float) -> np.ndarray:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def _rot_x_mat(deg: float) -> np.ndarray:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]])


def _rot_y_mat(deg: float) -> np.ndarray:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def auto_orient_mesh(
    model_path: Path,
    printer: PrinterConfig,
    mesh_id: str,
    scale_percent: float = 100.0,
) -> AutoOrientResponse:
    """Calcula con `trimesh.bounds.oriented_bounds` la rotación óptima manteniendo la escala."""
    is_3mf = model_path.suffix.lower() == ".3mf"
    parts_info: list[MultimaterialPartInfo] = []
    if is_3mf:
        extracted = extract_3mf_parts_and_meshes(model_path)
        parts_info = [p for p, _ in extracted]
        raw_mesh = (
            extracted[0][1]
            if len(extracted) == 1
            else trimesh.util.concatenate([m for _, m in extracted])
        )
    else:
        raw_mesh = load_raw_mesh(model_path)

    eval_mesh = raw_mesh.convex_hull if len(raw_mesh.vertices) > 15000 else raw_mesh
    verts = eval_mesh.vertices.copy()
    if abs(scale_percent - 100.0) > 1e-3:
        verts = verts * (scale_percent / 100.0)

    to_origin, _ = trimesh.bounds.oriented_bounds(eval_mesh)
    r_obb = to_origin[:3, :3]

    candidates: list[tuple[np.ndarray, float]] = [(np.eye(3), 0.0), (_rot_z_mat(45.0), 0.05)]

    base_obb_rotations: list[np.ndarray] = []
    for perm in itertools.permutations([0, 1, 2]):
        for sx, sy, sz in itertools.product([-1.0, 1.0], repeat=3):
            p_mat = np.zeros((3, 3))
            p_mat[0, perm[0]] = sx
            p_mat[1, perm[1]] = sy
            p_mat[2, perm[2]] = sz
            if round(float(np.linalg.det(p_mat))) == 1:
                r_cand = p_mat @ r_obb
                base_obb_rotations.append(r_cand)
                candidates.append((r_cand, 0.0))
                candidates.append((_rot_z_mat(45.0) @ r_cand, 0.05))

    for r_cand in base_obb_rotations[:6]:
        for angle in (20.0, -20.0, 35.0, -35.0, 45.0, -45.0):
            candidates.append((_rot_x_mat(angle) @ r_cand, 1.0))
            candidates.append((_rot_y_mat(angle) @ r_cand, 1.0))

    best_score: tuple[float, ...] | None = None
    best_euler = (0.0, 0.0, 0.0)

    for r_mat, tilt_penalty in candidates:
        rot_pts = verts @ r_mat.T
        p_min = rot_pts.min(axis=0)
        p_max = rot_pts.max(axis=0)
        ext = p_max - p_min
        dx, dy, dz = float(ext[0]), float(ext[1]), float(ext[2])

        if printer.kinematics == "delta" and printer.diameter_mm is not None:
            max_rad = printer.diameter_mm / 2.0
            xy_c = (p_min[:2] + p_max[:2]) / 2.0
            rad = float(np.linalg.norm(rot_pts[:, :2] - xy_c, axis=1).max())
            fits = rad <= max_rad and dz <= printer.height_mm
            rec_scale = min(
                (max_rad * 0.95) / max(rad, 1e-6),
                (printer.height_mm * 0.95) / max(dz, 1e-6),
            )
            footprint = rad * rad
        elif printer.bed_mm is not None:
            bed_x, bed_y, bed_z = printer.bed_mm
            fits = dx <= bed_x and dy <= bed_y and dz <= bed_z
            rec_scale = min(
                (bed_x * 0.95) / max(dx, 1e-6),
                (bed_y * 0.95) / max(dy, 1e-6),
                (bed_z * 0.95) / max(dz, 1e-6),
            )
            footprint = dx * dy
        else:
            fits = True
            rec_scale = 1.0
            footprint = dx * dy

        base_fraction = float(np.mean(rot_pts[:, 2] <= float(p_min[2]) + 1.5))

        m4 = np.eye(4)
        m4[:3, :3] = r_mat
        rx, ry, rz = (
            round((math.degrees(a) % 360.0), 1)
            for a in trimesh.transformations.euler_from_matrix(m4, axes="sxyz")
        )

        score = (
            0.0 if fits else 1.0,
            0.0 if fits else -round(rec_scale, 4),
            tilt_penalty,
            round(footprint, 1),
            -round(base_fraction, 3),
        )
        if best_score is None or score < best_score:
            best_score = score
            best_euler = (rx, ry, rz)

    oriented_mesh = apply_transform_to_mesh(
        raw_mesh,
        printer=printer,
        scale_percent=scale_percent,
        rot_x=best_euler[0],
        rot_y=best_euler[1],
        rot_z=best_euler[2],
        copy=False,
    )
    analysis = analyze_mesh_object(
        oriented_mesh,
        printer,
        mesh_id=mesh_id,
        scale_percent=scale_percent,
        file_format="3mf" if is_3mf else "stl",
        multimaterial_parts=parts_info,
    )

    if analysis.fits_in_volume:
        msg = (
            f"Auto-orientado al {scale_percent:.0f}% "
            f"({best_euler[0]}°, {best_euler[1]}°, {best_euler[2]}°): cabe en cama sin escalar."
        )
    else:
        msg = (
            f"Orientación óptima de huella mínima ({best_euler[0]}°, {best_euler[1]}°, {best_euler[2]}°) "
            f"al {scale_percent:.0f}%. Escala sugerida máx: {analysis.recommended_scale_percent}%."
        )

    return AutoOrientResponse(
        mesh_id=mesh_id,
        rot_x=best_euler[0],
        rot_y=best_euler[1],
        rot_z=best_euler[2],
        scale_percent=scale_percent,
        message=msg,
        analysis=analysis,
    )


def auto_arrange_instances(
    model_path: Path,
    printer: PrinterConfig,
    instances: list[ModelInstanceTransform],
    min_distance_mm: float = 6.0,
) -> AutoArrangeResponse:
    """Empaqueta N instancias sin colisiones sobre cama circular (Delta) o rectangular."""
    if not instances:
        return AutoArrangeResponse(
            instances=[],
            fits_in_volume=True,
            warnings=[],
            message="Sin instancias que ordenar.",
        )

    raw = load_raw_mesh(model_path)
    eff_instances = [inst.model_copy(deep=True) for inst in instances]

    # Medir huella XY real de cada instancia tras su escala y rotación
    footprints: list[tuple[int, float, float, float]] = []
    for idx, inst in enumerate(eff_instances):
        m = apply_transform_to_mesh(
            raw,
            printer=None,
            scale_percent=inst.scale_percent,
            rot_x=inst.rot_x,
            rot_y=inst.rot_y,
            rot_z=inst.rot_z,
            scale_x=inst.scale_x,
            scale_y=inst.scale_y,
            scale_z=inst.scale_z,
            drop_to_bed=True,
            copy=True,
        )
        ext = m.extents
        w, d, h = float(ext[0]), float(ext[1]), float(ext[2])
        footprints.append((idx, w, d, h))

    # Si solo hay 1 instancia, centrarla en el plato
    if len(eff_instances) == 1:
        eff_instances[0].offset_x = 0.0
        eff_instances[0].offset_y = 0.0
        if eff_instances[0].drop_to_bed:
            eff_instances[0].offset_z = 0.0
        analysis = analyze_model_file(model_path, printer, instances=eff_instances)
        return AutoArrangeResponse(
            instances=eff_instances,
            fits_in_volume=analysis.fits_in_volume,
            warnings=analysis.warnings,
            message="Instancia centrada en el plato.",
        )

    is_delta = printer.kinematics == "delta" and printer.diameter_mm is not None
    edge_margin = 3.0
    max_r = ((printer.diameter_mm / 2.0) - edge_margin) if is_delta and printer.diameter_mm else 0.0
    half_bx = ((printer.bed_mm[0] / 2.0) - edge_margin) if printer.bed_mm else 110.0
    half_by = ((printer.bed_mm[1] / 2.0) - edge_margin) if printer.bed_mm else 110.0
    max_z_bed = printer.height_mm

    # Precalcular candidatos ordenados por cercanía al centro (espiral cartesiana fina)
    bound_lim = max_r if is_delta else max(half_bx, half_by)
    step = 4.0
    coords = np.arange(-bound_lim, bound_lim + step * 0.5, step)
    candidates: list[tuple[float, float]] = []
    for cx in coords:
        for cy in coords:
            if is_delta and math.hypot(cx, cy) > max_r:
                continue
            candidates.append((round(float(cx), 2), round(float(cy), 2)))
    candidates.sort(key=lambda pt: (pt[0] * pt[0] + pt[1] * pt[1], abs(pt[1]), abs(pt[0])))

    def inside_bed(ox: float, oy: float, w: float, d: float) -> bool:
        hw, hd = w * 0.5, d * 0.5
        if is_delta:
            return all(
                math.hypot(ox + sx * hw, oy + sy * hd) <= max_r
                for sx in (-1.0, 1.0)
                for sy in (-1.0, 1.0)
            )
        return (abs(ox) + hw <= half_bx) and (abs(oy) + hd <= half_by)

    def overlaps(ox: float, oy: float, w: float, d: float, placed_list: list[tuple[float, float, float, float]]) -> bool:
        for px, py, pw, pd in placed_list:
            if (
                abs(ox - px) < (w + pw) * 0.5 + min_distance_mm
                and abs(oy - py) < (d + pd) * 0.5 + min_distance_mm
            ):
                return True
        return False

    # Ordenar mayor a menor área para empaquetado óptimo tipo Arrange.cpp
    ordered = sorted(footprints, key=lambda item: (item[1] * item[2], item[3]), reverse=True)
    placed: list[tuple[float, float, float, float]] = []
    placed_map: dict[int, tuple[float, float]] = {}
    overflow_count = 0

    for idx, w, d, h in ordered:
        found: tuple[float, float] | None = None
        for cx, cy in candidates:
            if not inside_bed(cx, cy, w, d):
                continue
            if not overlaps(cx, cy, w, d, placed):
                found = (cx, cy)
                break

        if found is None:
            overflow_count += 1
            # Colocar fuera en anillo auxiliar para visibilidad si excede la cama
            angle = (len(placed) * 2.399963)
            dist = (max_r if is_delta else max(half_bx, half_by)) + max(w, d) * 0.65
            found = (round(math.cos(angle) * dist, 1), round(math.sin(angle) * dist, 1))

        placed.append((found[0], found[1], w, d))
        placed_map[idx] = found

    # Recentrar el conjunto completo si cabe holgadamente en la cama para simetría estética
    if overflow_count == 0 and placed:
        all_min_x = min(px - pw * 0.5 for px, _, pw, _ in placed)
        all_max_x = max(px + pw * 0.5 for px, _, pw, _ in placed)
        all_min_y = min(py - pd * 0.5 for _, py, _, pd in placed)
        all_max_y = max(py + pd * 0.5 for _, py, _, pd in placed)
        shift_x = -(all_min_x + all_max_x) * 0.5
        shift_y = -(all_min_y + all_max_y) * 0.5
        if all(
            inside_bed(placed_map[i][0] + shift_x, placed_map[i][1] + shift_y, w, d)
            for i, w, d, _ in footprints
        ):
            for i in placed_map:
                ox, oy = placed_map[i]
                placed_map[i] = (round(ox + shift_x, 2), round(oy + shift_y, 2))

    for i, inst in enumerate(eff_instances):
        ox, oy = placed_map[i]
        inst.offset_x = ox
        inst.offset_y = oy
        if inst.drop_to_bed:
            inst.offset_z = 0.0

    analysis = analyze_model_file(model_path, printer, instances=eff_instances)
    msg = (
        f"Auto-ordenamiento completado para {len(eff_instances)} piezas (holgura {min_distance_mm:.0f} mm)."
        if overflow_count == 0 and analysis.fits_in_volume
        else f"Auto-ordenamiento parcial: {overflow_count} pieza(s) exceden el área disponible (altura máx {max_z_bed:.0f} mm)."
    )
    return AutoArrangeResponse(
        instances=eff_instances,
        fits_in_volume=analysis.fits_in_volume and overflow_count == 0,
        warnings=analysis.warnings,
        message=msg,
    )


def compute_lay_on_face_candidates(
    model_path: Path,
    mesh_id: str,
    scale_percent: float = 100.0,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
) -> LayOnFaceResponse:
    """Extrae facetas planas del casco convexo (`LayOnFace.cpp`) y rotaciones para Z = 0."""
    raw = load_raw_mesh(model_path)
    current = apply_transform_to_mesh(
        raw,
        printer=None,
        scale_percent=scale_percent,
        scale_x=scale_x,
        scale_y=scale_y,
        scale_z=scale_z,
        rot_x=rot_x,
        rot_y=rot_y,
        rot_z=rot_z,
        drop_to_bed=True,
        copy=False,
    )

    ch = current.convex_hull
    trimesh.repair.fix_normals(ch)
    normals = ch.face_normals
    areas = ch.area_faces
    centers = ch.triangles_center

    # Asegurar normales hacia afuera del centroide del casco convexo
    hull_centroid = ch.centroid
    flip_mask = np.sum((centers - hull_centroid) * normals, axis=1) < 0
    if np.any(flip_mask):
        normals = normals.copy()
        normals[flip_mask] *= -1.0

    # Agrupar triángulos coplanares con normal similar y distancia al plano coincidente
    n_faces = len(normals)
    visited = np.zeros(n_faces, dtype=bool)
    clusters: list[tuple[np.ndarray, np.ndarray, float]] = []

    for i in range(n_faces):
        if visited[i]:
            continue
        n_ref = normals[i]
        norm_len = float(np.linalg.norm(n_ref))
        if norm_len < 1e-6:
            visited[i] = True
            continue
        n_unit = n_ref / norm_len
        c_ref = centers[i]

        dots = normals @ n_unit
        plane_dists = np.abs((centers - c_ref) @ n_unit)
        group_mask = (~visited) & (dots > 0.999) & (plane_dists < 0.25)
        visited[group_mask] = True

        g_areas = areas[group_mask]
        tot_area = float(g_areas.sum())
        if tot_area <= 1e-6:
            continue
        g_center = (centers[group_mask] * g_areas[:, None]).sum(axis=0) / tot_area
        clusters.append((n_unit, g_center, tot_area))

    # Descartar caras minúsculas (< 5.0 mm²) salvo que el modelo entero sea miniatura
    major = [cl for cl in clusters if cl[2] >= 5.0]
    if not major:
        major = clusters
    major.sort(key=lambda item: item[2], reverse=True)
    major = major[:16]

    r_cur = trimesh.transformations.euler_matrix(
        math.radians(rot_x), math.radians(rot_y), math.radians(rot_z), axes="sxyz"
    )[:3, :3]
    down = np.array([0.0, 0.0, -1.0])

    candidates: list[LayOnFaceCandidate] = []
    for idx, (n_unit, g_center, tot_area) in enumerate(major):
        dot_down = float(np.clip(np.dot(n_unit, down), -1.0, 1.0))
        if dot_down < -1.0 + 1e-6:
            r_align = _rot_x_mat(180.0)
        elif dot_down > 1.0 - 1e-6:
            r_align = np.eye(3)
        else:
            v = np.cross(n_unit, down)
            s = float(np.linalg.norm(v))
            vx = np.array(
                [
                    [0.0, -v[2], v[1]],
                    [v[2], 0.0, -v[0]],
                    [-v[1], v[0], 0.0],
                ]
            )
            r_align = np.eye(3) + vx + (vx @ vx) * ((1.0 - dot_down) / (s * s))

        r_new = r_align @ r_cur
        m4 = np.eye(4)
        m4[:3, :3] = r_new
        nx_deg, ny_deg, nz_deg = (
            round((math.degrees(a) % 360.0), 1)
            for a in trimesh.transformations.euler_from_matrix(m4, axes="sxyz")
        )

        candidates.append(
            LayOnFaceCandidate(
                face_id=idx,
                normal=[round(float(v), 5) for v in n_unit],
                center=[round(float(v), 3) for v in g_center],
                area_mm2=round(float(tot_area), 2),
                rot_x=nx_deg,
                rot_y=ny_deg,
                rot_z=nz_deg,
            )
        )

    return LayOnFaceResponse(mesh_id=mesh_id, candidates=candidates)


def cut_mesh_by_plane(
    model_path: Path,
    printer: PrinterConfig,
    cut_z_mm: float,
    tilt_x_deg: float = 0.0,
    tilt_y_deg: float = 0.0,
    keep_mode: str = "both",
    scale_percent: float = 100.0,
    scale_x: float | None = None,
    scale_y: float | None = None,
    scale_z: float | None = None,
    rot_x: float = 0.0,
    rot_y: float = 0.0,
    rot_z: float = 0.0,
) -> tuple[str, Path, int, MeshAnalysisResponse]:
    """Secciona el modelo por plano (`slice_mesh_plane` con cap=True) devolviendo sólido cerrado."""
    raw = load_raw_mesh(model_path)
    base_mesh = apply_transform_to_mesh(
        raw,
        printer=None,
        scale_percent=scale_percent,
        scale_x=scale_x,
        scale_y=scale_y,
        scale_z=scale_z,
        rot_x=rot_x,
        rot_y=rot_y,
        rot_z=rot_z,
        drop_to_bed=True,
        copy=False,
    )

    b_min, b_max = base_mesh.bounds
    if cut_z_mm <= float(b_min[2]) + 0.05 or cut_z_mm >= float(b_max[2]) - 0.05:
        if abs(tilt_x_deg) < 1e-2 and abs(tilt_y_deg) < 1e-2:
            raise ValueError(
                f"La altura de corte Z={cut_z_mm:.1f} mm debe quedar entre {b_min[2]:.1f} y {b_max[2]:.1f} mm."
            )

    n_vec = (_rot_y_mat(tilt_y_deg) @ _rot_x_mat(tilt_x_deg)) @ np.array([0.0, 0.0, 1.0])
    n_vec = n_vec / float(np.linalg.norm(n_vec))
    origin = np.array([0.0, 0.0, float(cut_z_mm)])

    upper_mesh: trimesh.Trimesh | None = None
    lower_mesh: trimesh.Trimesh | None = None

    if keep_mode in ("upper", "both"):
        u = trimesh.intersections.slice_mesh_plane(
            base_mesh, plane_normal=n_vec, plane_origin=origin, cap=True
        )
        if u is not None and len(u.faces) > 0:
            upper_mesh = u

    if keep_mode in ("lower", "both"):
        l = trimesh.intersections.slice_mesh_plane(
            base_mesh, plane_normal=-n_vec, plane_origin=origin, cap=True
        )
        if l is not None and len(l.faces) > 0:
            lower_mesh = l

    if keep_mode == "upper":
        if upper_mesh is None:
            raise ValueError("El corte superior resultó vacío en esa posición de plano.")
        final_mesh = apply_transform_to_mesh(upper_mesh, printer=None, drop_to_bed=True)
        parts_count = 1
    elif keep_mode == "lower":
        if lower_mesh is None:
            raise ValueError("El corte inferior resultó vacío en esa posición de plano.")
        final_mesh = apply_transform_to_mesh(lower_mesh, printer=None, drop_to_bed=True)
        parts_count = 1
    else:
        pieces: list[trimesh.Trimesh] = []
        if lower_mesh is not None:
            l_part = apply_transform_to_mesh(lower_mesh, printer=None, drop_to_bed=True)
            pieces.append(l_part)
        if upper_mesh is not None:
            u_part = apply_transform_to_mesh(upper_mesh, printer=None, drop_to_bed=True)
            pieces.append(u_part)
        if not pieces:
            raise ValueError("El plano de corte no intersectó el volumen del modelo.")
        if len(pieces) == 2:
            gap = 8.0
            lw = float(pieces[0].extents[0])
            uw = float(pieces[1].extents[0])
            pieces[0].apply_translation([-(gap * 0.5 + lw * 0.5), 0.0, 0.0])
            pieces[1].apply_translation([(gap * 0.5 + uw * 0.5), 0.0, 0.0])
            final_mesh = trimesh.util.concatenate(pieces)
            parts_count = 2
        else:
            final_mesh = pieces[0]
            parts_count = 1

    new_mesh_id = uuid.uuid4().hex[:12]
    out_path = MESH_CACHE_DIR / f"{new_mesh_id}.stl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final_mesh.export(str(out_path), file_type="stl")

    analysis = analyze_model_file(out_path, printer, mesh_id=new_mesh_id)
    msg = (
        f"Corte completado ({parts_count} parte{'s' if parts_count > 1 else ''} cerrada{'s' if parts_count > 1 else ''}) a Z={cut_z_mm:.1f} mm."
    )
    return new_mesh_id, out_path, parts_count, analysis


def find_optimal_anti_support_orientation(
    model_path: Path,
    printer: PrinterConfig,
    mesh_id: str,
    scale_percent: float = 100.0,
    current_rotation: tuple[float, float, float] = (0.0, 0.0, 0.0),
    layer_height_mm: float = 0.20,
    lithophane_mode: bool = False,
) -> tuple[tuple[float, float, float], float, dict[str, Any], MeshAnalysisResponse]:
    """Busca orientación que minimiza tiempo total, altura Z y volumen real de soportes."""
    is_3mf = model_path.suffix.lower() == ".3mf"
    parts_info: list[MultimaterialPartInfo] = []
    if is_3mf:
        extracted = extract_3mf_parts_and_meshes(model_path)
        parts_info = [p for p, _ in extracted]
        raw_mesh = (
            extracted[0][1]
            if len(extracted) == 1
            else trimesh.util.concatenate([m for _, m in extracted])
        )
    else:
        raw_mesh = load_raw_mesh(model_path)

    raw_mesh_hero = _detect_hero_face_normal(raw_mesh, extracted, is_3mf)
    hero_vec_np = np.array(raw_mesh_hero, dtype=np.float64) if raw_mesh_hero is not None else None
    is_character_like = (
        is_multicolor
        or any(
            tok in model_path.stem.lower()
            for tok in ("robot", "char", "fig", "head", "bust", "mini", "toy", "personaje", "figura", "sheep", "oveja")
        )
    )
    hero_face_detected = bool(hero_vec_np is not None and is_character_like)

    hull = raw_mesh.convex_hull
    hull_verts = hull.vertices.copy()
    to_origin, _ = trimesh.bounds.oriented_bounds(hull)
    r_obb = to_origin[:3, :3]

    # Submuestreo estratificado de caras para evaluar rotaciones en <0.4s (incluso >100MB STL)
    n_faces = len(raw_mesh.faces)
    step = max(1, n_faces // 18000)
    normals_sub = raw_mesh.face_normals[::step].copy()
    areas_sub = raw_mesh.area_faces[::step].copy()
    centers_sub = raw_mesh.triangles_center[::step].copy()
    tot_area = float(areas_sub.sum()) or 1.0
    med_area = float(np.median(areas_sub)) if len(areas_sub) > 0 else 1.0
    fine_detail_mask = areas_sub < (med_area * 0.55)

    cur_rx, cur_ry, cur_rz = current_rotation
    r_current = trimesh.transformations.euler_matrix(
        math.radians(cur_rx),
        math.radians(cur_ry),
        math.radians(cur_rz),
        axes="sxyz",
    )[:3, :3]

    # Candidato #0: orientación actual del usuario + rotaciones cardinales, caras planas del convex_hull, OBB e inclinaciones
    candidates: list[tuple[np.ndarray, bool, bool]] = [
        (r_current, True, False),
        (np.eye(3), False, False),
        (_rot_x_mat(90.0), False, False),
        (_rot_x_mat(-90.0), False, False),
        (_rot_x_mat(180.0), False, False),
        (_rot_y_mat(90.0), False, False),
        (_rot_y_mat(-90.0), False, False),
        (_rot_z_mat(45.0), False, False),
        (_rot_z_mat(90.0), False, False),
    ]

    # Apoyos planos principales del convex_hull (orientar la normal de la cara hacia -Z)
    if len(hull.faces) > 0:
        hull_area_order = np.argsort(hull.area_faces)[::-1][:6]
        down_vec = np.array([0.0, 0.0, -1.0])
        for f_idx in hull_area_order:
            n_vec = hull.face_normals[f_idx]
            rot_4x4 = trimesh.geometry.align_vectors(n_vec, down_vec)
            candidates.append((rot_4x4[:3, :3], False, False))

    obb_rots: list[np.ndarray] = []
    for perm in itertools.permutations([0, 1, 2]):
        for sx, sy, sz in itertools.product([-1.0, 1.0], repeat=3):
            p_mat = np.zeros((3, 3))
            p_mat[0, perm[0]] = sx
            p_mat[1, perm[1]] = sy
            p_mat[2, perm[2]] = sz
            if round(float(np.linalg.det(p_mat))) == 1:
                r_cand = p_mat @ r_obb
                obb_rots.append(r_cand)
                candidates.append((r_cand, False, False))
                candidates.append((_rot_z_mat(45.0) @ r_cand, False, False))

    if not lithophane_mode:
        for r_base in [np.eye(3), _rot_x_mat(90.0), _rot_y_mat(90.0)] + obb_rots[:4]:
            for angle in (20.0, -20.0, 35.0, -35.0, 45.0, -45.0):
                candidates.append((_rot_x_mat(angle) @ r_base, False, True))
                candidates.append((_rot_y_mat(angle) @ r_base, False, True))

    scale_factor = scale_percent / 100.0
    base_hull = hull_verts * scale_factor
    base_centers = centers_sub * scale_factor
    oh_48_cos = math.cos(math.radians(48.0))
    flow_factor = 18.0 / max(float(printer.max_volumetric_flow_mm3_s), 8.0)
    try:
        raw_vol_cm3 = abs(float(raw_mesh.volume)) * (scale_factor ** 3) / 1000.0
    except Exception:
        raw_vol_cm3 = 0.0
    if raw_vol_cm3 <= 0.1:
        b_ext = (hull_verts.max(axis=0) - hull_verts.min(axis=0)) * scale_factor
        raw_vol_cm3 = float(b_ext[0] * b_ext[1] * b_ext[2]) * 0.25 / 1000.0

    evaluated: list[dict[str, Any]] = []
    seen_eulers: set[tuple[float, float, float]] = set()
    current_candidate: dict[str, Any] | None = None

    for r_mat, is_current, is_tilt in candidates:
        m4 = np.eye(4)
        m4[:3, :3] = r_mat
        rx, ry, rz = (
            round((math.degrees(a) % 360.0), 1)
            for a in trimesh.transformations.euler_from_matrix(m4, axes="sxyz")
        )
        if rx == 360.0:
            rx = 0.0
        if ry == 360.0:
            ry = 0.0
        if rz == 360.0:
            rz = 0.0

        euler_key = (rx, ry, rz)
        if not is_current and euler_key in seen_eulers:
            continue
        seen_eulers.add(euler_key)

        rot_hull = base_hull @ r_mat.T
        p_min = rot_hull.min(axis=0)
        p_max = rot_hull.max(axis=0)
        ext = p_max - p_min
        dx, dy, dz = float(ext[0]), float(ext[1]), float(ext[2])

        if printer.kinematics == "delta" and printer.diameter_mm is not None:
            max_rad = printer.diameter_mm / 2.0
            xy_c = (p_min[:2] + p_max[:2]) / 2.0
            rad = float(np.linalg.norm(rot_hull[:, :2] - xy_c, axis=1).max())
            fits = rad <= max_rad and dz <= printer.height_mm
            rec_ratio = min(
                (max_rad * 0.95) / max(rad, 1e-6),
                (printer.height_mm * 0.95) / max(dz, 1e-6),
            )
        elif printer.bed_mm is not None:
            bx, by, bz = printer.bed_mm
            fits = dx <= bx and dy <= by and dz <= bz
            rec_ratio = min(
                (bx * 0.95) / max(dx, 1e-6),
                (by * 0.95) / max(dy, 1e-6),
                (bz * 0.95) / max(dz, 1e-6),
            )
        else:
            fits = True
            rec_ratio = 1.0

        rot_n = normals_sub @ r_mat.T
        rot_cz = base_centers @ r_mat[2, :].T
        z_rel = rot_cz - float(rot_cz.min())

        oh_mask = (rot_n[:, 2] < -oh_48_cos) & (z_rel > 0.35)
        steep_mask = (rot_n[:, 2] < -CRITICAL_OVERHANG_COS) & (rot_n[:, 2] > -0.96) & (z_rel > 0.35)
        oh_ratio = float(areas_sub[oh_mask].sum()) / tot_area
        steep_ratio = float(areas_sub[steep_mask].sum()) / tot_area

        # Volumen real de soporte integrando altura `z_rel` de cada triángulo en voladizo (> 48°)
        support_vol_proxy_cm3 = (
            float((areas_sub[oh_mask] * (scale_factor ** 2) * z_rel[oh_mask]).sum()) * 0.45 / 1000.0
        )
        est_support_grams = round(support_vol_proxy_cm3 * 1.24, 2)

        # Estabilidad de base real sobre el plato
        bed_contact_mask = (z_rel <= 1.2) & (rot_n[:, 2] < -0.5)
        base_contact_area_mm2 = float(areas_sub[bed_contact_mask].sum()) * (scale_factor ** 2) * float(step)
        base_contact_frac = float(np.mean(rot_hull[:, 2] <= float(p_min[2]) + 1.5))
        if base_contact_area_mm2 < 5.0:
            base_contact_area_mm2 = max(1.0, base_contact_frac * dx * dy * 0.25)

        fine_oh_area = float(areas_sub[oh_mask & fine_detail_mask].sum())
        fine_tot_area = float(areas_sub[fine_detail_mask].sum()) or tot_area
        detail_down_ratio = fine_oh_area / fine_tot_area

        layers = dz / max(layer_height_mm, 0.08)
        est_time_min = round(
            (raw_vol_cm3 * 0.85 + layers * 0.16 + support_vol_proxy_cm3 * 2.1) * flow_factor,
            1,
        )

        fit_penalty = 0.0 if fits else 500.0
        unstable_penalty = 45.0 if (base_contact_area_mm2 < 60.0 and dz > 60.0) else 0.0
        detail_penalty = detail_down_ratio * 22.0
        tilt_penalty = 8.0 if (is_tilt and not is_current) else 0.0
        mm_penalty = 18.0 if (is_3mf and len(parts_info) > 1 and is_tilt and not is_current) else 0.0
        base_bonus = min(12.0, base_contact_area_mm2 / 120.0)

        litho_penalty = 0.0
        if lithophane_mode:
            # Litofanías: priorizar postura vertical (Z alto, borde plano de imagen vertical)
            if dz < max(dx, dy) * 0.45:
                litho_penalty += 400.0
            else:
                litho_penalty -= 60.0
            if printer.profile_id == "ender3_s1_pro":
                # Cama móvil en Y: alinear el ancho principal paralelo al eje Y para evitar balanceo
                if dx > dy * 1.25:
                    litho_penalty += 140.0
                elif dy >= dx:
                    litho_penalty -= 80.0

        estimated_time_score = round(
            est_time_min
            + fit_penalty
            + unstable_penalty
            + detail_penalty
            + tilt_penalty
            + mm_penalty
            + litho_penalty
            - base_bonus,
            2,
        )

        entry = {
            "rot_x": rx,
            "rot_y": ry,
            "rot_z": rz,
            "is_current": is_current,
            "is_tilt": is_tilt,
            "fits": fits,
            "rec_ratio": rec_ratio,
            "height_z_mm": round(dz, 1),
            "layers": int(round(layers)),
            "overhang_ratio": round(oh_ratio, 4),
            "steep_overhang_ratio": round(steep_ratio, 4),
            "support_volume_proxy_cm3": round(support_vol_proxy_cm3, 2),
            "estimated_support_grams": est_support_grams,
            "base_contact_area_mm2": round(base_contact_area_mm2, 1),
            "detail_protected_pct": round((1.0 - min(1.0, detail_down_ratio)) * 100.0, 1),
            "estimated_time_min": est_time_min,
            "estimated_time_score": estimated_time_score,
        }
        if is_current:
            current_candidate = entry
        evaluated.append(entry)

    evaluated.sort(key=lambda item: (item["estimated_time_score"], item["height_z_mm"]))
    top_candidates = evaluated[:3]
    if current_candidate is None:
        current_candidate = evaluated[0]

    best_cand = top_candidates[0]
    improves_meaningfully = (
        (not current_candidate["fits"] and best_cand["fits"])
        or (best_cand["estimated_time_score"] < current_candidate["estimated_time_score"] * 0.94)
    )

    if not improves_meaningfully:
        chosen = current_candidate
        apply_rotation = False
    else:
        chosen = best_cand
        apply_rotation = (
            abs(chosen["rot_x"] - current_candidate["rot_x"]) > 0.5
            or abs(chosen["rot_y"] - current_candidate["rot_y"]) > 0.5
            or abs(chosen["rot_z"] - current_candidate["rot_z"]) > 0.5
        )

    best_euler = sanitize_euler_rotation(chosen["rot_x"], chosen["rot_y"], chosen["rot_z"])
    best_rec_scale_pct = max(
        1.0, min(scale_percent, round(scale_percent * float(chosen["rec_ratio"]), 1))
    )
    effective_scale = scale_percent if chosen["fits"] else best_rec_scale_pct

    best_metrics: dict[str, Any] = {
        "overhang_ratio": chosen["overhang_ratio"],
        "steep_overhang_ratio": chosen["steep_overhang_ratio"],
        "detail_protected_pct": chosen["detail_protected_pct"],
        "is_multimaterial": is_3mf and len(parts_info) > 1,
        "fits_at_requested_scale": chosen["fits"],
        "apply_rotation": apply_rotation,
        "estimated_time_min": chosen["estimated_time_min"],
        "estimated_support_grams": chosen["estimated_support_grams"],
        "support_volume_proxy_cm3": chosen["support_volume_proxy_cm3"],
        "current_candidate": current_candidate,
        "top_candidates": top_candidates,
    }

    oriented_mesh = apply_transform_to_mesh(
        raw_mesh,
        printer=printer,
        scale_percent=effective_scale,
        rot_x=best_euler[0],
        rot_y=best_euler[1],
        rot_z=best_euler[2],
        copy=False,
    )
    analysis = analyze_mesh_object(
        oriented_mesh,
        printer,
        mesh_id=mesh_id,
        scale_percent=effective_scale,
        file_format="3mf" if is_3mf else "stl",
        multimaterial_parts=parts_info,
    )
    return best_euler, effective_scale, best_metrics, analysis


def _normalize_deg_signed(deg: float) -> float:
    """Normaliza ángulo a [-180, 180] redondeado a 1 decimal."""
    val = ((deg + 180.0) % 360.0) - 180.0
    val = round(val, 1)
    if abs(val) < 0.05:
        return 0.0
    if val <= -179.95:
        return 180.0
    return val


def _count_xy_contact_zones_and_span(
    touch_xy: np.ndarray,
    cluster_radius: float = 15.0,
) -> tuple[int, float]:
    """Agrupa puntos de contacto en XY (z <= min_z + 0.6 mm) y calcula zonas distintas + separación máxima (mm)."""
    if len(touch_xy) == 0:
        return 0, 0.0
    if len(touch_xy) == 1:
        return 1, 0.0

    # Separación máxima entre puntos de apoyo
    # Usar submuestreo si hay muchos puntos para mantener O(1) ms
    pts = touch_xy[:: max(1, len(touch_xy) // 128)]
    diffs = pts[:, None, :] - pts[None, :, :]
    span_mm = float(np.sqrt((diffs * diffs).sum(axis=2)).max())

    # Clustering greedy por radio en XY
    centers: list[np.ndarray] = []
    r2 = cluster_radius * cluster_radius
    for p in pts:
        matched = False
        for c in centers:
            d = p - c
            if float(d[0] * d[0] + d[1] * d[1]) <= r2:
                matched = True
                break
        if not matched:
            centers.append(p)
    return len(centers), span_mm


def _collect_multipoint_candidate_mats(
    raw_mesh: trimesh.Trimesh,
    hull: trimesh.Trimesh,
    pts: np.ndarray,
) -> list[np.ndarray]:
    """Genera matrices candidatas desde compute_stable_poses, caras 3D del convex hull y aristas 2D en YZ/XZ."""
    mats: list[np.ndarray] = []
    # 1) Poses estables físicas de trimesh
    try:
        stable_mats, _ = trimesh.poses.compute_stable_poses(raw_mesh, n_samples=16)
        for m4 in stable_mats[:10]:
            mats.append(np.asarray(m4[:3, :3], dtype=np.float64))
    except Exception:
        pass

    # 2) Caras más grandes del convex hull 3D alineadas con -Z
    if len(hull.faces) > 0:
        down_vec = np.array([0.0, 0.0, -1.0])
        for f_idx in np.argsort(hull.area_faces)[::-1][:8]:
            rot_4x4 = trimesh.geometry.align_vectors(hull.face_normals[f_idx], down_vec)
            mats.append(np.asarray(rot_4x4[:3, :3], dtype=np.float64))

    # 3) Aristas del Convex Hull 2D en planos YZ (Rx) y XZ (Ry)
    try:
        from scipy.spatial import ConvexHull  # type: ignore[import-not-found]

        if len(pts) >= 6:
            yz_hull = ConvexHull(pts[:, [1, 2]])
            for simplex in yz_hull.simplices:
                v0, v1 = pts[simplex[0], [1, 2]], pts[simplex[1], [1, 2]]
                ang = math.degrees(math.atan2(float(v1[1] - v0[1]), float(v1[0] - v0[0])))
                mats.append(_rot_x_mat(-ang))
                mats.append(_rot_x_mat(180.0 - ang))

            xz_hull = ConvexHull(pts[:, [0, 2]])
            for simplex in xz_hull.simplices:
                v0, v1 = pts[simplex[0], [0, 2]], pts[simplex[1], [0, 2]]
                ang = math.degrees(math.atan2(float(v1[1] - v0[1]), float(v1[0] - v0[0])))
                mats.append(_rot_y_mat(ang))
                mats.append(_rot_y_mat(180.0 + ang))
    except Exception:
        pass

    # 4) Barrido fino de inclinación trasera (-88°..-55°) para apoyo doble cabeza + talones
    for deg_int in range(-88, -54, 2):
        mats.append(_rot_x_mat(float(deg_int)))
    return mats


def _detect_hero_face_normal(
    raw_mesh: trimesh.Trimesh,
    extracted_parts: list[tuple[MultimaterialPartInfo, trimesh.Trimesh]],
    is_3mf: bool,
) -> list[float] | None:
    """Detecta el vector normal de la zona frontal/rostro por concentración de detalle fino y cambios de color .3mf."""
    try:
        areas = np.asarray(raw_mesh.area_faces, dtype=np.float64)
        centers = np.asarray(raw_mesh.triangles_center, dtype=np.float64)
        normals = np.asarray(raw_mesh.face_normals, dtype=np.float64)
        if len(areas) < 50:
            return None

        mesh_center = centers.mean(axis=0)
        q25 = float(np.percentile(areas, 25))
        fine_mask = areas <= max(q25, 1e-6)
        if not np.any(fine_mask):
            return None

        # Ponderar triángulos pequeños y su dirección desde el centroide + normal superficial
        fine_dirs = centers[fine_mask] - mesh_center
        fine_norms = np.linalg.norm(fine_dirs, axis=1, keepdims=True)
        valid = (fine_norms[:, 0] > 1e-3)
        if not np.any(valid):
            return None

        unit_dirs = fine_dirs[valid] / fine_norms[valid]
        w = 1.0 / (areas[fine_mask][valid] + 1e-4)
        # Refuerzo con normales orientadas hacia afuera
        dir_vec = ((unit_dirs * 0.65 + normals[fine_mask][valid] * 0.35) * w[:, None]).sum(axis=0)

        # Si es .3mf con múltiples partes (ej. ojos, boca, emblemas pequeños), reforzar hacia esas partes
        if is_3mf and len(extracted_parts) > 1:
            total_area = float(areas.sum()) or 1.0
            for _, p_mesh in extracted_parts:
                p_area = float(np.asarray(p_mesh.area_faces).sum())
                if 0.0005 * total_area <= p_area <= 0.22 * total_area:
                    p_center = np.asarray(p_mesh.triangles_center).mean(axis=0)
                    p_dir = p_center - mesh_center
                    p_norm = float(np.linalg.norm(p_dir))
                    if p_norm > 1e-3:
                        dir_vec += (p_dir / p_norm) * (float(w.sum()) * 0.35)

        vec_norm = float(np.linalg.norm(dir_vec))
        if vec_norm < 1e-6:
            return None
        hero = dir_vec / vec_norm
        return [round(float(hero[0]), 4), round(float(hero[1]), 4), round(float(hero[2]), 4)]
    except Exception:
        return None


def evaluate_orientation_candidates(
    model_path: Path,
    printer: PrinterConfig,
    mesh_id: str,
    scale_percent: float = 100.0,
) -> dict[str, Any]:
    """Evalúa 5 orientaciones clave sobre la malla STL/3MF para previsualización en vivo."""
    is_3mf = model_path.suffix.lower() == ".3mf"
    parts_info: list[MultimaterialPartInfo] = []
    extracted: list[tuple[MultimaterialPartInfo, trimesh.Trimesh]] = []
    is_multicolor = False
    multicolor_parts_count = 1
    if is_3mf:
        mc_info = inspect_3mf_multicolor_info(model_path)
        extracted = extract_3mf_parts_and_meshes(model_path)
        parts_info = [p for p, _ in extracted]
        multicolor_parts_count = max(len(parts_info), int(mc_info.get("parts_count") or 1))
        is_multicolor = (
            len(parts_info) > 1
            or bool(mc_info.get("has_paint_colors"))
            or bool(mc_info.get("is_multicolor"))
        )
        raw_mesh = (
            extracted[0][1]
            if len(extracted) == 1
            else trimesh.util.concatenate([m for _, m in extracted])
        )
    else:
        raw_mesh = load_raw_mesh(model_path)

    raw_mesh_hero = _detect_hero_face_normal(raw_mesh, extracted, is_3mf)
    hero_vec_np = np.array(raw_mesh_hero, dtype=np.float64) if raw_mesh_hero is not None else None
    is_character_like = (
        is_multicolor
        or any(
            tok in model_path.stem.lower()
            for tok in ("robot", "char", "fig", "head", "bust", "mini", "toy", "personaje", "figura", "sheep", "oveja")
        )
    )
    hero_face_detected = bool(hero_vec_np is not None and is_character_like)

    hull = raw_mesh.convex_hull
    hull_verts = hull.vertices.copy()
    to_origin, _ = trimesh.bounds.oriented_bounds(hull)
    r_obb = to_origin[:3, :3]

    n_faces = len(raw_mesh.faces)
    step = max(1, n_faces // 18000)
    normals_sub = raw_mesh.face_normals[::step].copy()
    areas_sub = raw_mesh.area_faces[::step].copy()
    centers_sub = raw_mesh.triangles_center[::step].copy()
    tot_area = float(areas_sub.sum()) or 1.0

    scale_factor = max(0.05, scale_percent / 100.0)
    base_hull = hull_verts * scale_factor
    base_centers = centers_sub * scale_factor
    oh_45_cos = math.cos(math.radians(45.0))

    try:
        raw_vol_cm3 = abs(float(raw_mesh.volume)) * (scale_factor ** 3) / 1000.0
    except Exception:
        raw_vol_cm3 = 0.0
    if raw_vol_cm3 <= 0.1:
        b_ext = (hull_verts.max(axis=0) - hull_verts.min(axis=0)) * scale_factor
        raw_vol_cm3 = float(b_ext[0] * b_ext[1] * b_ext[2]) * 0.25 / 1000.0

    def _eval_r_mat(r_mat: np.ndarray, explicit_euler: tuple[float, float, float] | None = None) -> dict[str, Any]:
        m4 = np.eye(4)
        m4[:3, :3] = r_mat
        # trimesh quaternion_from_matrix devuelve [w, x, y, z] -> convertir a [qx, qy, qz, qw]
        q_wxyz = trimesh.transformations.quaternion_from_matrix(m4)
        quat_xyzw = [
            round(float(q_wxyz[1]), 6),
            round(float(q_wxyz[2]), 6),
            round(float(q_wxyz[3]), 6),
            round(float(q_wxyz[0]), 6),
        ]
        if explicit_euler is not None:
            rx, ry, rz = (_normalize_deg_signed(a) for a in explicit_euler)
        else:
            rx, ry, rz = (
                _normalize_deg_signed(math.degrees(a))
                for a in trimesh.transformations.euler_from_matrix(m4, axes="sxyz")
            )
            # Evitar descomposición redundante 180° / ry / 180° -> simplificar a rotación limpia
            if abs(abs(rx) - 180.0) < 1.0 and abs(abs(rz) - 180.0) < 1.0:
                rx = 0.0
                ry = _normalize_deg_signed(180.0 - ry)
                rz = 0.0

        rot_hull = base_hull @ r_mat.T
        p_min = rot_hull.min(axis=0)
        p_max = rot_hull.max(axis=0)
        ext = p_max - p_min
        dx, dy, dz = float(ext[0]), float(ext[1]), float(ext[2])

        if printer.kinematics == "delta" and printer.diameter_mm is not None:
            max_rad = printer.diameter_mm / 2.0
            xy_c = (p_min[:2] + p_max[:2]) / 2.0
            rad = float(np.linalg.norm(rot_hull[:, :2] - xy_c, axis=1).max())
            fits = rad <= max_rad and dz <= printer.height_mm
        elif printer.bed_mm is not None:
            bx, by, bz = printer.bed_mm
            fits = dx <= bx and dy <= by and dz <= bz
        else:
            fits = True

        rot_n = normals_sub @ r_mat.T
        rot_cz = base_centers @ r_mat[2, :].T
        z_rel = rot_cz - float(rot_cz.min())
        z_bed_rel = rot_cz - float(p_min[2])

        oh_mask = (rot_n[:, 2] < -oh_45_cos) & (z_rel > 0.35)
        oh_ratio = float(areas_sub[oh_mask].sum()) / tot_area

        # Área acumulada de todas las caras coplanares apoyadas en la cama (z <= min_z + 0.4 mm)
        bed_contact_mask = (z_bed_rel <= 0.4) & (rot_n[:, 2] < -0.5)
        base_contact_area_mm2 = float(areas_sub[bed_contact_mask].sum()) * (scale_factor ** 2) * float(step)
        if base_contact_area_mm2 < 1.0:
            bed_pts = rot_hull[rot_hull[:, 2] <= float(p_min[2]) + 0.4]
            if len(bed_pts) >= 3:
                b_ext_2d = bed_pts[:, :2].max(axis=0) - bed_pts[:, :2].min(axis=0)
                base_contact_area_mm2 = max(1.0, float(b_ext_2d[0] * b_ext_2d[1]) * 0.5)
            else:
                base_contact_area_mm2 = 1.0

        stability_warning: str | None = None
        if base_contact_area_mm2 < 120.0:
            stability_warning = "Base muy pequeña · Requiere Brim/Balsa y Soportes"

        purge_weight = 0.55 if is_multicolor else 0.0
        hero_elev_deg: float | None = None
        hero_penalty = 1.0
        if hero_face_detected and hero_vec_np is not None:
            rot_hero = r_mat @ hero_vec_np
            hero_elev_deg = round(
                math.degrees(math.asin(max(-1.0, min(1.0, float(rot_hero[2]))))),
                1,
            )
            if hero_elev_deg < -8.0:
                # Prohibido: cara mirando hacia abajo (-Z) -> soportes sobre el rostro
                hero_penalty = 9.0
            elif hero_elev_deg > 65.0:
                # Cara casi paralela a la cama (<25° respecto a XY) -> efecto escalera en frente/ojos
                hero_penalty = 1.55
            elif 15.0 <= hero_elev_deg <= 60.0:
                # Ángulo óptimo de personaje (reclinado 20-45° / elevación frontal 45-75°)
                hero_penalty = 0.72

        # Zonas de contacto y separación máxima (span_mm) en z <= min_z + 0.6 mm
        touch_xy = rot_hull[rot_hull[:, 2] <= float(p_min[2]) + 0.6][:, :2]
        contact_zones_count, contact_span_mm = _count_xy_contact_zones_and_span(touch_xy)

        est_time_proxy = (
            dz * (1.0 + oh_ratio * 0.45 + purge_weight)
            + raw_vol_cm3 * 0.55
        )
        return {
            "rx": rx,
            "ry": ry,
            "rz": rz,
            "quaternion": quat_xyzw,
            "dx": round(dx, 1),
            "dy": round(dy, 1),
            "dz": round(dz, 1),
            "fits_bed": bool(fits),
            "overhang_ratio_pct": round(oh_ratio * 100.0, 1),
            "contact_area_mm2": round(base_contact_area_mm2, 1),
            "contact_zones_count": int(contact_zones_count),
            "contact_span_mm": round(contact_span_mm, 1),
            "stability_warning": stability_warning,
            "est_time_proxy": est_time_proxy,
            "hero_face_elevation_deg": hero_elev_deg,
            "hero_face_penalty": hero_penalty,
        }

    orig_eval = _eval_r_mat(np.eye(3), (0.0, 0.0, 0.0))
    back_eval = _eval_r_mat(_rot_x_mat(-90.0), (-90.0, 0.0, 0.0))
    tilt_eval = _eval_r_mat(_rot_x_mat(-45.0), (-45.0, 0.0, 0.0))

    # De Lado / Perfil (Cara Limpia): evalúa Ry = -90° y Ry = +90° y elige el que mejor protege el rostro
    side_neg = _eval_r_mat(_rot_y_mat(-90.0), (0.0, -90.0, 0.0))
    side_pos = _eval_r_mat(_rot_y_mat(90.0), (0.0, 90.0, 0.0))
    side_eval = min(
        [side_neg, side_pos],
        key=lambda e: (
            0 if e["fits_bed"] else 1,
            float(e.get("hero_face_penalty", 1.0)),
            e["overhang_ratio_pct"],
            e["dz"],
        ),
    )

    # Apoyo Multi-Punto en Cama (multi_point_bed_contact) desde compute_stable_poses + Convex Hull 3D/2D (YZ/XZ)
    mp_mats = _collect_multipoint_candidate_mats(raw_mesh, hull, base_hull)
    mp_evals: list[dict[str, Any]] = []
    seen_keys: set[tuple[float, float, float]] = set()
    used_keys = {
        (orig_eval["rx"], orig_eval["ry"], orig_eval["rz"]),
        (back_eval["rx"], back_eval["ry"], back_eval["rz"]),
        (tilt_eval["rx"], tilt_eval["ry"], tilt_eval["rz"]),
        (side_eval["rx"], side_eval["ry"], side_eval["rz"]),
    }
    for r_m in mp_mats:
        ev = _eval_r_mat(r_m)
        if abs(ev["rx"]) < 5.0 and abs(ev["ry"]) < 5.0:
            continue
        if hero_face_detected and ev.get("hero_face_elevation_deg") is not None and float(ev["hero_face_elevation_deg"]) < -8.0:
            continue
        key = (ev["rx"], ev["ry"], ev["rz"])
        if key in seen_keys or key in used_keys:
            continue
        seen_keys.add(key)
        mp_evals.append(ev)

    fitting_mp = [e for e in mp_evals if e["fits_bed"]] or mp_evals or [back_eval]
    multi_eval = max(
        fitting_mp,
        key=lambda e: (
            1 if int(e.get("contact_zones_count", 1)) >= 2 else 0,
            1 if float(e.get("contact_span_mm", 0.0)) >= 40.0 else 0,
            1 if ((abs(e["ry"]) < 1.0 and abs(e["rz"]) < 1.0) or (abs(e["rx"]) < 1.0 and abs(e["rz"]) < 1.0)) else 0,
            min(4, int(e.get("contact_zones_count", 1))),
            -float(e.get("hero_face_penalty", 1.0)),
            -float(e["overhang_ratio_pct"]),
            -float(e["dz"]),
            float(e.get("contact_span_mm", 0.0)),
        ),
    )

    orig_time = max(orig_eval["est_time_proxy"], 1e-6)
    orig_dz = max(orig_eval["dz"], 1.0)

    def _time_delta_label(ev: dict[str, Any], is_orig: bool = False) -> str:
        if is_orig:
            return "Base de referencia"
        pct = round(((ev["est_time_proxy"] - orig_time) / orig_time) * 100)
        suffix = " · menos purgas Z" if is_multicolor and ev["dz"] < orig_dz * 0.85 else ""
        return f"{pct:+d}% tiempo{suffix}"

    def _dynamic_badge(oid: str, ev: dict[str, Any]) -> str:
        oh = float(ev["overhang_ratio_pct"])
        warn = ev.get("stability_warning")
        if oh <= 2.0 and not warn and float(ev["contact_area_mm2"]) >= 20.0:
            return "Sin Soportes"
        if oid == "original":
            return "Original"
        if oid == "double_support":
            z_cnt = int(ev.get("contact_zones_count", 1))
            span = float(ev.get("contact_span_mm", 0.0))
            return f"{z_cnt} zonas · {span:.0f} mm"
        if oid == "side_profile":
            return "Rostro de perfil · Sin escalones"
        if oid == "back_down":
            return "Espalda apoyada · Frente libre"
        if oid == "tilted_45":
            return "Talón en cama · Menos voladizo"
        return "Requiere Soportes"

    is_vertical_figure = (
        orig_eval["dz"] > max(orig_eval["dx"], orig_eval["dy"]) * 1.25
        and orig_eval["dz"] > 80.0
    )

    mp_zones = int(multi_eval.get("contact_zones_count", 1))
    mp_span = float(multi_eval.get("contact_span_mm", 0.0))
    mp_title = (
        "Apoyo Doble en Cama (Cabeza + Base)"
        if mp_zones >= 2 and mp_span >= 40.0
        else "Apoyo Multi-Punto Optimizado"
    )
    mp_oh_delta = round(float(multi_eval["overhang_ratio_pct"]) - float(orig_eval["overhang_ratio_pct"]), 1)

    raw_options = [
        {
            "id": "original",
            "title": "Posición Original",
            "badge": _dynamic_badge("original", orig_eval),
            "ev": orig_eval,
            "is_orig": True,
            "explanation": (
                f"Orientación de archivo asentada en Z=0 ({orig_eval['dz']} mm en Z, {orig_eval['overhang_ratio_pct']}% voladizos)."
            ),
        },
        {
            "id": "double_support",
            "title": mp_title,
            "badge": _dynamic_badge("double_support", multi_eval),
            "ev": multi_eval,
            "is_orig": False,
            "explanation": (
                f"{mp_zones} zonas de apoyo simultáneo en Z=0 (separación {mp_span:.0f} mm); "
                f"voladizos {multi_eval['overhang_ratio_pct']}% ({mp_oh_delta:+.1f}%), {_time_delta_label(multi_eval)}."
            ),
        },
        {
            "id": "side_profile",
            "title": "De Lado / Perfil (Cara Limpia)",
            "badge": _dynamic_badge("side_profile", side_eval),
            "ev": side_eval,
            "is_orig": False,
            "explanation": (
                f"Acuesta sobre costado (Ry={side_eval['ry']}°) a Z=0: reduce Z a {side_eval['dz']} mm evitando escalones en el rostro."
            ),
        },
        {
            "id": "back_down",
            "title": "Espalda Plana en Cama / Frente Libre",
            "badge": _dynamic_badge("back_down", back_eval),
            "ev": back_eval,
            "is_orig": False,
            "explanation": (
                f"Apoya la espalda en Z=0 ({orig_eval['dz']}→{back_eval['dz']} mm en Z), dejando rostro y pecho libres de soportes."
            ),
        },
        {
            "id": "tilted_45",
            "title": "Inclinado 45° Atrás (Talón en Cama)",
            "badge": _dynamic_badge("tilted_45", tilt_eval),
            "ev": tilt_eval,
            "is_orig": False,
            "explanation": (
                f"Inclina 45° hacia atrás apoyando talón en Z=0 ({tilt_eval['overhang_ratio_pct']}% voladizos); los soportes caen en la espalda."
            ),
        },
    ]

    def _rank_score(o: dict[str, Any]) -> tuple[int, int, float]:
        ev = o["ev"]
        fits_pen = 0 if ev["fits_bed"] else 1
        stab_pen = 1 if ev.get("stability_warning") else 0
        base_score = (
            ev["est_time_proxy"]
            * (1.0 + ev["overhang_ratio_pct"] / 120.0)
            * float(ev.get("hero_face_penalty", 1.0))
        )
        if is_vertical_figure and o["id"] == "back_down" and fits_pen == 0 and stab_pen == 0:
            base_score *= 0.85
        return (fits_pen, stab_pen, base_score)

    best_opt = min(raw_options, key=_rank_score)
    recommended_id = best_opt["id"]

    # Ordenar colocando primero la recomendada, luego viables y al final opciones con stability_warning
    raw_options_sorted = sorted(
        raw_options,
        key=lambda o: (
            0 if o["id"] == recommended_id else 1,
            _rank_score(o),
        ),
    )

    options_out: list[dict[str, Any]] = []
    for item in raw_options_sorted:
        ev = item["ev"]
        options_out.append(
            {
                "id": item["id"],
                "title": item["title"],
                "badge": item["badge"],
                "rotation": {"rx": ev["rx"], "ry": ev["ry"], "rz": ev["rz"]},
                "quaternion": ev.get("quaternion"),
                "z_height_mm": ev["dz"],
                "overhang_ratio_pct": ev["overhang_ratio_pct"],
                "contact_area_mm2": ev["contact_area_mm2"],
                "estimated_time_delta_pct": _time_delta_label(ev, item["is_orig"]),
                "explanation": item["explanation"],
                "stability_warning": ev.get("stability_warning"),
                "fits_bed": ev["fits_bed"],
                "hero_face_elevation_deg": ev.get("hero_face_elevation_deg"),
                "is_recommended": item["id"] == recommended_id,
            }
        )

    return {
        "mesh_id": mesh_id,
        "model_name": model_path.stem,
        "is_multicolor": is_multicolor,
        "multicolor_parts_count": multicolor_parts_count,
        "hero_face_detected": hero_face_detected,
        "hero_face_normal": raw_mesh_hero if hero_face_detected else None,
        "recommended_id": recommended_id,
        "options": options_out,
    }


def _scene_objects_dir(mesh_id: str) -> Path:
    clean_id = "".join(ch for ch in mesh_id if ch.isalnum() or ch in ("-", "_"))
    return MESH_CACHE_DIR / f"{clean_id}_objs"


def get_scene_object_stl_path(mesh_id: str, object_id: str) -> Path | None:
    clean_obj = "".join(ch for ch in object_id if ch.isalnum() or ch in ("-", "_"))
    if not clean_obj:
        return None
    cand = _scene_objects_dir(mesh_id) / f"{clean_obj}.stl"
    return cand if cand.is_file() else None


def _export_scene_objects_to_cache(
    mesh_id: str,
    parts_with_meshes: list[tuple[MultimaterialPartInfo, trimesh.Trimesh]],
) -> list[SceneObjectInfo]:
    """Exporta cada objeto de un `.3mf` como `.stl` independiente centrado localmente."""
    obj_dir = _scene_objects_dir(mesh_id)
    obj_dir.mkdir(parents=True, exist_ok=True)

    all_bounds = [m.bounds for _, m in parts_with_meshes if len(m.vertices) > 0]
    if all_bounds:
        g_min = np.min([b[0] for b in all_bounds], axis=0)
        g_max = np.max([b[1] for b in all_bounds], axis=0)
        global_cx = float((g_min[0] + g_max[0]) / 2.0)
        global_cy = float((g_min[1] + g_max[1]) / 2.0)
        global_zmin = float(g_min[2])
    else:
        global_cx = global_cy = global_zmin = 0.0

    out: list[SceneObjectInfo] = []
    for idx, (p_info, p_mesh) in enumerate(parts_with_meshes):
        if len(p_mesh.vertices) == 0:
            continue
        obj_id = "".join(ch for ch in (p_info.part_id or f"obj_{idx + 1}") if ch.isalnum() or ch in ("-", "_"))
        if not obj_id:
            obj_id = f"obj_{idx + 1}"
        b = p_mesh.bounds
        lcx = float((b[0][0] + b[1][0]) / 2.0)
        lcy = float((b[0][1] + b[1][1]) / 2.0)
        lz0 = float(b[0][2])

        local_mesh = p_mesh.copy()
        local_mesh.apply_translation([-lcx, -lcy, -lz0])

        stl_path = obj_dir / f"{obj_id}.stl"
        exported = local_mesh.export(file_type="stl")
        stl_bytes = exported if isinstance(exported, (bytes, bytearray)) else str(exported).encode("utf-8")
        stl_path.write_bytes(bytes(stl_bytes))

        ext = local_mesh.extents
        out.append(
            SceneObjectInfo(
                object_id=obj_id,
                name=p_info.name or f"Pieza {idx + 1}",
                extruder=max(1, min(4, int(p_info.extruder))),
                color_hex=p_info.color_hex,
                mesh_url=f"/api/models/{mesh_id}/objects/{obj_id}.stl",
                position=[
                    round(lcx - global_cx, 2),
                    round(lcy - global_cy, 2),
                    round(max(0.0, lz0 - global_zmin), 2),
                ],
                rotation=[0.0, 0.0, 0.0],
                scale=[100.0, 100.0, 100.0],
                dimensions_mm=[round(float(ext[0]), 2), round(float(ext[1]), 2), round(float(ext[2]), 2)],
            )
        )
    return out


def split_mesh_into_scene_objects(
    model_path: Path,
    mesh_id: str,
) -> list[SceneObjectInfo]:
    """Divide una malla `.stl` o `.3mf` en componentes geométricos desconectados (`split`)."""
    is_3mf = model_path.suffix.lower() == ".3mf"
    if is_3mf:
        extracted = extract_3mf_parts_and_meshes(model_path)
        if len(extracted) > 1:
            return _export_scene_objects_to_cache(mesh_id, extracted)
        raw = extracted[0][1]
    else:
        raw = load_raw_mesh(model_path)

    shells = [m for m in raw.split(only_watertight=False) if len(m.faces) >= 10]
    if not shells:
        shells = [raw]
    shells.sort(key=lambda m: float(np.prod(m.extents)), reverse=True)

    parts_list: list[tuple[MultimaterialPartInfo, trimesh.Trimesh]] = []
    for idx, sh in enumerate(shells[:32]):
        parts_list.append(
            (
                MultimaterialPartInfo(
                    part_id=f"split_{idx + 1}",
                    name=f"Pieza {idx + 1}",
                    extruder=1,
                    triangle_count=int(len(sh.faces)),
                ),
                sh,
            )
        )
    return _export_scene_objects_to_cache(mesh_id, parts_list)


def assemble_scene_objects_for_slicer(
    mesh_id: str,
    scene_objects: list[SceneObjectTransform],
    job_dir: Path,
    printer: PrinterConfig,
    part_extruder_map: dict[str, int] | None = None,
) -> Path:
    """Reconstruye un `.3mf` multi-objeto con las transformaciones y filamentos individuales de cada pieza."""
    bed_cx, bed_cy = _bed_center_xy(printer)
    override_map = part_extruder_map or {}
    xml_objects: list[str] = []
    xml_items: list[str] = []

    for idx, obj in enumerate(scene_objects, start=1):
        stl_path = get_scene_object_stl_path(mesh_id, obj.object_id)
        if stl_path is None:
            continue
        mesh = load_raw_mesh(stl_path)
        transformed = apply_transform_to_mesh(
            mesh,
            printer=None,
            scale_percent=obj.scale_percent,
            rot_x=obj.rot_x,
            rot_y=obj.rot_y,
            rot_z=obj.rot_z,
            scale_x=obj.scale_x,
            scale_y=obj.scale_y,
            scale_z=obj.scale_z,
            offset_x=bed_cx + obj.offset_x,
            offset_y=bed_cy + obj.offset_y,
            offset_z=obj.offset_z,
            drop_to_bed=obj.drop_to_bed,
            copy=False,
        )
        ext_num = max(1, min(4, int(override_map.get(obj.object_id, obj.extruder - 1) + 1 if obj.object_id in override_map else obj.extruder)))
        verts = transformed.vertices
        faces = transformed.faces
        v_lines = "\n".join(f'          <vertex x="{v[0]:.4f}" y="{v[1]:.4f}" z="{v[2]:.4f}" />' for v in verts)
        t_lines = "\n".join(f'          <triangle v1="{f[0]}" v2="{f[1]}" v3="{f[2]}" />' for f in faces)
        xml_objects.append(
            f'    <object id="{idx}" type="model" name="{obj.name}" p:extruder="{ext_num}">\n'
            f'      <mesh>\n'
            f'        <vertices>\n{v_lines}\n        </vertices>\n'
            f'        <triangles>\n{t_lines}\n        </triangles>\n'
            f'      </mesh>\n'
            f'    </object>'
        )
        xml_items.append(f'    <item objectid="{idx}" printable="1" />')

    if not xml_objects:
        raise ValueError("No hay objetos activos válidos para ensamblar el .3mf.")

    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" '
        'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06">\n'
        '  <resources>\n'
        + "\n".join(xml_objects)
        + "\n  </resources>\n  <build>\n"
        + "\n".join(xml_items)
        + "\n  </build>\n</model>\n"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
        '  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml" />\n'
        '  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml" />\n'
        '</Types>\n'
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        '  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2015/02/3dmodel" />\n'
        '</Relationships>\n'
    )

    out_3mf = job_dir / "scene_objects_assembled.3mf"
    with zipfile.ZipFile(out_3mf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("3D/3dmodel.model", model_xml)
    return out_3mf
