"""Postprocesador universal de G-code para pausas por capa (Klipper y FlashForge M25)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_PAUSE_HEADER_RE = re.compile(
    r"^;\s*===\s*NIKK SLICER:\s*(?:PAUSA EN CAPA\s+\d+|CAMBIO MANUAL DE CARRETE EN T\d+).*?===\s*$"
)
_LAYER_COMMENT_RE = re.compile(
    r"^;\s*(?:LAYER_CHANGE|LAYER\s*:\s*(\d+)|layer\s+(\d+))", re.IGNORECASE
)
_Z_COMMENT_RE = re.compile(r"^;\s*Z\s*:\s*([0-9]+(?:\.[0-9]+)?)", re.IGNORECASE)
_G_Z_RE = re.compile(r"\bZ([0-9]+(?:\.[0-9]+)?)\b")


def is_flashforge_creator_printer(printer_id: str) -> bool:
    pid = (printer_id or "").lower()
    return "creator5" in pid or "flashforge" in pid


def build_pause_block(
    printer_id: str,
    layer: int,
    z_mm: float | None = None,
    note: str = "",
    *,
    source: str = "manual",
    slot: int | None = None,
    outgoing_color: str | None = None,
    incoming_color: str | None = None,
) -> list[str]:
    """Construye las líneas G-code de pausa adaptadas al firmware de la impresora."""
    z_str = f"{z_mm:.2f}" if z_mm is not None else "?"
    clean_note = (note or "Pausa programada").strip().replace("\n", " ")
    if source == "auto_multicolor" and slot is not None and is_flashforge_creator_printer(printer_id):
        out_c = (outgoing_color or "Color anterior").strip()
        in_c = (incoming_color or "Color nuevo").strip()
        return [
            f"; === NIKK SLICER: CAMBIO MANUAL DE CARRETE EN T{slot} ===",
            f"; Cambiar carrete T{slot}: {out_c} -> {in_c} en Z={z_str}mm",
            "G91",
            "G1 Z10 F1200",
            "G90",
            "G1 X10 Y10 F6000",
            "M25",
            "G91",
            "G1 Z-10 F1200",
            "G90",
        ]

    header = f"; === NIKK SLICER: PAUSA EN CAPA {layer} (Z={z_str}mm) · {clean_note} ==="
    if is_flashforge_creator_printer(printer_id):
        return [
            header,
            "G91",
            "G1 Z10 F1200",
            "G90",
            "G1 X10 Y10 F6000",
            "M25",
            "G91",
            "G1 Z-10 F1200",
            "G90",
        ]
    return [
        header,
        "PAUSE",
    ]


def strip_nikk_pause_blocks(lines: list[str]) -> list[str]:
    """Elimina bloques de pausa inyectados previamente por Nikk Slicer (idempotente)."""
    cleaned: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if _PAUSE_HEADER_RE.match(line.strip()):
            i += 1
            if i < n and lines[i].strip().startswith("; Cambiar carrete "):
                i += 1
            if i < n and lines[i].strip() == "PAUSE":
                i += 1
                continue
            # Bloque FlashForge: G91, G1 Z10..., G90, G1 X10 Y10..., M25, G91, G1 Z-10..., G90
            ff_seq = ["G91", "G1 Z10", "G90", "G1 X10", "M25", "G91", "G1 Z-10", "G90"]
            matched = 0
            while i < n and matched < len(ff_seq):
                if lines[i].strip().startswith(ff_seq[matched]):
                    i += 1
                    matched += 1
                else:
                    break
            continue
        cleaned.append(line)
        i += 1
    return cleaned


def _index_gcode_layers(lines: list[str]) -> list[tuple[int, int, float]]:
    """Devuelve lista de `(layer_num_1based, insert_line_idx, z_mm)` en un solo barrido."""
    layer_markers: list[tuple[int, int, float]] = []
    current_z = 0.0
    layer_count = 0

    for idx, raw in enumerate(lines):
        s = raw.strip()
        if not s:
            continue
        zm = _Z_COMMENT_RE.match(s)
        if zm:
            try:
                current_z = float(zm.group(1))
            except ValueError:
                pass
            if layer_markers and layer_markers[-1][1] == idx - 1:
                ln, _, _ = layer_markers[-1]
                layer_markers[-1] = (ln, idx, current_z)
            continue

        lm = _LAYER_COMMENT_RE.match(s)
        if lm:
            layer_count += 1
            layer_markers.append((layer_count, idx, current_z))
            continue

        if s.startswith(("G0 ", "G1 ")) and "Z" in s:
            gz = _G_Z_RE.search(s)
            if gz:
                try:
                    current_z = float(gz.group(1))
                except ValueError:
                    pass

    return layer_markers


def apply_layer_pauses_to_gcode(
    gcode_text: str,
    printer_id: str,
    pauses: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Inyecta pausas por capa sobre el texto G-code en memoria (< 20 ms)."""
    lines = strip_nikk_pause_blocks(gcode_text.splitlines())
    if not pauses:
        return "\n".join(lines) + ("\n" if gcode_text.endswith("\n") else ""), []

    markers = _index_gcode_layers(lines)
    total_layers = len(markers)
    marker_by_layer = {ln: (insert_idx, z_val) for ln, insert_idx, z_val in markers}

    # Agrupar pausas por capa (manteniendo orden y deduplicando por capa)
    dedup: dict[int, dict[str, Any]] = {}
    for p in pauses:
        raw_layer = int(p.get("layer") or 1)
        eff_layer = max(1, min(total_layers, raw_layer)) if total_layers > 0 else max(1, raw_layer)
        dedup[eff_layer] = {
            "layer": eff_layer,
            "note": str(p.get("note") or ""),
            "z_mm": p.get("z_mm"),
            "source": str(p.get("source") or "manual"),
            "slot": p.get("slot"),
            "outgoing_color": p.get("outgoing_color"),
            "incoming_color": p.get("incoming_color"),
        }

    insertions: dict[int, list[str]] = {}
    applied: list[dict[str, Any]] = []
    for eff_layer in sorted(dedup.keys()):
        item = dedup[eff_layer]
        if eff_layer in marker_by_layer:
            insert_idx, detected_z = marker_by_layer[eff_layer]
            z_val = float(detected_z) if detected_z > 0 else item.get("z_mm")
        else:
            insert_idx = max(0, len(lines) - 1)
            z_val = item.get("z_mm")

        block = build_pause_block(
            printer_id=printer_id,
            layer=eff_layer,
            z_mm=float(z_val) if z_val is not None else None,
            note=item["note"],
            source=item["source"],
            slot=item["slot"],
            outgoing_color=item["outgoing_color"],
            incoming_color=item["incoming_color"],
        )
        insertions.setdefault(insert_idx, []).extend(block)
        applied.append(
            {
                "layer": eff_layer,
                "note": item["note"],
                "z_mm": round(float(z_val), 2) if z_val is not None else None,
                "source": item["source"],
                "slot": item["slot"],
                "outgoing_color": item["outgoing_color"],
                "incoming_color": item["incoming_color"],
            }
        )

    out_lines: list[str] = []
    for idx, line in enumerate(lines):
        out_lines.append(line)
        if idx in insertions:
            out_lines.extend(insertions[idx])

    result_text = "\n".join(out_lines) + "\n"
    return result_text, applied


def apply_layer_pauses_to_file(
    gcode_path: Path,
    printer_id: str,
    pauses: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Lee un `.gcode` en disco, inyecta pausas y sobrescribe el archivo (< 50 ms)."""
    raw_text = gcode_path.read_text(encoding="utf-8", errors="ignore")
    updated_text, applied = apply_layer_pauses_to_gcode(raw_text, printer_id, pauses)
    gcode_path.write_text(updated_text, encoding="utf-8")
    return updated_text, applied
