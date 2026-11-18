"""Persistencia atómica de proyectos laminados en `backend/temp/projects/`."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import TEMP_DIR

PROJECTS_DIR = TEMP_DIR / "projects"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def save_slice_project(
    *,
    project_id: str,
    gcode_filename: str,
    model_filename: str,
    mesh_id: str | None,
    printer_id: str,
    material: str,
    nozzle_diameter: float,
    quality_preset: str,
    transform: dict[str, Any],
    params: dict[str, Any],
    metrics: dict[str, Any],
    ai_strategy: str | None = None,
) -> dict[str, Any]:
    """Guarda el registro JSON completo del proyecto junto al job_id."""
    record = {
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gcode_filename": gcode_filename,
        "model_filename": model_filename,
        "mesh_id": mesh_id,
        "printer_id": printer_id,
        "material": material,
        "nozzle_diameter": nozzle_diameter,
        "quality_preset": quality_preset,
        "ai_strategy": ai_strategy or "Laminado estándar",
        "transform": transform,
        "params": params,
        "metrics": metrics,
    }
    _atomic_write_json(PROJECTS_DIR / f"{project_id}.json", record)
    return record


def list_saved_projects(limit: int = 30) -> list[dict[str, Any]]:
    """Lista los proyectos guardados ordenados del más reciente al más antiguo."""
    if not PROJECTS_DIR.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for p in PROJECTS_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("project_id"):
                records.append(data)
        except Exception:
            continue
    records.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
    return records[:limit]


def get_saved_project(project_id: str) -> dict[str, Any] | None:
    """Recupera un proyecto por `project_id`."""
    clean_id = "".join(ch for ch in project_id if ch.isalnum() or ch in ("-", "_"))
    if not clean_id:
        return None
    path = PROJECTS_DIR / f"{clean_id}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None
