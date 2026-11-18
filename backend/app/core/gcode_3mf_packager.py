"""Empaquetador `.gcode.3mf` con renderizado 3D software (sin OpenGL) para FlashForge Creator 5 Pro."""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import xml.sax.saxutils as saxutils
import zipfile
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import trimesh


def _encode_rgba_png(rgba: np.ndarray) -> bytes:
    """Codifica un array `(H, W, 4)` uint8 a PNG RGBA válido usando zlib estándar."""
    height, width, _ = rgba.shape
    raw_rows = b"".join(b"\x00" + rgba[y].tobytes() for y in range(height))
    compressed = zlib.compress(raw_rows, level=6)

    def _chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack("!IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", compressed)
        + _chunk(b"IEND", b"")
    )


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    hx = hex_str.strip().lstrip("#")
    if len(hx) == 6:
        try:
            return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        except ValueError:
            pass
    return 56, 189, 248


def render_mesh_thumbnail_png(
    mesh_path: Path,
    *,
    width: int = 512,
    height: int = 512,
    base_color_hex: str = "#38BDF8",
) -> bytes:
    """Renderiza una miniatura 3D isométrica sólida del modelo STL/3MF usando NumPy (sin OpenGL)."""
    canvas = np.zeros((height, width, 4), dtype=np.uint8)
    canvas[:, :] = (15, 23, 42, 255)

    try:
        loaded = trimesh.load(str(mesh_path), force="mesh")
        if isinstance(loaded, trimesh.Scene):
            geoms = [
                g for g in loaded.geometry.values() if isinstance(g, trimesh.Trimesh) and len(g.faces) > 0
            ]
            mesh = trimesh.util.concatenate(geoms) if geoms else None
        elif isinstance(loaded, trimesh.Trimesh):
            mesh = loaded
        else:
            mesh = None
    except Exception:
        mesh = None

    if mesh is None or len(mesh.faces) == 0:
        return _encode_rgba_png(canvas)

    verts = np.asarray(mesh.vertices, dtype=np.float32)
    faces = np.asarray(mesh.faces, dtype=np.int32)

    # Centrar en origen y normalizar escala
    center = (verts.min(axis=0) + verts.max(axis=0)) * 0.5
    v_centered = verts - center
    max_extent = float(np.max(verts.max(axis=0) - verts.min(axis=0))) or 1.0
    v_norm = v_centered / max_extent

    # Rotación isométrica (vista frontal 3/4 superior, modelo derecho)
    az = np.radians(35.0)
    el = np.radians(-62.0)
    rz = np.array(
        [[np.cos(az), -np.sin(az), 0.0], [np.sin(az), np.cos(az), 0.0], [0.0, 0.0, 1.0]],
        dtype=np.float32,
    )
    rx = np.array(
        [[1.0, 0.0, 0.0], [0.0, np.cos(el), -np.sin(el)], [0.0, np.sin(el), np.cos(el)]],
        dtype=np.float32,
    )
    rot = rx @ rz
    v_rot = v_norm @ rot.T

    scale_px = min(width, height) * 0.68
    px_x = v_rot[:, 0] * scale_px + width * 0.5
    px_y = -v_rot[:, 1] * scale_px + height * 0.52
    pz = v_rot[:, 2]

    br, bg, bb = _hex_to_rgb(base_color_hex)

    # Normales de vértice/cara para sombreado 3D sólido
    v0 = v_rot[faces[:, 0]]
    v1 = v_rot[faces[:, 1]]
    v2 = v_rot[faces[:, 2]]
    face_normals = np.cross(v1 - v0, v2 - v0)
    fn_len = np.linalg.norm(face_normals, axis=1, keepdims=True)
    face_normals = face_normals / np.maximum(fn_len, 1e-6)

    light_dir = np.array([0.42, 0.65, 0.63], dtype=np.float32)
    light_dir /= np.linalg.norm(light_dir)
    face_lit = np.clip(np.abs(face_normals @ light_dir) * 0.72 + 0.28, 0.24, 1.0)

    if len(faces) <= 8000:
        # Rasterización exacta por triángulo para mallas ligeras
        face_z = (pz[faces[:, 0]] + pz[faces[:, 1]] + pz[faces[:, 2]]) / 3.0
        order = np.argsort(face_z)
        for fi in order:
            i0, i1, i2 = faces[fi]
            x0, y0 = px_x[i0], px_y[i0]
            x1, y1 = px_x[i1], px_y[i1]
            x2, y2 = px_x[i2], px_y[i2]
            min_x = max(0, int(np.floor(min(x0, x1, x2))))
            max_x = min(width - 1, int(np.ceil(max(x0, x1, x2))))
            min_y = max(0, int(np.floor(min(y0, y1, y2))))
            max_y = min(height - 1, int(np.ceil(max(y0, y1, y2))))
            if min_x > max_x or min_y > max_y:
                continue
            area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
            if abs(area) < 0.2:
                continue
            xs = np.arange(min_x, max_x + 1, dtype=np.float32)[None, :] + 0.5
            ys = np.arange(min_y, max_y + 1, dtype=np.float32)[:, None] + 0.5
            w0 = (x1 - xs) * (y2 - ys) - (y1 - ys) * (x2 - xs)
            w1 = (x2 - xs) * (y0 - ys) - (y2 - ys) * (x0 - xs)
            w2 = (x0 - xs) * (y1 - ys) - (y0 - ys) * (x1 - xs)
            inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0) if area > 0 else (w0 <= 0) & (w1 <= 0) & (w2 <= 0)
            if not np.any(inside):
                continue
            lit = float(face_lit[fi])
            sub = canvas[min_y : max_y + 1, min_x : max_x + 1]
            sub[inside] = (min(255, int(br * lit)), min(255, int(bg * lit)), min(255, int(bb * lit)), 255)
    else:
        # Para mallas densas (>8k caras), usar centroides + vértices ordenados por Z con splat 3x3 sólido
        # sin saltarse la superficie ni dejar huecos
        cx = (px_x[faces[:, 0]] + px_x[faces[:, 1]] + px_x[faces[:, 2]]) / 3.0
        cy = (px_y[faces[:, 0]] + px_y[faces[:, 1]] + px_y[faces[:, 2]]) / 3.0
        cz = (pz[faces[:, 0]] + pz[faces[:, 1]] + pz[faces[:, 2]]) / 3.0

        ix = np.clip(np.round(cx).astype(np.int32), 1, width - 2)
        iy = np.clip(np.round(cy).astype(np.int32), 1, height - 2)
        order = np.argsort(cz)

        ix_o = ix[order]
        iy_o = iy[order]
        lit_o = face_lit[order]

        r_arr = np.clip((br * lit_o).astype(np.int32), 0, 255).astype(np.uint8)
        g_arr = np.clip((bg * lit_o).astype(np.int32), 0, 255).astype(np.uint8)
        b_arr = np.clip((bb * lit_o).astype(np.int32), 0, 255).astype(np.uint8)

        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                canvas[iy_o + dy, ix_o + dx, 0] = r_arr
                canvas[iy_o + dy, ix_o + dx, 1] = g_arr
                canvas[iy_o + dy, ix_o + dx, 2] = b_arr
                canvas[iy_o + dy, ix_o + dx, 3] = 255

    return _encode_rgba_png(canvas)


def package_gcode_as_3mf(
    gcode_path: Path,
    mesh_path: Path | None,
    output_3mf_path: Path,
    *,
    prediction_sec: int = 0,
    weight_g: float = 0.0,
    length_m: float = 0.0,
    nozzle_diameter: float = 0.4,
    supports_used: bool = False,
    tool_entries: list[dict[str, Any]] | None = None,
) -> Path:
    """Empaqueta un `.gcode` en formato `.gcode.3mf` compatible con FlashForge Creator 5 Pro."""
    raw_gcode_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    cleaned_lines = [
        ln
        for ln in raw_gcode_text.splitlines()
        if ln.strip() not in ("TIMELAPSE_TAKE_FRAME", "; SLICERHUB_TIMELAPSE = 1")
    ]
    gcode_bytes = ("\n".join(cleaned_lines) + "\n").encode("utf-8")
    gcode_md5 = hashlib.md5(gcode_bytes).hexdigest()

    tools = tool_entries or [
        {"tool_id": 0, "material": "PLA", "color": "#38BDF8", "used_g": weight_g, "used_m": length_m}
    ]
    primary_color = str(tools[0].get("color") or "#38BDF8")

    thumb_png = (
        render_mesh_thumbnail_png(mesh_path, width=512, height=512, base_color_hex=primary_color)
        if (mesh_path is not None and mesh_path.is_file())
        else render_mesh_thumbnail_png(gcode_path, width=512, height=512, base_color_hex=primary_color)
    )
    thumb_small_png = (
        render_mesh_thumbnail_png(mesh_path, width=128, height=128, base_color_hex=primary_color)
        if (mesh_path is not None and mesh_path.is_file())
        else render_mesh_thumbnail_png(gcode_path, width=128, height=128, base_color_hex=primary_color)
    )

    filament_xml = "\n".join(
        f'    <filament id="{int(t.get("tool_id", idx)) + 1}" tray_info_idx="" '
        f'type="{saxutils.escape(str(t.get("material", "PLA")).upper())}" '
        f'color="{saxutils.escape(str(t.get("color", "#FFFFFF")))}" '
        f'used_m="{float(t.get("used_m", length_m)):.2f}" '
        f'used_g="{float(t.get("used_g", weight_g)):.2f}" />'
        for idx, t in enumerate(tools)
    )

    slice_info_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.04.02.00"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="printer_model_id" value="Flashforge-Creator-5-Pro"/>
    <metadata key="nozzle_diameters" value="{nozzle_diameter}"/>
    <metadata key="timelapse_type" value="0"/>
    <metadata key="prediction" value="{max(0, int(prediction_sec))}"/>
    <metadata key="weight" value="{max(0.0, float(weight_g)):.2f}"/>
    <metadata key="outside" value="false"/>
    <metadata key="support_used" value="{'true' if supports_used else 'false'}"/>
    <metadata key="label_object_enabled" value="false"/>
{filament_xml}
  </plate>
</config>
"""

    model_settings_xml = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
  </plate>
</config>
"""

    plate_json = json.dumps(
        {
            "version": 2,
            "plate_index": 1,
            "bed_type": "textured_plate",
            "first_extruder": int(tools[0].get("tool_id", 0)),
            "prediction": max(0, int(prediction_sec)),
            "weight": round(float(weight_g), 2),
            "filament_ids": [int(t.get("tool_id", i)) for i, t in enumerate(tools)],
            "filament_colors": [str(t.get("color", "#FFFFFF")) for t in tools],
            "nozzle_diameter": nozzle_diameter,
            "is_seq_print": False,
        },
        indent=2,
    )

    content_types_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
  <Default Extension="png" ContentType="image/png"/>
  <Default Extension="gcode" ContentType="text/x.gcode"/>
  <Default Extension="config" ContentType="text/plain"/>
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="md5" ContentType="text/plain"/>
</Types>
"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
  <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
</Relationships>
"""

    minimal_model_xml = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources/>
  <build/>
</model>
"""

    project_settings_json = json.dumps(
        {
            "printer_model": "Flashforge Creator 5 Pro",
            "nozzle_diameter": [str(nozzle_diameter)],
            "curr_bed_type": "Textured PEI Plate",
            "filament_type": [str(t.get("material", "PLA")).upper() for t in tools],
            "filament_colour": [str(t.get("color", "#FFFFFF")) for t in tools],
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
        },
        indent=2,
    )

    output_3mf_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_3mf_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("3D/3dmodel.model", minimal_model_xml)
        zf.writestr("Metadata/plate_1.gcode", gcode_bytes)
        zf.writestr("Metadata/plate_1.gcode.md5", gcode_md5)
        zf.writestr("Metadata/plate_1.png", thumb_png)
        zf.writestr("Metadata/plate_1_small.png", thumb_small_png)
        zf.writestr("Metadata/top_1.png", thumb_png)
        zf.writestr("Metadata/pick_1.png", thumb_png)
        zf.writestr("Metadata/slice_info.config", slice_info_xml)
        zf.writestr("Metadata/model_settings.config", model_settings_xml)
        zf.writestr("Metadata/project_settings.config", project_settings_json)
        zf.writestr("Metadata/plate_1.json", plate_json)

    return output_3mf_path


def prepare_flashforge_gcode(
    gcode_path: Path,
    mesh_path: Path | None,
    output_gcode_path: Path,
    *,
    primary_color: str = "#38BDF8",
) -> Path:
    """Prepara un `.gcode` compatible con FlashForge Creator 5 Pro e inserta miniatura 140x110."""
    raw_gcode_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    cleaned_lines = [
        ln
        for ln in raw_gcode_text.splitlines()
        if ln.strip() not in ("TIMELAPSE_TAKE_FRAME", "; SLICERHUB_TIMELAPSE = 1")
    ]

    has_thumbnail = any("; THUMBNAIL_BLOCK_START" in ln or "; thumbnail begin" in ln for ln in cleaned_lines[:1500])
    if not has_thumbnail:
        thumb_png = (
            render_mesh_thumbnail_png(mesh_path, width=140, height=110, base_color_hex=primary_color)
            if (mesh_path is not None and mesh_path.is_file())
            else render_mesh_thumbnail_png(gcode_path, width=140, height=110, base_color_hex=primary_color)
        )
        b64 = base64.b64encode(thumb_png).decode("ascii")
        wrapped = [f"; {b64[i:i + 78]}" for i in range(0, len(b64), 78)]
        thumb_block = [
            "",
            "; THUMBNAIL_BLOCK_START",
            ";",
            f"; thumbnail begin 140x110 {len(b64)}",
            *wrapped,
            "; thumbnail end",
            "; THUMBNAIL_BLOCK_END",
            "",
        ]
        insert_idx = next(
            (i + 1 for i, ln in enumerate(cleaned_lines) if ln.strip() == "; CONFIG_BLOCK_END"),
            None,
        )
        if insert_idx is None:
            insert_idx = next(
                (i for i, ln in enumerate(cleaned_lines) if ln.strip() == "; EXECUTABLE_BLOCK_START"),
                0,
            )
        cleaned_lines[insert_idx:insert_idx] = thumb_block

    output_gcode_path.parent.mkdir(parents=True, exist_ok=True)
    output_gcode_path.write_text("\n".join(cleaned_lines) + "\n", encoding="utf-8")
    return output_gcode_path
