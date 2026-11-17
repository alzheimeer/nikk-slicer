#!/usr/bin/env python3
"""Lanzador nativo de escritorio para Nikk Slicer (Frontend compilado + FastAPI unificados)."""

from __future__ import annotations

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from logging.handlers import RotatingFileHandler
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = PROJECT_ROOT / "backend"
LOG_DIR = Path.home() / "Library" / "Logs" / "NikkSlicer"
LOG_FILE = LOG_DIR / "nikkslicer.log"
CHROME_PROFILE_DIR = Path.home() / "Library" / "Application Support" / "NikkSlicer" / "ChromeAppProfile"


def _load_backend_env() -> None:
    for env_path in (BACKEND_DIR / ".env", PROJECT_ROOT / ".env"):
        if not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val


_load_backend_env()

BIND_HOST = os.environ.get("NIKKSLICER_HOST", "0.0.0.0").strip() or "0.0.0.0"
PORT = int(os.environ.get("NIKKSLICER_PORT", "8000") or "8000")
LOCAL_HOST = "127.0.0.1"
BASE_URL = f"http://{LOCAL_HOST}:{PORT}"
HEALTH_URL = f"{BASE_URL}/api/health"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("nikkslicer.launcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    logger.propagate = False

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "slicerhub", "nikkslicer"):
        sub = logging.getLogger(name)
        sub.setLevel(logging.INFO)
        sub.handlers.clear()
        sub.addHandler(file_handler)
        sub.propagate = False

    return logger


def is_port_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_nikkslicer_health(timeout: float = 1.2) -> bool:
    try:
        req = urllib.request.Request(HEALTH_URL, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return False
            data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            return data.get("status") == "ok" and data.get("app") == "Nikk Slicer"
    except Exception:
        return False


def cleanup_stale_port(port: int, logger: logging.Logger) -> None:
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
    except subprocess.CalledProcessError:
        return
    pids = [int(x) for x in out.splitlines() if x.strip().isdigit()]
    my_pid = os.getpid()
    pids = [p for p in pids if p != my_pid]
    if not pids:
        return

    logger.info("Limpiando proceso previo en puerto %s: %s", port, pids)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    deadline = time.time() + 2.5
    while time.time() < deadline:
        if not is_port_open(LOCAL_HOST, port, timeout=0.2):
            return
        time.sleep(0.2)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    time.sleep(0.3)


def start_embedded_uvicorn(logger: logging.Logger):
    os.chdir(str(BACKEND_DIR))
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    import uvicorn

    config = uvicorn.Config(
        "app.main:app",
        host=BIND_HOST,
        port=PORT,
        log_level="info",
        log_config=None,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    thread = threading.Thread(target=server.run, name="nikkslicer-uvicorn", daemon=True)
    thread.start()
    logger.info("Servidor embebido uvicorn iniciado en http://%s:%s (UI local %s)", BIND_HOST, PORT, BASE_URL)
    return server, thread


def wait_for_backend(timeout_sec: float = 25.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if check_nikkslicer_health(timeout=1.0):
            return True
        time.sleep(0.3)
    return False


def _configure_macos_app_identity(logger: logging.Logger) -> None:
    """Sobrescribe el nombre de la app ('Python' -> 'Nikk Slicer') y el icono del Dock en macOS."""
    try:
        from Foundation import NSBundle, NSProcessInfo  # type: ignore[import-not-found]

        info = NSBundle.mainBundle().infoDictionary()
        if info is not None:
            info["CFBundleName"] = "Nikk Slicer"
            info["CFBundleDisplayName"] = "Nikk Slicer"
        NSProcessInfo.processInfo().setProcessName_("Nikk Slicer")
    except Exception as exc:
        logger.debug("No se pudo personalizar NSBundle/NSProcessInfo: %s", exc)


def _set_macos_dock_icon(logger: logging.Logger) -> None:
    """Asigna el icono de Nikk Slicer al Dock de macOS."""
    try:
        from AppKit import NSApplication, NSImage  # type: ignore[import-not-found]

        app = NSApplication.sharedApplication()
        for icon_path in (
            PROJECT_ROOT / "Nikk Slicer.app" / "Contents" / "Resources" / "NikkSlicer.icns",
            PROJECT_ROOT / "frontend" / "public" / "nikk-logo.jpg",
        ):
            if icon_path.is_file():
                img = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
                if img is not None:
                    app.setApplicationIconImage_(img)
                    break
    except Exception as exc:
        logger.debug("No se pudo asignar icono del Dock: %s", exc)


def open_desktop_window(logger: logging.Logger) -> None:
    try:
        _configure_macos_app_identity(logger)
        import webview  # type: ignore[import-not-found]

        logger.info("Abriendo ventana nativa con pywebview...")
        webview.create_window(
            "Nikk Slicer",
            BASE_URL,
            width=1440,
            height=920,
            min_size=(1100, 720),
        )
        _set_macos_dock_icon(logger)
        webview.start()
        return
    except ImportError:
        pass

    chrome_candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
        Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
    ]
    chrome_bin = next((c for c in chrome_candidates if c.is_file()), None)
    if chrome_bin is not None:
        CHROME_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(chrome_bin),
            f"--app={BASE_URL}",
            f"--user-data-dir={CHROME_PROFILE_DIR}",
            "--new-window",
            "--window-size=1440,920",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        logger.info("Abriendo Nikk Slicer en modo aplicación dedicada (%s)...", chrome_bin.name)
        started = time.time()
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        proc.wait()
        elapsed = time.time() - started
        if elapsed < 2.0:
            logger.info(
                "El navegador delegó la ventana a una instancia activa (%.2fs).",
                elapsed,
            )
        return

    logger.info("Abriendo Nikk Slicer en Safari...")
    subprocess.run(["open", "-a", "Safari", BASE_URL], check=False)


def main() -> int:
    logger = setup_logging()
    logger.info("=== Iniciando Nikk Slicer Desktop Launcher ===")

    reused_existing = False
    server = None
    server_thread = None

    if is_port_open(LOCAL_HOST, PORT):
        if check_nikkslicer_health():
            logger.info("Instancia previa saludable de Nikk Slicer detectada en %s; reutilizando.", BASE_URL)
            reused_existing = True
        else:
            logger.warning("Puerto %s ocupado por proceso obsoleto o ajeno; reiniciando.", PORT)
            cleanup_stale_port(PORT, logger)

    if not reused_existing:
        server, server_thread = start_embedded_uvicorn(logger)
        if not wait_for_backend(timeout_sec=25.0):
            logger.error("Timeout esperando disponibilidad de %s", HEALTH_URL)
            if server is not None:
                server.should_exit = True
            return 1

    try:
        open_desktop_window(logger)
    finally:
        if server is not None and server_thread is not None:
            logger.info("Ventana cerrada: deteniendo uvicorn limpiamente...")
            server.should_exit = True
            server_thread.join(timeout=6.0)
            logger.info("Nikk Slicer detenido correctamente.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
