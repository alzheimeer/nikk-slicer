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
    DimensionsMM,
    LayOnFaceCandidate,
    LayOnFaceResponse,
    MeshAnalysisResponse,
    ModelInstanceTransform,
    MultimaterialPartInfo,
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
    """Decodifica el atributo `paint_color` (árbol nibbles Orca/Bambu) a extrusor 1..4."""
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
    counts = [0, 0, 0, 0, 0]  # índice 0 = sin pintar, 1..4 = T0..T3
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
            slot = max(0, min(4, state))
            counts[slot] += 1
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

    best_ext = max(range(1, 5), key=lambda e: counts[e])
    return best_ext if counts[best_ext] > 0 else 1


def inspect_3mf_multicolor_info(threemf_path: Path) -> dict[str, object]:
    """Inspecciona pintado por triángulo (`paint_color` o `pid`/`p1`) y paleta embebida en `.3mf`."""
    counts = [0, 0, 0, 0]  # T0..T3
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
                                    counts[ext - 1] += 1
                                elif "pid" in tri.attrib and "p1" in tri.attrib:
                                    has_tri_pid_attr = True
                                    try:
                                        p1_idx = int(tri.attrib["p1"])
                                    except ValueError:
                                        p1_idx = 0
                                    tri_pids_seen.add(p1_idx)
                                    counts[p1_idx % 4] += 1
                                else:
                                    counts[0] += 1
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
                project_palette = first_group[:4]

    active_slots = sum(1 for c in counts if c > 0)
    percentages: dict[str, float] = {}
    if total_paint_tris > 0 and (has_paint_color_attr or (has_tri_pid_attr and active_slots > 1)):
        for i, c in enumerate(counts):
            if c > 0:
                percentages[f"T{i}"] = round((c / total_paint_tris) * 100.0, 1)

    return {
        "has_triangle_painting": bool(
            total_paint_tris > 0 and (has_paint_color_attr or (has_tri_pid_attr and active_slots > 1))
        ),
        "active_painted_extruders": active_slots,
        "extruder_triangle_percentages": percentages,
        "detected_filament_colors": project_palette[:4],
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
) -> Path:
    """Reempaqueta un `.3mf` pintado por triángulo transformado al plato, preservando `paint_color`."""
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
                            pc = _PAINT_DIRECT_CODE.get(ext, "4")
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
        warnings=warnings,
    )


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
