"""Exportador `.gcode.3mf` fiel a Orca-Flashforge (`bbs_3mf.cpp`) para FlashForge Creator 5 Pro.

Módulo independiente para no alterar el flujo actual de `.gcode` ni `gcode_3mf_packager.py`.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import uuid
import xml.sax.saxutils as saxutils
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


@dataclass(slots=True)
class FlashforgeToolUsage:
    tool_id: int
    material: str
    color: str
    used_g: float
    used_m: float
    tray_info_idx: str = "GFG99"


@dataclass(slots=True)
class ParsedGcodeMeta:
    prediction_sec: int
    total_weight_g: float
    total_length_m: float
    nozzle_diameter: float
    supports_used: bool
    tools: list[FlashforgeToolUsage]


def _parse_duration_seconds(raw: str) -> int:
    total = 0
    for val, unit in re.findall(r"(\d+)\s*([dhms])", raw.lower()):
        n = int(val)
        if unit == "d":
            total += n * 86400
        elif unit == "h":
            total += n * 3600
        elif unit == "m":
            total += n * 60
        elif unit == "s":
            total += n
    return total


def _parse_float_list(raw: str) -> list[float]:
    out: list[float] = []
    for part in raw.split(","):
        s = part.strip()
        if not s:
            continue
        try:
            out.append(float(s))
        except ValueError:
            out.append(0.0)
    return out


def parse_gcode_metadata(gcode_text: str) -> ParsedGcodeMeta:
    """Extrae tiempos, pesos, longitudes, colores, materiales y cabezales usados desde el G-code."""
    head = "\n".join(gcode_text.splitlines()[:400])
    tail = "\n".join(gcode_text.splitlines()[-400:])
    meta_block = f"{head}\n{tail}"

    prediction_sec = 0
    m_time = re.search(r";\s*estimated printing time[^=]*=\s*(.+)", meta_block)
    if m_time:
        prediction_sec = _parse_duration_seconds(m_time.group(1))

    m_total_g = re.search(r";\s*total filament used \[g\]\s*=\s*([0-9.]+)", meta_block)
    total_weight_g = float(m_total_g.group(1)) if m_total_g else 0.0

    used_g_list: list[float] = []
    m_g_list = re.search(r";\s*filament used \[g\]\s*=\s*(.+)", meta_block)
    if m_g_list:
        used_g_list = _parse_float_list(m_g_list.group(1))

    used_mm_list: list[float] = []
    m_mm_list = re.search(r";\s*filament used \[mm\]\s*=\s*(.+)", meta_block)
    if m_mm_list:
        used_mm_list = _parse_float_list(m_mm_list.group(1))

    colors = ["#FFFFFF", "#FFFFFF", "#FFFFFF", "#FFFFFF"]
    m_colors = re.search(r";\s*SLICERHUB_EXTRUDER_COLORS\s*=\s*(.+)", meta_block)
    if m_colors:
        parts = [c.strip() for c in m_colors.group(1).split(",") if c.strip()]
        for idx, col in enumerate(parts[:4]):
            colors[idx] = col if col.startswith("#") else f"#{col}"
    else:
        m_fcol = re.search(r";\s*filament_colour\s*=\s*(.+)", meta_block)
        if m_fcol:
            parts = [c.strip() for c in m_fcol.group(1).split(";") if c.strip()]
            for idx, col in enumerate(parts[:4]):
                colors[idx] = col if col.startswith("#") else f"#{col}"

    materials = ["PLA", "PLA", "PLA", "PLA"]
    m_types = re.search(r";\s*filament_type\s*=\s*(.+)", meta_block)
    if m_types:
        tparts = [p.strip().strip('"').upper() for p in m_types.group(1).split(";") if p.strip()]
        for idx, mt in enumerate(tparts[:4]):
            if mt:
                materials[idx] = mt

    nozzle_diameter = 0.4
    m_noz = re.search(r";\s*nozzle_diameter\s*=\s*([0-9.]+)", meta_block)
    if m_noz:
        try:
            nozzle_diameter = float(m_noz.group(1))
        except ValueError:
            pass

    supports_used = bool(
        re.search(r";\s*enable_support\s*=\s*1\b", meta_block)
        or re.search(r";TYPE:Support\b", gcode_text)
    )

    used_tools = sorted({int(m) for m in re.findall(r"^T([0-3])\b", gcode_text, flags=re.M)})
    if not used_tools:
        m_fil = re.search(r";\s*filament:\s*([0-9,\s]+)", meta_block)
        if m_fil:
            used_tools = sorted(
                {int(x.strip()) - 1 for x in m_fil.group(1).split(",") if x.strip().isdigit() and 1 <= int(x.strip()) <= 4}
            )
    if not used_tools:
        used_tools = [0]

    tools: list[FlashforgeToolUsage] = []
    for t_id in used_tools:
        g_val = used_g_list[t_id] if t_id < len(used_g_list) else (total_weight_g if len(used_tools) == 1 else 0.0)
        m_val = (used_mm_list[t_id] / 1000.0) if t_id < len(used_mm_list) else 0.0
        mat = materials[t_id] if t_id < len(materials) else "PLA"
        tray_idx = "GFG99" if "PETG" in mat else "GFA00"
        tools.append(
            FlashforgeToolUsage(
                tool_id=t_id,
                material=mat,
                color=colors[t_id] if t_id < len(colors) else "#FFFFFF",
                used_g=round(g_val, 2),
                used_m=round(m_val, 2),
                tray_info_idx=tray_idx,
            )
        )

    if total_weight_g <= 0.0:
        total_weight_g = round(sum(t.used_g for t in tools), 2)
    total_length_m = round(sum(t.used_m for t in tools), 2)

    return ParsedGcodeMeta(
        prediction_sec=prediction_sec,
        total_weight_g=total_weight_g,
        total_length_m=total_length_m,
        nozzle_diameter=nozzle_diameter,
        supports_used=supports_used,
        tools=tools,
    )


def _hex_to_rgb(hex_c: str) -> tuple[int, int, int]:
    hx = hex_c.strip().lstrip("#")
    if len(hx) >= 6:
        try:
            return int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        except ValueError:
            pass
    return 56, 189, 248


def render_multicolor_gcode_thumbnail_png(
    gcode_text: str,
    tool_colors: dict[int, str],
    *,
    width: int = 512,
    height: int = 512,
) -> bytes:
    """Renderiza una miniatura 3D isométrica multicolor con fondo transparente desde el G-code."""
    cur_x, cur_y, cur_z = 0.0, 0.0, 0.0
    cur_t = 0
    in_exec = False
    segs: list[tuple[float, float, float, float, float, float, int]] = []

    re_x = re.compile(r"\bX([-+]?\d*\.?\d+)")
    re_y = re.compile(r"\bY([-+]?\d*\.?\d+)")
    re_z = re.compile(r"\bZ([-+]?\d*\.?\d+)")
    re_e = re.compile(r"\bE([-+]?\d*\.?\d+)")
    re_t = re.compile(r"^T([0-3])\b")

    for raw in gcode_text.splitlines():
        ln = raw.strip()
        if not ln:
            continue
        if ln == "; EXECUTABLE_BLOCK_START":
            in_exec = True
            continue
        if not in_exec and (ln.startswith(";") or ln.startswith("M")):
            continue
        mt = re_t.match(ln)
        if mt:
            cur_t = int(mt.group(1))
            continue
        if not (ln.startswith("G0 ") or ln.startswith("G1 ")):
            continue

        nx, ny, nz = cur_x, cur_y, cur_z
        mx = re_x.search(ln)
        my = re_y.search(ln)
        mz = re_z.search(ln)
        me = re_e.search(ln)
        if mx:
            nx = float(mx.group(1))
        if my:
            ny = float(my.group(1))
        if mz:
            nz = float(mz.group(1))

        if ln.startswith("G1 ") and me and float(me.group(1)) > 0.0:
            # Ignorar línea de purga en el borde derecho/frontal
            if not (cur_x > 248.0 or nx > 248.0):
                segs.append((cur_x, cur_y, cur_z, nx, ny, nz, cur_t))

        cur_x, cur_y, cur_z = nx, ny, nz

    if not segs:
        im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        return buf.getvalue()

    # Submuestrear si hay demasiados segmentos para mantener render rápido (<0.3s)
    step = max(1, len(segs) // 18000)
    segs = segs[::step]

    arr = np.asarray([(s[0], s[1], s[2], s[3], s[4], s[5]) for s in segs], dtype=np.float32)
    tools_arr = np.asarray([s[6] for s in segs], dtype=np.int32)

    pts0 = arr[:, :3]
    pts1 = arr[:, 3:6]
    all_pts = np.vstack([pts0, pts1])
    pmin = all_pts.min(axis=0)
    pmax = all_pts.max(axis=0)
    center = (pmin + pmax) * 0.5
    extent = float(np.max(pmax - pmin)) or 1.0

    # Rotación isométrica (3/4 frontal superior)
    az = np.radians(35.0)
    el = np.radians(-58.0)
    rz = np.array([[np.cos(az), -np.sin(az), 0.0], [np.sin(az), np.cos(az), 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, np.cos(el), -np.sin(el)], [0.0, np.sin(el), np.cos(el)]], dtype=np.float32)
    rot = rx @ rz

    r0 = ((pts0 - center) / extent) @ rot.T
    r1 = ((pts1 - center) / extent) @ rot.T
    rx_all = np.concatenate([r0[:, 0], r1[:, 0]])
    ry_all = np.concatenate([r0[:, 1], r1[:, 1]])
    span = max(float(rx_all.max() - rx_all.min()), float(ry_all.max() - ry_all.min()), 1e-4)
    scale_px = min(width, height) * 0.78 / span
    cx_2d = (rx_all.min() + rx_all.max()) * 0.5
    cy_2d = (ry_all.min() + ry_all.max()) * 0.5

    x0 = (r0[:, 0] - cx_2d) * scale_px + width * 0.5
    y0 = -(r0[:, 1] - cy_2d) * scale_px + height * 0.5
    x1 = (r1[:, 0] - cx_2d) * scale_px + width * 0.5
    y1 = -(r1[:, 1] - cy_2d) * scale_px + height * 0.5
    depth = (r0[:, 2] + r1[:, 2]) * 0.5
    order = np.argsort(depth)

    rgb_map = {t: _hex_to_rgb(col) for t, col in tool_colors.items()}
    im = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    lw = max(1, int(round(width / 160)))
    z_min, z_max = float(pts0[:, 2].min()), float(pts0[:, 2].max())
    z_span = max(0.2, z_max - z_min)

    for idx in order:
        t_id = int(tools_arr[idx])
        br, bg, bb = rgb_map.get(t_id, (200, 210, 220))
        shade = 0.72 + 0.28 * ((float(pts0[idx, 2]) - z_min) / z_span)
        col = (min(255, int(br * shade)), min(255, int(bg * shade)), min(255, int(bb * shade)), 255)
        draw.line([(float(x0[idx]), float(y0[idx])), (float(x1[idx]), float(y1[idx]))], fill=col, width=lw)

    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def export_flashforge_gcode_3mf(
    gcode_path: Path,
    output_3mf_path: Path,
    *,
    mesh_path: Path | None = None,
    object_name: str | None = None,
    printer_model_id: str = "Flashforge-Creator-5-Pro",
    printer_model_name: str = "Flashforge Creator 5 Pro",
    timelapse_type: int = 0,
    tool_overrides: list[dict[str, Any]] | None = None,
) -> Path:
    """Genera un `.gcode.3mf` replicando la estructura de `Orca-Flashforge` (`bbs_3mf.cpp`)."""
    raw_gcode_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    cleaned_lines = [
        ln
        for ln in raw_gcode_text.splitlines()
        if ln.strip() not in ("TIMELAPSE_TAKE_FRAME", "; SLICERHUB_TIMELAPSE = 1")
    ]
    cleaned_gcode = "\n".join(cleaned_lines) + "\n"

    meta = parse_gcode_metadata(cleaned_gcode)
    tools = meta.tools
    if tool_overrides:
        tools = [
            FlashforgeToolUsage(
                tool_id=int(t.get("tool_id", idx)),
                material=str(t.get("material", "PLA")).upper(),
                color=str(t.get("color", "#FFFFFF")),
                used_g=round(float(t.get("used_g", 0.0)), 2),
                used_m=round(float(t.get("used_m", 0.0)), 2),
                tray_info_idx=str(t.get("tray_info_idx") or ("GFG99" if "PETG" in str(t.get("material", "")).upper() else "GFA00")),
            )
            for idx, t in enumerate(tool_overrides)
        ]

    tool_color_map = {t.tool_id: t.color for t in tools}
    thumb_png = render_multicolor_gcode_thumbnail_png(
        cleaned_gcode, tool_color_map, width=512, height=512
    )
    with Image.open(io.BytesIO(thumb_png)) as im_big:
        im_small = im_big.resize((128, 128), Image.Resampling.LANCZOS)
        buf_small = io.BytesIO()
        im_small.save(buf_small, format="PNG")
        thumb_small_png = buf_small.getvalue()

        # Miniatura 140x110 transparente incrustada en G-code (Orca-Flashforge / Flash Studio)
        im_140 = im_big.resize((110, 110), Image.Resampling.LANCZOS)
        canvas_140 = Image.new("RGBA", (140, 110), (0, 0, 0, 0))
        canvas_140.paste(im_140, (15, 0), im_140)
        buf_140 = io.BytesIO()
        canvas_140.save(buf_140, format="PNG")
        b64_140 = base64.b64encode(buf_140.getvalue()).decode("ascii")

    wrapped_140 = "\n".join(
        f"; {b64_140[i : i + 78]}" for i in range(0, len(b64_140), 78)
    )
    thumb_block = (
        f"; thumbnail begin 140x110 {len(b64_140)}\n"
        f"{wrapped_140}\n"
        f"; thumbnail end"
    )
    if re.search(r";\s*thumbnail\s+begin\s+\S+\s+\d+", cleaned_gcode, re.I):
        cleaned_gcode = re.sub(
            r";\s*thumbnail\s+begin\s+\S+\s+\d+.*?;\s*thumbnail\s+end",
            thumb_block,
            cleaned_gcode,
            count=1,
            flags=re.S | re.I,
        )
    else:
        cleaned_gcode = f"; THUMBNAIL_BLOCK_START\n{thumb_block}\n; THUMBNAIL_BLOCK_END\n\n{cleaned_gcode}"

    gcode_bytes = cleaned_gcode.encode("utf-8")
    # bbs_3mf.cpp:6092 -> sprintf("%02X", digest[j]) -> MD5 en MAYÚSCULAS (32 hex)
    gcode_md5_upper = hashlib.md5(gcode_bytes).hexdigest().upper()

    obj_label = saxutils.escape((object_name or gcode_path.stem or "model").strip())
    plate_uuid = uuid.uuid4().hex
    noz_str = f"{meta.nozzle_diameter:.1f}"
    noz_4 = ",".join([noz_str] * 4)

    def _rgba8(hex_c: str) -> str:
        hx = hex_c.strip().lstrip("#")
        if len(hx) == 6:
            return f"#{hx.upper()}FF"
        if len(hx) == 8:
            return f"#{hx.upper()}"
        return "#FFFFFFFF"

    filament_xml = "\n".join(
        f'    <filament id="{t.tool_id + 1}" tray_info_idx="{saxutils.escape(t.tray_info_idx)}" '
        f'type="{saxutils.escape(t.material)}" color="{saxutils.escape(_rgba8(t.color))}" '
        f'used_m="{t.used_m:.2f}" used_g="{t.used_g:.2f}" group_id="{idx}" '
        f'nozzle_diameter="{meta.nozzle_diameter:.2f}" volume_type="Standard" '
        f'used_for_object="true" used_for_support="false" />'
        for idx, t in enumerate(tools)
    )
    nozzle_xml = "\n".join(
        f'    <nozzle id="{t.tool_id}" extruder_id="{t.tool_id + 1}" '
        f'nozzle_diameter="{noz_str}" volume_type="Standard" />'
        for t in tools
    )

    slice_info_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header>
    <header_item key="X-BBL-Client-Type" value="slicer"/>
    <header_item key="X-BBL-Client-Version" value="02.06.00.51"/>
    <header_item key="OrcaSlicer-Version" value="2.4.2"/>
    <uuid value="{plate_uuid}"/>
  </header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="extruder_type" value="0 0 0 0"/>
    <metadata key="nozzle_volume_type" value="0 0 0 0"/>
    <metadata key="printer_model_id" value="{saxutils.escape(printer_model_id)}"/>
    <metadata key="nozzle_diameters" value="{noz_4}"/>
    <metadata key="timelapse_type" value="{int(timelapse_type)}"/>
    <metadata key="prediction" value="{max(0, int(meta.prediction_sec))}"/>
    <metadata key="weight" value="{max(0.0, float(meta.total_weight_g)):.2f}"/>
    <metadata key="first_layer_time" value="15,0"/>
    <metadata key="outside" value="false"/>
    <metadata key="support_used" value="{'true' if meta.supports_used else 'false'}"/>
    <metadata key="label_object_enabled" value="false"/>
    <metadata key="enable_filament_dynamic_map" value="false"/>
    <metadata key="has_filament_switcher" value="false"/>
    <metadata key="filament_maps" value="1 2 3 4"/>
    <metadata key="limit_filament_maps" value="4 4 0 0"/>
    <object identify_id="1" name="{obj_label}" skipped="false" />
{filament_xml}
{nozzle_xml}
  </plate>
</config>
"""

    model_settings_xml = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <plate>
    <metadata key="plater_id" value="1"/>
    <metadata key="plater_name" value=""/>
    <metadata key="locked" value="false"/>
    <metadata key="filament_map_mode" value="Auto For Flush"/>
    <metadata key="filament_maps" value="1 2 3 4"/>
    <metadata key="gcode_file" value="Metadata/plate_1.gcode"/>
    <metadata key="thumbnail_file" value="Metadata/plate_1.png"/>
    <metadata key="thumbnail_no_light_file" value="Metadata/plate_no_light_1.png"/>
    <metadata key="top_file" value="Metadata/top_1.png"/>
    <metadata key="pick_file" value="Metadata/pick_1.png"/>
    <metadata key="pattern_bbox_file" value="Metadata/plate_1.json"/>
  </plate>
</config>
"""

    model_settings_rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/Metadata/plate_1.gcode" Id="rel-1" Type="http://schemas.bambulab.com/package/2021/gcode"/>
</Relationships>
"""

    custom_gcode_xml = """<?xml version="1.0" encoding="utf-8"?>
<custom_gcodes_per_layer>
<plate>
<plate_info id="1"/>
<mode value="MultiExtruder"/>
</plate>
</custom_gcodes_per_layer>
"""

    filament_seq_json = json.dumps(
        {
            "plate_1": {
                "nozzle_sequence": [t.tool_id for t in tools],
                "optimal_assignment": [0, 1, 2, 3],
                "sequence": [t.tool_id + 1 for t in tools],
            }
        },
        separators=(",", ":"),
    )

    plate_json = json.dumps(
        {
            "bbox_all": [20.0, 20.0, 236.0, 236.0],
            "bbox_objects": [{"area": 1000.0, "bbox": [20.0, 20.0, 236.0, 236.0], "id": 1, "layer_height": 0.2, "name": obj_label}],
            "bed_type": "textured_plate",
            "filament_colors": [_rgba8(t.color) for t in tools],
            "filament_ids": [t.tool_id for t in tools],
            "first_extruder": tools[0].tool_id if tools else 0,
            "first_layer_time": 15.0,
            "is_seq_print": False,
            "nozzle_diameter": meta.nozzle_diameter,
            "version": 2,
        },
        separators=(",", ":"),
    )

    project_settings_json = json.dumps(
        {
            "printer_model": printer_model_name,
            "nozzle_diameter": [str(meta.nozzle_diameter)] * 4,
            "curr_bed_type": "Textured PEI Plate",
            "filament_type": [t.material for t in tools],
            "filament_colour": [t.color for t in tools],
            "printable_area": ["0x0", "256x0", "256x256", "0x256"],
            "printable_height": "256",
        },
        indent=2,
    )

    content_types_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="gcode" ContentType="text/x.gcode"/>
</Types>
"""

    rels_xml = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/thumbnail"/>
 <Relationship Target="/Metadata/plate_1.png" Id="rel-4" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-middle"/>
 <Relationship Target="/Metadata/plate_1_small.png" Id="rel-5" Type="http://schemas.bambulab.com/package/2021/cover-thumbnail-small"/>
</Relationships>
"""

    minimal_model_xml = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" xmlns:p="http://schemas.microsoft.com/3dmanufacturing/production/2015/06" requiredextensions="p">
 <metadata name="Application">BambuStudio-02.06.00.51</metadata>
 <metadata name="OrcaSlicer">2.4.2</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources/>
 <build/>
</model>
"""

    output_3mf_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_3mf_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("3D/3dmodel.model", minimal_model_xml)
        zf.writestr("Metadata/plate_1.gcode", gcode_bytes)
        zf.writestr("Metadata/plate_1.gcode.md5", gcode_md5_upper)
        zf.writestr("Metadata/plate_1.png", thumb_png)
        zf.writestr("Metadata/plate_1_small.png", thumb_small_png)
        zf.writestr("Metadata/plate_no_light_1.png", thumb_png)
        zf.writestr("Metadata/top_1.png", thumb_png)
        zf.writestr("Metadata/pick_1.png", thumb_png)
        zf.writestr("Metadata/slice_info.config", slice_info_xml)
        zf.writestr("Metadata/model_settings.config", model_settings_xml)
        zf.writestr("Metadata/_rels/model_settings.config.rels", model_settings_rels_xml)
        zf.writestr("Metadata/custom_gcode_per_layer.xml", custom_gcode_xml)
        zf.writestr("Metadata/filament_sequence.json", filament_seq_json)
        zf.writestr("Metadata/project_settings.config", project_settings_json)
        zf.writestr("Metadata/plate_1.json", plate_json)

    return output_3mf_path
