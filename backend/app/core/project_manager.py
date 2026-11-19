"""Gestor completo de proyectos en `~/.nikk_slicer/projects/<project_id>/`."""

from __future__ import annotations

import base64
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import MESH_CACHE_DIR, TEMP_DIR

PROJECTS_HOME_DIR = Path.home() / ".nikk_slicer" / "projects"


def _sanitize_project_id(raw_id: str | None) -> str:
    if not raw_id:
        return ""
    return "".join(ch for ch in raw_id if ch.isalnum() or ch in ("-", "_"))[:64]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp_path, path)


def _find_cached_mesh(mesh_id: str | None) -> Path | None:
    if not mesh_id:
        return None
    clean_m = _sanitize_project_id(mesh_id)
    if not clean_m:
        return None
    for ext in (".3mf", ".stl"):
        cand = MESH_CACHE_DIR / f"{clean_m}{ext}"
        if cand.is_file():
            return cand
    return None


def _find_job_gcode(job_id: str | None) -> Path | None:
    if not job_id:
        return None
    clean_j = _sanitize_project_id(job_id)
    if not clean_j:
        return None
    out_dir = TEMP_DIR / clean_j / "output"
    if not out_dir.is_dir():
        return None
    cands = [p for p in sorted(out_dir.glob("*.gcode")) if p.name != "model.flashforge.gcode"]
    return cands[0] if cands else None


def save_full_project(
    *,
    project_id: str | None = None,
    title: str,
    original_filename: str,
    printer_id: str,
    material: str,
    mesh_id: str | None = None,
    job_id: str | None = None,
    thumbnail_base64: str | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Crea o actualiza un proyecto completo en `~/.nikk_slicer/projects/<project_id>/`."""
    PROJECTS_HOME_DIR.mkdir(parents=True, exist_ok=True)
    clean_id = _sanitize_project_id(project_id)
    if not clean_id:
        clean_id = f"proj_{uuid.uuid4().hex[:10]}"

    proj_dir = PROJECTS_HOME_DIR / clean_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    json_path = proj_dir / "project.json"

    existing: dict[str, Any] = {}
    if json_path.is_file():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    now_iso = datetime.now(timezone.utc).isoformat()
    created_at = str(existing.get("created_at") or now_iso)

    model_rel = existing.get("model_file")
    src_mesh = _find_cached_mesh(mesh_id)
    if src_mesh is not None:
        dest_model = proj_dir / f"model{src_mesh.suffix.lower()}"
        shutil.copy2(src_mesh, dest_model)
        model_rel = dest_model.name

    gcode_rel = existing.get("gcode_file")
    src_gcode = _find_job_gcode(job_id)
    if src_gcode is not None:
        dest_gcode = proj_dir / "output.gcode"
        shutil.copy2(src_gcode, dest_gcode)
        gcode_rel = dest_gcode.name

    thumb_rel = existing.get("thumbnail_file")
    if thumbnail_base64 and "," in thumbnail_base64:
        try:
            b64_part = thumbnail_base64.split(",", 1)[1]
            img_bytes = base64.b64decode(b64_part)
            if len(img_bytes) > 100:
                (proj_dir / "thumbnail.png").write_bytes(img_bytes)
                thumb_rel = "thumbnail.png"
        except Exception:
            pass

    clean_title = (title or "").strip()[:80] or Path(original_filename or "Proyecto 3D").stem
    record: dict[str, Any] = {
        "project_id": clean_id,
        "title": clean_title,
        "original_filename": original_filename or "modelo.stl",
        "created_at": created_at,
        "updated_at": now_iso,
        "printer_id": printer_id,
        "material": material,
        "model_file": model_rel,
        "gcode_file": gcode_rel,
        "thumbnail_file": thumb_rel,
        "state": state if state is not None else existing.get("state", {}),
    }
    _atomic_write_json(json_path, record)
    return _format_summary(record)


def _format_summary(record: dict[str, Any]) -> dict[str, Any]:
    pid = str(record.get("project_id") or "")
    proj_dir = PROJECTS_HOME_DIR / pid
    has_thumb = bool(record.get("thumbnail_file")) and (proj_dir / str(record.get("thumbnail_file"))).is_file()
    state = record.get("state") or {}
    return {
        "project_id": pid,
        "title": str(record.get("title") or record.get("original_filename") or pid),
        "original_filename": str(record.get("original_filename") or "modelo.stl"),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or record.get("created_at") or ""),
        "printer_id": str(record.get("printer_id") or ""),
        "material": str(record.get("material") or "pla"),
        "has_thumbnail": has_thumb,
        "thumbnail_url": f"/api/projects/{pid}/thumbnail" if has_thumb else None,
        "slice_metrics": state.get("slice_metrics") or {},
    }


def list_recent_projects(limit: int = 5) -> list[dict[str, Any]]:
    """Devuelve los `limit` proyectos más recientes ordenados por `updated_at` descendente."""
    if not PROJECTS_HOME_DIR.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for sub in PROJECTS_HOME_DIR.iterdir():
        if not sub.is_dir():
            continue
        jp = sub / "project.json"
        if not jp.is_file():
            continue
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("project_id"):
                records.append(data)
        except Exception:
            continue
    records.sort(key=lambda r: str(r.get("updated_at") or r.get("created_at") or ""), reverse=True)
    return [_format_summary(r) for r in records[: max(1, limit)]]


def get_full_project(project_id: str) -> dict[str, Any] | None:
    """Carga un proyecto completo y restaura su malla en `MESH_CACHE_DIR` si es necesario."""
    clean_id = _sanitize_project_id(project_id)
    if not clean_id:
        return None
    proj_dir = PROJECTS_HOME_DIR / clean_id
    jp = proj_dir / "project.json"
    if not jp.is_file():
        return None
    try:
        record = json.loads(jp.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(record, dict):
        return None

    state = dict(record.get("state") or {})
    model_rel = record.get("model_file")
    if model_rel and (proj_dir / str(model_rel)).is_file():
        src_model = proj_dir / str(model_rel)
        mesh_id = _sanitize_project_id(state.get("mesh_id")) or f"proj_{clean_id}"
        MESH_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cached_target = MESH_CACHE_DIR / f"{mesh_id}{src_model.suffix.lower()}"
        if not cached_target.is_file():
            shutil.copy2(src_model, cached_target)
        state["mesh_id"] = mesh_id

    gcode_text: str | None = None
    gcode_rel = record.get("gcode_file")
    if gcode_rel and (proj_dir / str(gcode_rel)).is_file():
        try:
            gcode_text = (proj_dir / str(gcode_rel)).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            gcode_text = None

    summary = _format_summary(record)
    return {
        **summary,
        "state": state,
        "gcode_text": gcode_text,
        "model_url": f"/api/projects/{clean_id}/model" if model_rel else None,
    }


def get_project_thumbnail_path(project_id: str) -> Path | None:
    clean_id = _sanitize_project_id(project_id)
    if not clean_id:
        return None
    p = PROJECTS_HOME_DIR / clean_id / "thumbnail.png"
    return p if p.is_file() else None


def get_project_model_path(project_id: str) -> tuple[Path, str] | None:
    clean_id = _sanitize_project_id(project_id)
    if not clean_id:
        return None
    proj_dir = PROJECTS_HOME_DIR / clean_id
    jp = proj_dir / "project.json"
    if not jp.is_file():
        return None
    try:
        record = json.loads(jp.read_text(encoding="utf-8"))
        model_rel = record.get("model_file")
        orig_name = str(record.get("original_filename") or model_rel or "modelo.stl")
        if model_rel and (proj_dir / str(model_rel)).is_file():
            return proj_dir / str(model_rel), orig_name
    except Exception:
        pass
    return None


def delete_full_project(project_id: str) -> bool:
    clean_id = _sanitize_project_id(project_id)
    if not clean_id:
        return False
    proj_dir = PROJECTS_HOME_DIR / clean_id
    if not proj_dir.is_dir():
        return False
    shutil.rmtree(proj_dir, ignore_errors=True)
    return True
