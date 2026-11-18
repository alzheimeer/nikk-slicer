"""Bitácora persistente de errores y fallos de laminado, IA y conectores."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import TEMP_DIR

ERROR_JOURNAL_LOG_PATH = TEMP_DIR / "bitacora_errores.log"
ERROR_JOURNAL_JSONL_PATH = TEMP_DIR / "bitacora_errores.jsonl"
MAX_JOURNAL_ENTRIES = 200
_JOURNAL_LOCK = threading.Lock()


def record_error(
    source: str,
    message: str,
    *,
    printer_id: str | None = None,
    detail: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Registra un fallo en `bitacora_errores.log` y `bitacora_errores.jsonl`."""
    now = datetime.now(timezone.utc).astimezone()
    ts_iso = now.isoformat(timespec="seconds")
    ts_human = now.strftime("%Y-%m-%d %H:%M:%S")

    entry: dict[str, Any] = {
        "timestamp": ts_iso,
        "source": source,
        "printer_id": printer_id or "",
        "message": str(message).strip(),
        "detail": str(detail).strip() if detail else "",
        "context": context or {},
    }

    with _JOURNAL_LOCK:
        TEMP_DIR.mkdir(parents=True, exist_ok=True)
        # 1. Log legible en texto plano
        printer_tag = f" | printer={printer_id}" if printer_id else ""
        lines = [f"[{ts_human}] [{source}{printer_tag}] {entry['message']}"]
        if entry["detail"]:
            lines.append(f"  Detalle: {entry['detail']}")
        if entry["context"]:
            lines.append(f"  Contexto: {json.dumps(entry['context'], ensure_ascii=False)}")
        lines.append("")
        with ERROR_JOURNAL_LOG_PATH.open("a", encoding="utf-8") as fh:
            fh.write("\n".join(lines))

        # 2. JSONL estructurado (últimos MAX_JOURNAL_ENTRIES)
        existing: list[str] = []
        if ERROR_JOURNAL_JSONL_PATH.is_file():
            existing = [
                ln
                for ln in ERROR_JOURNAL_JSONL_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
                if ln.strip()
            ]
        existing.append(json.dumps(entry, ensure_ascii=False))
        trimmed = existing[-MAX_JOURNAL_ENTRIES:]
        ERROR_JOURNAL_JSONL_PATH.write_text("\n".join(trimmed) + "\n", encoding="utf-8")

    return entry


def read_error_journal(limit: int = 50) -> list[dict[str, Any]]:
    """Devuelve las últimas entradas de la bitácora ordenadas de más reciente a más antigua."""
    with _JOURNAL_LOCK:
        if not ERROR_JOURNAL_JSONL_PATH.is_file():
            return []
        lines = [
            ln
            for ln in ERROR_JOURNAL_JSONL_PATH.read_text(encoding="utf-8", errors="ignore").splitlines()
            if ln.strip()
        ]
    parsed: list[dict[str, Any]] = []
    for ln in reversed(lines[-max(1, min(limit, MAX_JOURNAL_ENTRIES)) :]):
        try:
            parsed.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return parsed


def clear_error_journal() -> None:
    """Limpia los archivos de bitácora de errores."""
    with _JOURNAL_LOCK:
        for path in (ERROR_JOURNAL_LOG_PATH, ERROR_JOURNAL_JSONL_PATH):
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass
