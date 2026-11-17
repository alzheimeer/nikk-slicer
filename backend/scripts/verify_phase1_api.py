#!/usr/bin/env python3
"""Batería de pruebas de verificación de Fase 1 contra http://127.0.0.1:8000."""

from __future__ import annotations

import json
import tempfile
import urllib.request
import uuid
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"
CUBE_STL = (
    Path(__file__).resolve().parents[1]
    / "profiles"
    / "test_assets"
    / "calibration_cube_20mm.stl"
)


def post_multipart(url: str, fields: dict[str, str], file_path: Path) -> tuple[int, dict]:
    """Envía una petición multipart/form-data y devuelve (status_code, json_body)."""
    boundary = f"----SlicerHubBoundary{uuid.uuid4().hex}"
    body = bytearray()

    for key, val in fields.items():
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
        body.extend(f"{val}\r\n".encode())

    body.extend(f"--{boundary}\r\n".encode())
    body.extend(
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'.encode()
    )
    body.extend(b"Content-Type: application/octet-stream\r\n\r\n")
    body.extend(file_path.read_bytes())
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode())

    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def make_oversized_stl(path: Path, size_xy: float = 240.0, size_z: float = 10.0) -> None:
    """Genera un STL válido de 240x240x10 mm que excede la cama de la Ender 3 S1 Pro."""
    hx = size_xy / 2.0
    hy = size_xy / 2.0
    v = [
        (-hx, -hy, 0),
        (hx, -hy, 0),
        (hx, hy, 0),
        (-hx, hy, 0),
        (-hx, -hy, size_z),
        (hx, -hy, size_z),
        (hx, hy, size_z),
        (-hx, hy, size_z),
    ]
    faces = [
        ((0, 0, -1), (0, 2, 1)),
        ((0, 0, -1), (0, 3, 2)),
        ((0, 0, 1), (4, 5, 6)),
        ((0, 0, 1), (4, 6, 7)),
        ((0, -1, 0), (0, 1, 5)),
        ((0, -1, 0), (0, 5, 4)),
        ((1, 0, 0), (1, 2, 6)),
        ((1, 0, 0), (1, 6, 5)),
        ((0, 1, 0), (2, 3, 7)),
        ((0, 1, 0), (2, 7, 6)),
        ((-1, 0, 0), (3, 0, 4)),
        ((-1, 0, 0), (3, 4, 7)),
    ]
    lines = ["solid oversized_box"]
    for n, (a, b, c) in faces:
        lines.append(f"  facet normal {n[0]} {n[1]} {n[2]}")
        lines.append("    outer loop")
        for idx in (a, b, c):
            p = v[idx]
            lines.append(f"      vertex {p[0]:.6f} {p[1]:.6f} {p[2]:.6f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid oversized_box")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    matrix = [
        ("flsun_v400", "pla", "215", "60", "false", "estandar"),
        ("flsun_t1_pro", "petg", "250", "75", "true", "alta_velocidad"),
        ("flsun_sr", "pla", "210", "60", "true", "estandar"),
        ("creator5_pro", "petg", "245", "75", "true", "mecanico_resistente"),
        ("ender3_s1_pro", "pla", "210", "60", "false", "estandar"),
    ]

    print("=== 1 y 2. Pruebas /api/slice y descarga G-code en las 5 impresoras ===")
    for printer_id, material, noz, bed, supports, preset in matrix:
        status, data = post_multipart(
            f"{BASE_URL}/api/slice",
            {
                "printer_id": printer_id,
                "material": material,
                "nozzle_temp": noz,
                "bed_temp": bed,
                "supports": supports,
                "quality_preset": preset,
            },
            CUBE_STL,
        )
        assert status == 200, f"{printer_id}: status={status}"
        gcode_url = f"{BASE_URL}{data['gcode_url']}"
        with urllib.request.urlopen(gcode_url, timeout=60) as dl:
            assert dl.status == 200
            gcode_text = dl.read().decode("utf-8", errors="ignore")

        assert len(gcode_text) > 10000, f"{printer_id}: G-code demasiado corto"

        if material == "petg" and supports == "true":
            assert "; support_top_z_distance = 0.26" in gcode_text, (
                f"{printer_id}: falta support_top_z_distance = 0.26 en PETG con soportes"
            )
            assert "; enable_support = 1" in gcode_text

        if printer_id == "ender3_s1_pro":
            assert "; gcode_flavor = marlin2" in gcode_text
            assert "M420 S1 Z10" in gcode_text
            assert "M900 K" in gcode_text

        print(
            f"  [PASS] {printer_id:14s} | {material.upper():4s} | supports={supports:5s} | "
            f"tiempo={data['estimated_time']:8s} | {data['filament_grams']}g / {data['filament_meters']}m | "
            f"gcode={len(gcode_text)} B"
        )

    print("=== 3. Prueba /api/analyze-mesh fuera de volumen en Ender 3 S1 Pro ===")
    with tempfile.TemporaryDirectory() as tmpdir:
        oversized = Path(tmpdir) / "oversized_240mm.stl"
        make_oversized_stl(oversized, size_xy=240.0, size_z=10.0)
        status, analysis = post_multipart(
            f"{BASE_URL}/api/analyze-mesh",
            {"printer_id": "ender3_s1_pro"},
            oversized,
        )
        assert status == 200
        assert analysis["fits_in_volume"] is False, f"Se esperaba fits_in_volume=False: {analysis}"
        assert any("exceden" in w for w in analysis["warnings"]), (
            f"Falta alerta de volumen: {analysis['warnings']}"
        )
        print(
            f"  [PASS] analyze-mesh oversized (240x240x10mm en Ender 3 S1 Pro): "
            f"fits_in_volume={analysis['fits_in_volume']}, warnings={analysis['warnings']}"
        )


if __name__ == "__main__":
    main()
