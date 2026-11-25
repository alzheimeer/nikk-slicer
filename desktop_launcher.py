#!/usr/bin/env python3
"""Lanzador nativo de escritorio para Nikk Slicer (Frontend compilado + FastAPI unificados)."""

from __future__ import annotations

import json
import locale
import logging
import os
import queue
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform.startswith("win")


class _SafeLogStream:
    """Flujo seguro para sys.stdout/sys.stderr en ejecutables --windowed sin consola."""

    def __init__(self, stream):
        self._stream = stream

    def write(self, data: str) -> int:
        try:
            res = self._stream.write(data)
            self._stream.flush()
            return res
        except Exception:
            return len(data) if isinstance(data, str) else 0

    def flush(self) -> None:
        try:
            self._stream.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        return False

    def __getattr__(self, name: str):
        return getattr(self._stream, name)


def _ensure_stdio_streams() -> None:
    """Redirige sys.stdout/sys.stderr cuando son None (PyInstaller --windowed en Windows)."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        if IS_WINDOWS:
            base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "NikkSlicer"
        else:
            base = Path.home() / ".nikk_slicer"
        base.mkdir(parents=True, exist_ok=True)
        log_path = base / "launcher.log"
        stream = _SafeLogStream(open(log_path, "a", encoding="utf-8", errors="replace"))
    except Exception:
        stream = _SafeLogStream(open(os.devnull, "w", encoding="utf-8"))
    if sys.stdout is None:
        sys.stdout = stream  # type: ignore[assignment]
    if sys.stderr is None:
        sys.stderr = stream  # type: ignore[assignment]


_ensure_stdio_streams()

if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    PROJECT_ROOT = Path(sys._MEIPASS)  # type: ignore[attr-defined]
else:
    PROJECT_ROOT = Path(__file__).resolve().parent

BACKEND_DIR = PROJECT_ROOT / "backend"
if IS_MACOS:
    LOG_DIR = Path.home() / "Library" / "Logs" / "NikkSlicer"
    CHROME_PROFILE_DIR = Path.home() / "Library" / "Application Support" / "NikkSlicer" / "ChromeAppProfile"
elif IS_WINDOWS:
    _local_app_data = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
    LOG_DIR = _local_app_data / "NikkSlicer" / "Logs"
    CHROME_PROFILE_DIR = _local_app_data / "NikkSlicer" / "ChromeAppProfile"
else:
    LOG_DIR = Path.home() / ".nikk_slicer" / "logs"
    CHROME_PROFILE_DIR = Path.home() / ".nikk_slicer" / "chrome_profile"
LOG_FILE = LOG_DIR / "nikkslicer.log"


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


def _win_no_window_kwargs() -> dict[str, object]:
    if IS_WINDOWS and hasattr(subprocess, "CREATE_NO_WINDOW"):
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}


def cleanup_stale_port(port: int, logger: logging.Logger) -> None:
    my_pid = os.getpid()
    pids: list[int] = []
    if IS_WINDOWS:
        try:
            out = subprocess.check_output(
                ["netstat", "-ano", "-p", "TCP"],
                text=True,
                errors="ignore",
                **_win_no_window_kwargs(),
            )
            for line in out.splitlines():
                parts = line.split()
                if len(parts) >= 5 and f":{port}" in parts[1] and parts[3].upper() == "LISTENING":
                    if parts[4].isdigit() and int(parts[4]) != my_pid:
                        pids.append(int(parts[4]))
        except Exception:
            return
    else:
        try:
            out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True).strip()
        except subprocess.CalledProcessError:
            return
        pids = [int(x) for x in out.splitlines() if x.strip().isdigit() and int(x) != my_pid]

    if not pids:
        return

    logger.info("Limpiando proceso previo en puerto %s: %s", port, pids)
    for pid in pids:
        if IS_WINDOWS:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                **_win_no_window_kwargs(),
            )
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    deadline = time.time() + 2.5
    while time.time() < deadline:
        if not is_port_open(LOCAL_HOST, port, timeout=0.2):
            return
        time.sleep(0.2)
    if not IS_WINDOWS:
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
        timeout_graceful_shutdown=1,
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]

    def _run_uvicorn() -> None:
        try:
            server.run()
        except BaseException:
            logger.exception("Error fatal ejecutando servidor embebido uvicorn")

    thread = threading.Thread(target=_run_uvicorn, name="nikkslicer-uvicorn", daemon=True)
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


_PENDING_OPEN_FILES: list[str] = [
    arg for arg in sys.argv[1:] if arg.lower().endswith((".stl", ".3mf")) and Path(arg).is_file()
]


def _detect_splash_lang() -> str:
    """Detecta idioma ES/EN desde configuración local o locale del sistema."""
    try:
        if IS_WINDOWS:
            cfg_base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "NikkSlicer"
        else:
            cfg_base = Path.home() / ".nikk_slicer"
        for cand in (cfg_base / "settings.json", cfg_base / "config.json"):
            if cand.is_file():
                raw = json.loads(cand.read_text(encoding="utf-8", errors="ignore"))
                lang = str(raw.get("language") or raw.get("lang") or "").lower()
                if lang.startswith("en"):
                    return "en"
                if lang.startswith("es"):
                    return "es"
    except Exception:
        pass
    try:
        loc = (locale.getlocale()[0] or os.environ.get("LANG") or "").lower()
        if loc.startswith("en"):
            return "en"
    except Exception:
        pass
    return "es"


class _SplashScreen:
    """Pantalla de bienvenida nativa ligera (Tkinter) sin barra de título."""

    _MESSAGES = {
        "es": {
            "loading_cfg": "Cargando configuración...",
            "starting_engine": "Iniciando motor de laminado...",
            "preparing_ws": "Preparando espacio de trabajo 3D...",
            "ready": "Listo",
        },
        "en": {
            "loading_cfg": "Loading configuration...",
            "starting_engine": "Starting slicing engine...",
            "preparing_ws": "Preparing 3D workspace...",
            "ready": "Ready",
        },
    }

    def __init__(self, version: str = "v1.0.0") -> None:
        self.version = version
        self.lang = _detect_splash_lang()
        self._msgs = self._MESSAGES.get(self.lang, self._MESSAGES["es"])
        self._cmd_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._ready_evt = threading.Event()
        self._closed = False
        self._thread: threading.Thread | None = None

    def msg(self, key: str) -> str:
        return self._msgs.get(key, key)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run_tk, name="nikkslicer-splash", daemon=True)
        self._thread.start()
        self._ready_evt.wait(timeout=1.5)

    def set_progress(self, percent: int, status_key_or_text: str) -> None:
        if self._closed:
            return
        text = self._msgs.get(status_key_or_text, status_key_or_text)
        self._cmd_queue.put(("progress", (max(0, min(100, int(percent))), text)))

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._cmd_queue.put(("close", None))
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _find_logo_path(self) -> Path | None:
        for cand in (
            PROJECT_ROOT / "frontend" / "public" / "nikk-logo.jpg",
            PROJECT_ROOT / "nikk-logo.jpg",
        ):
            if cand.is_file():
                return cand
        return None

    def _run_tk(self) -> None:
        try:
            import tkinter as tk
            from PIL import Image, ImageTk  # type: ignore[import-not-found]
        except Exception:
            self._ready_evt.set()
            return

        root = None
        try:
            root = tk.Tk()
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            width, height = 420, 460
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = max(0, (sw - width) // 2)
            y = max(0, (sh - height) // 2)
            root.geometry(f"{width}x{height}+{x}+{y}")
            root.configure(bg="#06B6D4")

            # Contenedor interior oscuro con borde sutil cian
            card = tk.Frame(root, bg="#0B1120", highlightthickness=1, highlightbackground="#1E293B")
            card.pack(fill="both", expand=True, padx=1, pady=1)

            # Barra de acento superior
            accent = tk.Frame(card, bg="#06B6D4", height=3)
            accent.pack(fill="x", side="top")

            # Encabezado: Título + versión
            hdr = tk.Frame(card, bg="#0B1120")
            hdr.pack(fill="x", padx=24, pady=(22, 10))
            tk.Label(
                hdr,
                text="Nikk Slicer",
                fg="#F8FAFC",
                bg="#0B1120",
                font=("Segoe UI", 18, "bold"),
            ).pack(side="left")
            tk.Label(
                hdr,
                text=self.version,
                fg="#06B6D4",
                bg="#0B1120",
                font=("Segoe UI", 10, "bold"),
            ).pack(side="right", pady=(6, 0))

            # Imagen central nikk-logo.jpg
            logo_holder = tk.Frame(card, bg="#0B1120")
            logo_holder.pack(expand=True, pady=(4, 8))
            logo_ref = None
            logo_path = self._find_logo_path()
            if logo_path is not None:
                try:
                    img = Image.open(logo_path).convert("RGBA")
                    img.thumbnail((236, 236), Image.Resampling.LANCZOS)
                    logo_ref = ImageTk.PhotoImage(img)
                    lbl_img = tk.Label(logo_holder, image=logo_ref, bg="#0B1120", bd=0)
                    lbl_img.image = logo_ref  # type: ignore[attr-defined]
                    lbl_img.pack()
                except Exception:
                    logo_ref = None
            if logo_ref is None:
                tk.Label(
                    logo_holder,
                    text="NIKK SLICER",
                    fg="#06B6D4",
                    bg="#0B1120",
                    font=("Segoe UI", 22, "bold"),
                ).pack()

            # Pie: estado + barra de progreso
            footer = tk.Frame(card, bg="#0B1120")
            footer.pack(fill="x", side="bottom", padx=24, pady=(0, 24))

            status_row = tk.Frame(footer, bg="#0B1120")
            status_row.pack(fill="x", pady=(0, 8))
            status_var = tk.StringVar(value=self.msg("loading_cfg"))
            pct_var = tk.StringVar(value="20%")
            tk.Label(
                status_row,
                textvariable=status_var,
                fg="#CBD5E1",
                bg="#0B1120",
                font=("Segoe UI", 9),
                anchor="w",
            ).pack(side="left")
            tk.Label(
                status_row,
                textvariable=pct_var,
                fg="#10B981",
                bg="#0B1120",
                font=("Segoe UI", 9, "bold"),
                anchor="e",
            ).pack(side="right")

            bar_w = width - 50
            bar_h = 8
            canvas = tk.Canvas(
                footer,
                width=bar_w,
                height=bar_h,
                bg="#1E293B",
                highlightthickness=0,
                bd=0,
            )
            canvas.pack(fill="x")
            fill_rect = canvas.create_rectangle(0, 0, int(bar_w * 0.20), bar_h, fill="#06B6D4", width=0)

            def _poll_queue() -> None:
                try:
                    while True:
                        cmd, payload = self._cmd_queue.get_nowait()
                        if cmd == "progress":
                            pct, text = payload  # type: ignore[misc]
                            status_var.set(str(text))
                            pct_var.set(f"{pct}%")
                            fill_color = "#10B981" if pct >= 100 else "#06B6D4"
                            canvas.coords(fill_rect, 0, 0, max(4, int(bar_w * (pct / 100.0))), bar_h)
                            canvas.itemconfig(fill_rect, fill=fill_color)
                        elif cmd == "close":
                            root.quit()
                            root.destroy()
                            return
                except queue.Empty:
                    pass
                root.after(45, _poll_queue)

            root.update_idletasks()
            root.update()
            self._ready_evt.set()
            root.after(45, _poll_queue)
            root.mainloop()
            # Liberar referencias Tk en el mismo hilo donde se crearon
            del status_var, pct_var, logo_ref, canvas, fill_rect
            root = None
            import gc
            gc.collect()
        except Exception:
            self._ready_evt.set()
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass


def _queue_open_file(path_str: str, logger: logging.Logger) -> bool:
    p = Path(path_str)
    if p.suffix.lower() not in (".stl", ".3mf") or not p.is_file():
        return False
    _PENDING_OPEN_FILES.append(str(p))
    try:
        import webview  # type: ignore[import-not-found]

        win = webview.active_window()
        if win is not None:
            win.evaluate_js("window.dispatchEvent(new CustomEvent('nikk-open-pending-file'));")
    except Exception as exc:
        logger.debug("No se pudo notificar archivo pendiente al WebView: %s", exc)
    return True


def _install_macos_open_file_handler(logger: logging.Logger) -> None:
    """Registra application:openFile:/openFiles:/openURLs: en BrowserView.AppDelegate antes de iniciar."""
    try:
        import objc  # type: ignore[import-not-found]
        from webview.platforms import cocoa  # type: ignore[import-not-found]

        app_del = cocoa.BrowserView.AppDelegate

        def application_openFile_(self, sender, filename):  # type: ignore[no-untyped-def]
            return _queue_open_file(str(filename), logger)

        def application_openFiles_(self, sender, filenames):  # type: ignore[no-untyped-def]
            handled = False
            for fn in list(filenames or []):
                if _queue_open_file(str(fn), logger):
                    handled = True
            try:
                sender.replyToOpenOrPrint_(0 if handled else 1)
            except Exception:
                pass

        def application_openURLs_(self, sender, urls):  # type: ignore[no-untyped-def]
            for url in list(urls or []):
                try:
                    path = url.path() if hasattr(url, "path") else str(url)
                    if path:
                        _queue_open_file(str(path), logger)
                except Exception:
                    pass

        objc.classAddMethod(
            app_del,
            b"application:openFile:",
            objc.selector(application_openFile_, selector=b"application:openFile:", signature=b"B@:@@"),
        )
        objc.classAddMethod(
            app_del,
            b"application:openFiles:",
            objc.selector(application_openFiles_, selector=b"application:openFiles:", signature=b"v@:@@"),
        )
        objc.classAddMethod(
            app_del,
            b"application:openURLs:",
            objc.selector(application_openURLs_, selector=b"application:openURLs:", signature=b"v@:@@"),
        )
    except Exception as exc:
        logger.warning("No se pudo instalar handler openFiles en AppKit: %s", exc)


class DesktopApi:
    """Puente JS -> Python para diálogo nativo de guardado y apertura de archivos en macOS."""

    def has_pending_open_file(self) -> bool:
        return any(Path(p).is_file() for p in _PENDING_OPEN_FILES)

    def get_pending_open_file(self) -> dict[str, str] | None:
        while _PENDING_OPEN_FILES:
            p = Path(_PENDING_OPEN_FILES.pop(0))
            if p.is_file():
                return {
                    "name": p.name,
                    "path": str(p),
                }
        return None

    def save_file(self, url: str, suggested_name: str) -> dict[str, object]:
        import webview  # type: ignore[import-not-found]

        win = webview.active_window()
        if win is None:
            return {"saved": False, "reason": "No hay ventana activa."}
        dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", webview.SAVE_DIALOG)
        target = win.create_file_dialog(
            dialog_type,
            save_filename=suggested_name,
        )
        if not target:
            return {"saved": False, "cancelled": True}
        dest = Path(target[0] if isinstance(target, (list, tuple)) else target)
        with urllib.request.urlopen(url, timeout=45) as resp:
            dest.write_bytes(resp.read())
        return {"saved": True, "path": str(dest)}

    def save_post_file(
        self,
        url: str,
        payload_json: str,
        suggested_name: str,
        file_types: list[str] | None = None,
    ) -> dict[str, object]:
        import webview  # type: ignore[import-not-found]

        win = webview.active_window()
        if win is None:
            return {"saved": False, "error": "No hay ventana activa."}

        dialog_type = getattr(getattr(webview, "FileDialog", None), "SAVE", webview.SAVE_DIALOG)
        ft_tuple = tuple(str(ft) for ft in (file_types or []) if ft)
        target = win.create_file_dialog(
            dialog_type,
            save_filename=suggested_name,
            file_types=ft_tuple,
        )
        if not target:
            return {"saved": False, "cancelled": True}

        dest = Path(target[0] if isinstance(target, (list, tuple)) else target)
        expected_ext = Path(suggested_name).suffix
        if expected_ext and dest.suffix.lower() != expected_ext.lower():
            dest = dest.with_suffix(expected_ext)

        target_url = url if str(url).startswith(("http://", "https://")) else f"http://127.0.0.1:8000{url}"
        req = urllib.request.Request(
            target_url,
            data=payload_json.encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as fh:
                    shutil.copyfileobj(resp, fh)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            try:
                detail = json.loads(err_body).get("detail") or err_body
            except Exception:
                detail = err_body or str(exc)
            return {"saved": False, "error": f"Error al exportar ({exc.code}): {detail}"}
        except Exception as exc:
            return {"saved": False, "error": str(exc)}

        return {"saved": True, "path": str(dest)}

    def open_new_window(self, project_id: str | None = None) -> dict[str, object]:
        open_new_project_window(project_id=project_id)
        return {"opened": True}

    def set_window_title(self, title: str) -> dict[str, object]:
        import webview  # type: ignore[import-not-found]

        win = webview.active_window()
        if win is not None and title:
            try:
                win.set_title(str(title)[:100])
            except Exception:
                pass
        return {"ok": True}

    def focus_window_by_id(self, window_id: str) -> dict[str, object]:
        def _do_focus() -> None:
            try:
                from AppKit import NSApp  # type: ignore[import-not-found]
                from Foundation import NSOperationQueue  # type: ignore[import-not-found]

                def _on_main():
                    win = _WINDOW_BY_ID.get(str(window_id or ""))
                    if win is not None:
                        ns_win = getattr(win, "native", None)
                        if ns_win is None and hasattr(win, "gui"):
                            ns_win = getattr(win.gui, "window", None)
                        if ns_win is not None:
                            ns_win.makeKeyAndOrderFront_(None)
                    NSApp.activateIgnoringOtherApps_(True)

                NSOperationQueue.mainQueue().addOperationWithBlock_(_on_main)
            except Exception:
                pass

        threading.Thread(target=_do_focus, daemon=True).start()
        return {"focused": True}

    def pick_slicer_executable(self) -> dict[str, object]:
        import webview  # type: ignore[import-not-found]

        win = webview.active_window()
        if win is None:
            return {"cancelled": True}
        selected = win.create_file_dialog(webview.OPEN_DIALOG)
        if not selected:
            return {"cancelled": True}
        chosen = selected[0] if isinstance(selected, (list, tuple)) else selected
        return {"cancelled": False, "path": str(chosen)}


_MENU_TARGET = None
_RECENT_SUBMENU = None
_WINDOW_BY_ID: dict[str, object] = {}


def _build_window_url(project_id: str | None = None) -> tuple[str, str]:
    wsid = uuid.uuid4().hex[:10]
    if project_id:
        return wsid, f"{BASE_URL}/?window_session_id={wsid}&project_id={project_id}"
    return wsid, f"{BASE_URL}/?window_session_id={wsid}"


def _register_window(wsid: str, win: object) -> None:
    _WINDOW_BY_ID[wsid] = win
    try:
        def _on_closed():
            _WINDOW_BY_ID.pop(wsid, None)

        win.events.closed += _on_closed  # type: ignore[attr-defined]
    except Exception:
        pass


def open_new_project_window(project_id: str | None = None) -> None:
    if IS_WINDOWS:
        try:
            cmd = [sys.executable]
            if not getattr(sys, "frozen", False):
                cmd.append(str(Path(__file__).resolve()))
            cmd.append("--new-window")
            if project_id:
                cmd.append(f"--project-id={project_id}")
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **_win_no_window_kwargs(),
            )
            return
        except Exception:
            pass
    try:
        import webview  # type: ignore[import-not-found]

        wsid, url = _build_window_url(project_id)
        win = webview.create_window(
            "Nikk Slicer",
            url,
            width=1440,
            height=920,
            min_size=(1100, 720),
            maximized=True,
            background_color="#020617",
            js_api=DesktopApi(),
        )
        if win is not None:
            _register_window(wsid, win)
            try:
                win.maximize()
            except Exception:
                pass
    except Exception:
        pass


def _populate_recent_submenu(submenu) -> None:
    try:
        from AppKit import NSMenuItem  # type: ignore[import-not-found]

        submenu.removeAllItems()
        sys.path.insert(0, str(BACKEND_DIR))
        from app.core.project_manager import list_recent_projects  # type: ignore[import-not-found]

        recents = list_recent_projects(limit=5)
        if not recents:
            empty_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Sin proyectos recientes", None, ""
            )
            empty_item.setEnabled_(False)
            submenu.addItem_(empty_item)
            return

        for proj in recents:
            title = str(proj.get("title") or proj.get("original_filename") or "Proyecto")
            pid = str(proj.get("project_id") or "")
            item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                title, "openRecentProject:", ""
            )
            item.setTarget_(_MENU_TARGET)
            item.setRepresentedObject_(pid)
            submenu.addItem_(item)
    except Exception:
        pass


def _install_macos_archivo_menu(logger: logging.Logger) -> None:
    global _MENU_TARGET, _RECENT_SUBMENU
    try:
        import objc  # type: ignore[import-not-found]
        import webview  # type: ignore[import-not-found]
        from AppKit import (  # type: ignore[import-not-found]
            NSApp,
            NSEventModifierFlagCommand,
            NSEventModifierFlagShift,
            NSMenu,
            NSMenuItem,
        )
        from Foundation import NSObject, NSOperationQueue  # type: ignore[import-not-found]

        def _dispatch_js_async(script: str) -> None:
            def _worker() -> None:
                try:
                    win = webview.active_window()
                    if win is not None:
                        win.evaluate_js(script)
                except Exception:
                    pass

            threading.Thread(target=_worker, daemon=True).start()

        class NikkMenuTarget(NSObject):
            def newProjectWindow_(self, _sender):
                threading.Thread(target=open_new_project_window, daemon=True).start()

            def openProjectsModal_(self, _sender):
                _dispatch_js_async(
                    "window.dispatchEvent(new CustomEvent('nikk:menu-open-projects'))"
                )

            def saveProject_(self, _sender):
                _dispatch_js_async(
                    "window.dispatchEvent(new CustomEvent('nikk:menu-save-project'))"
                )

            def saveProjectAs_(self, _sender):
                _dispatch_js_async(
                    "window.dispatchEvent(new CustomEvent('nikk:menu-save-project-as'))"
                )

            def closeProject_(self, _sender):
                _dispatch_js_async(
                    "window.dispatchEvent(new CustomEvent('nikk:menu-close-project'))"
                )

            def openRecentProject_(self, sender):
                pid = str(sender.representedObject() or "")
                if not pid:
                    return

                def _open_recent_worker() -> None:
                    try:
                        win = webview.active_window()
                        if win is None:
                            open_new_project_window(project_id=pid)
                            return
                        has_model = False
                        try:
                            has_model = bool(
                                win.evaluate_js("Boolean(window.__nikkHasModel)")
                            )
                        except Exception:
                            has_model = False
                        if has_model:
                            open_new_project_window(project_id=pid)
                        else:
                            win.evaluate_js(
                                f"window.dispatchEvent(new CustomEvent('nikk:open-project', {{ detail: {{ projectId: '{pid}' }} }}))"
                            )
                    except Exception:
                        pass

                threading.Thread(target=_open_recent_worker, daemon=True).start()

            def menuNeedsUpdate_(self, menu):
                _populate_recent_submenu(menu)

        def _setup_on_main():
            global _MENU_TARGET, _RECENT_SUBMENU
            main_menu = NSApp.mainMenu()
            if main_menu is None:
                return
            for i in range(main_menu.numberOfItems()):
                if main_menu.itemAtIndex_(i).title() == "Archivo":
                    return

            _MENU_TARGET = NikkMenuTarget.alloc().init()
            archivo_menu = NSMenu.alloc().initWithTitle_("Archivo")

            it_new = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Nuevo proyecto (Nueva ventana)", "newProjectWindow:", "n"
            )
            it_new.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
            it_new.setTarget_(_MENU_TARGET)
            archivo_menu.addItem_(it_new)

            it_open = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Abrir proyecto...", "openProjectsModal:", "o"
            )
            it_open.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
            it_open.setTarget_(_MENU_TARGET)
            archivo_menu.addItem_(it_open)

            it_save = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Guardar proyecto", "saveProject:", "s"
            )
            it_save.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
            it_save.setTarget_(_MENU_TARGET)
            archivo_menu.addItem_(it_save)

            it_save_as = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Guardar proyecto como...", "saveProjectAs:", "S"
            )
            it_save_as.setKeyEquivalentModifierMask_(
                NSEventModifierFlagCommand | NSEventModifierFlagShift
            )
            it_save_as.setTarget_(_MENU_TARGET)
            archivo_menu.addItem_(it_save_as)

            it_close = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Cerrar proyecto", "closeProject:", "w"
            )
            it_close.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
            it_close.setTarget_(_MENU_TARGET)
            archivo_menu.addItem_(it_close)

            archivo_menu.addItem_(NSMenuItem.separatorItem())

            _RECENT_SUBMENU = NSMenu.alloc().initWithTitle_("Proyectos recientes")
            _RECENT_SUBMENU.setDelegate_(_MENU_TARGET)
            _populate_recent_submenu(_RECENT_SUBMENU)
            it_recent = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Proyectos recientes", None, ""
            )
            it_recent.setSubmenu_(_RECENT_SUBMENU)
            archivo_menu.addItem_(it_recent)

            archivo_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                "Archivo", None, ""
            )
            archivo_item.setSubmenu_(archivo_menu)
            insert_idx = 1 if main_menu.numberOfItems() >= 1 else 0
            main_menu.insertItem_atIndex_(archivo_item, insert_idx)

            # Registrar menú nativo "Ventana" para Dock (clic derecho) y Cmd+`
            has_ventana = any(
                main_menu.itemAtIndex_(i).title() in ("Ventana", "Window")
                for i in range(main_menu.numberOfItems())
            )
            if not has_ventana:
                window_menu = NSMenu.alloc().initWithTitle_("Ventana")
                it_min = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Minimizar", "performMiniaturize:", "m"
                )
                it_min.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand)
                window_menu.addItem_(it_min)

                it_zoom = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Zoom", "performZoom:", ""
                )
                window_menu.addItem_(it_zoom)

                window_menu.addItem_(NSMenuItem.separatorItem())

                it_front = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Traer todas al frente", "arrangeInFront:", ""
                )
                window_menu.addItem_(it_front)

                window_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Ventana", None, ""
                )
                window_item.setSubmenu_(window_menu)
                main_menu.addItem_(window_item)
                NSApp.setWindowsMenu_(window_menu)

        NSOperationQueue.mainQueue().addOperationWithBlock_(_setup_on_main)
    except Exception as exc:
        logger.warning("No se pudo instalar menú Archivo nativo: %s", exc)


def _find_windows_icon() -> Path | None:
    for candidate in (
        PROJECT_ROOT / "nikk_slicer.ico",
        PROJECT_ROOT / "frontend" / "public" / "nikk_slicer.ico",
        Path(sys.executable).resolve().parent / "nikk_slicer.ico",
    ):
        if candidate.is_file():
            return candidate
    return None


def _build_windows_menu(logger: logging.Logger) -> list[object]:
    try:
        import webview  # type: ignore[import-not-found]
        from webview.menu import Menu, MenuAction, MenuSeparator  # type: ignore[import-not-found]

        def _dispatch(script: str) -> None:
            def _run() -> None:
                try:
                    win = webview.active_window()
                    if win is not None:
                        win.evaluate_js(script)
                except Exception:
                    pass

            threading.Thread(target=_run, daemon=True).start()

        recent_items: list[object] = []
        try:
            sys.path.insert(0, str(BACKEND_DIR))
            from app.core.project_manager import list_recent_projects  # type: ignore[import-not-found]

            for proj in list_recent_projects(limit=5):
                title = str(proj.get("title") or proj.get("original_filename") or "Proyecto")
                pid = str(proj.get("project_id") or "")
                recent_items.append(
                    MenuAction(
                        title,
                        lambda _pid=pid: _dispatch(
                            f"window.dispatchEvent(new CustomEvent('nikk:menu-open-recent', {{ detail: {{ projectId: '{_pid}' }} }}))"
                        ),
                    )
                )
        except Exception:
            pass

        if not recent_items:
            recent_items.append(MenuAction("Sin proyectos recientes", lambda: None))

        archivo_items: list[object] = [
            MenuAction("Nuevo proyecto (Ctrl+N)", lambda: threading.Thread(target=open_new_project_window, daemon=True).start()),
            MenuAction("Abrir proyecto... (Ctrl+O)", lambda: _dispatch("window.dispatchEvent(new CustomEvent('nikk:menu-open-projects'))")),
            MenuAction("Guardar proyecto (Ctrl+S)", lambda: _dispatch("window.dispatchEvent(new CustomEvent('nikk:menu-save-project'))")),
            MenuAction("Guardar proyecto como...", lambda: _dispatch("window.dispatchEvent(new CustomEvent('nikk:menu-save-project-as'))")),
            MenuAction("Cerrar proyecto (Ctrl+W)", lambda: _dispatch("window.dispatchEvent(new CustomEvent('nikk:menu-close-project'))")),
            MenuSeparator(),
            Menu("Proyectos recientes", recent_items),
            MenuSeparator(),
            MenuAction("Salir", lambda: [w.destroy() for w in list(webview.windows)]),
        ]

        ver_items: list[object] = [
            MenuAction("Recargar", lambda: _dispatch("window.location.reload()")),
            MenuAction("Pantalla completa", lambda: webview.active_window().toggle_fullscreen() if webview.active_window() else None),
        ]

        ventana_items: list[object] = [
            MenuAction("Nueva ventana", lambda: threading.Thread(target=open_new_project_window, daemon=True).start()),
        ]

        return [
            Menu("Archivo", archivo_items),
            Menu("Ver", ver_items),
            Menu("Ventana", ventana_items),
        ]
    except Exception as exc:
        logger.warning("No se pudo construir menú nativo de Windows: %s", exc)
        return []


def open_desktop_window(
    logger: logging.Logger,
    initial_project_id: str | None = None,
    splash: _SplashScreen | None = None,
) -> None:
    try:
        if IS_MACOS:
            _configure_macos_app_identity(logger)
        import webview  # type: ignore[import-not-found]

        logger.info("Abriendo ventana nativa con pywebview...")
        if IS_MACOS:
            _install_macos_open_file_handler(logger)
        wsid, url = _build_window_url(initial_project_id)
        main_win = webview.create_window(
            "Nikk Slicer",
            url,
            width=1440,
            height=920,
            min_size=(1100, 720),
            maximized=True,
            background_color="#020617",
            js_api=DesktopApi(),
        )
        if main_win is not None:
            _register_window(wsid, main_win)
        if IS_MACOS:
            _set_macos_dock_icon(logger)

        splash_done = threading.Event()

        def _finish_splash() -> None:
            if splash_done.is_set():
                return
            splash_done.set()
            if splash is not None:
                splash.set_progress(100, "ready")
                time.sleep(0.18)
                splash.close()

        def _on_loaded() -> None:
            try:
                if main_win is not None:
                    main_win.maximize()
            except Exception:
                pass
            threading.Thread(target=_finish_splash, daemon=True).start()

        if main_win is not None:
            try:
                main_win.events.loaded += _on_loaded
            except Exception:
                pass

        def _on_webview_ready(win=None):
            time.sleep(0.35)
            try:
                if win is not None:
                    win.maximize()
            except Exception:
                pass
            if IS_MACOS:
                _install_macos_archivo_menu(logger)
            # Respaldo por si el evento `loaded` no dispara en algún entorno
            def _fallback_close() -> None:
                if not splash_done.wait(timeout=3.0):
                    _finish_splash()

            threading.Thread(target=_fallback_close, daemon=True).start()

        start_kwargs: dict[str, object] = {
            "func": _on_webview_ready,
            "args": (main_win,),
        }
        if IS_WINDOWS:
            start_kwargs["gui"] = "edgechromium"
            win_menus = _build_windows_menu(logger)
            if win_menus:
                start_kwargs["menu"] = win_menus
            win_icon = _find_windows_icon()
            if win_icon is not None:
                start_kwargs["icon"] = str(win_icon)

        webview.start(**start_kwargs)
        return
    except Exception as exc:
        logger.warning("pywebview no disponible o falló (%s); usando fallback de navegador.", exc)

    if IS_WINDOWS:
        program_files = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        program_files_x86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        local_app_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        browser_candidates = [
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
        ]
    else:
        browser_candidates = [
            Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    chrome_bin = next((c for c in browser_candidates if c.is_file()), None)
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
            **_win_no_window_kwargs(),
        )
        if splash is not None:
            splash.set_progress(100, "ready")
            splash.close()
        proc.wait()
        elapsed = time.time() - started
        if elapsed < 2.0:
            logger.info(
                "El navegador delegó la ventana a una instancia activa (%.2fs).",
                elapsed,
            )
        return

    if IS_WINDOWS:
        logger.info("Abriendo Nikk Slicer en el navegador predeterminado de Windows...")
        os.startfile(BASE_URL)  # type: ignore[attr-defined]
        return

    logger.info("Abriendo Nikk Slicer en Safari...")
    subprocess.run(["open", "-a", "Safari", BASE_URL], check=False)


def _build_macos_splash_html(logo_path: Path | None, version: str, msgs: dict[str, str]) -> str:
    import base64

    logo_tag = (
        '<div style="width:128px;height:128px;border-radius:16px;background:#0F172A;'
        'display:flex;align-items:center;justify-content:center;font-weight:800;'
        'font-size:32px;color:#22D3EE;border:1px solid #1E293B;">NK</div>'
    )
    if logo_path is not None and logo_path.is_file():
        try:
            b64 = base64.b64encode(logo_path.read_bytes()).decode("ascii")
            ext = logo_path.suffix.lower().lstrip(".") or "jpeg"
            if ext == "jpg":
                ext = "jpeg"
            logo_tag = (
                f'<img src="data:image/{ext};base64,{b64}" '
                'style="width:140px;height:140px;object-fit:contain;border-radius:14px;" />'
            )
        except Exception:
            pass

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; user-select: none; }}
  html, body {{
    width: 100%; height: 100%; background: #0B1120; color: #F8FAFC;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
    overflow: hidden;
  }}
  .card {{
    width: 100%; height: 100%; display: flex; flex-direction: column;
    border: 1px solid #1E293B; border-top: 3px solid #06B6D4; background: #0B1120;
  }}
  .hdr {{ padding: 24px 24px 10px; display: flex; justify-content: space-between; align-items: baseline; }}
  .title {{ font-size: 20px; font-weight: 700; color: #F8FAFC; }}
  .ver {{ font-size: 11px; color: #64748B; font-family: ui-monospace, monospace; }}
  .sub {{ padding: 0 24px; font-size: 12px; color: #94A3B8; }}
  .logo {{ flex: 1; display: flex; align-items: center; justify-content: center; }}
  .footer {{ padding: 0 24px 26px; }}
  .row {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }}
  #status {{ font-size: 12px; color: #CBD5E1; }}
  #pct {{ font-size: 12px; font-weight: 700; color: #22D3EE; font-family: ui-monospace, monospace; }}
  .bar-bg {{ width: 100%; height: 8px; border-radius: 999px; background: #1E293B; overflow: hidden; }}
  #bar-fill {{ width: 20%; height: 100%; border-radius: 999px; background: linear-gradient(90deg, #06B6D4, #10B981); transition: width 0.25s ease; }}
</style>
</head>
<body>
  <div class="card">
    <div class="hdr">
      <div class="title">Nikk Slicer</div>
      <div class="ver">{version}</div>
    </div>
    <div class="sub">{msgs.get("subtitle", "")}</div>
    <div class="logo">{logo_tag}</div>
    <div class="footer">
      <div class="row">
        <div id="status">{msgs.get("loading_cfg", "Loading...")}</div>
        <div id="pct">20%</div>
      </div>
      <div class="bar-bg"><div id="bar-fill"></div></div>
    </div>
  </div>
  <script>
    window.__setSplashProgress = function(p, txt) {{
      var fill = document.getElementById('bar-fill');
      var pct = document.getElementById('pct');
      var st = document.getElementById('status');
      if (fill) fill.style.width = p + '%';
      if (pct) pct.textContent = p + '%';
      if (st && txt) st.textContent = txt;
    }};
  </script>
</body>
</html>"""


def _run_macos_with_splash(
    logger: logging.Logger,
    initial_project_id: str | None,
    version: str = "v1.3.0",
) -> int:
    """Muestra splash instantáneo nativo con pywebview en el hilo principal de macOS mientras arranca uvicorn."""
    _configure_macos_app_identity(logger)
    _install_macos_open_file_handler(logger)
    import webview  # type: ignore[import-not-found]

    lang = _detect_splash_lang()
    msgs = _SplashScreen._MESSAGES.get(lang, _SplashScreen._MESSAGES["es"])
    logo_path = None
    for cand in (PROJECT_ROOT / "frontend" / "public" / "nikk-logo.jpg", PROJECT_ROOT / "nikk-logo.jpg"):
        if cand.is_file():
            logo_path = cand
            break

    splash_win = webview.create_window(
        "Nikk Slicer",
        html=_build_macos_splash_html(logo_path, version, msgs),
        width=420,
        height=460,
        resizable=False,
        frameless=True,
        on_top=True,
        background_color="#0B1120",
    )
    _set_macos_dock_icon(logger)

    state: dict[str, Any] = {"server": None, "server_thread": None, "exit_code": 0}

    def _set_p(pct: int, key: str) -> None:
        txt = msgs.get(key, key).replace("'", "\\'")
        try:
            if splash_win is not None:
                splash_win.evaluate_js(f"window.__setSplashProgress && window.__setSplashProgress({pct}, '{txt}')")
        except Exception:
            pass

    def _bootstrap(s_win=None):
        try:
            _set_p(25, "loading_cfg")
            reused_existing = False
            _set_p(50, "starting_engine")
            if is_port_open(LOCAL_HOST, PORT):
                if check_nikkslicer_health():
                    logger.info("Instancia previa saludable de Nikk Slicer detectada en %s; reutilizando.", BASE_URL)
                    reused_existing = True
                else:
                    cleanup_stale_port(PORT, logger)

            if not reused_existing:
                srv, srv_thr = start_embedded_uvicorn(logger)
                state["server"] = srv
                state["server_thread"] = srv_thr
                if not wait_for_backend(timeout_sec=25.0):
                    logger.error("Timeout esperando disponibilidad de %s", HEALTH_URL)
                    state["exit_code"] = 1
                    if s_win is not None:
                        s_win.destroy()
                    return

            _set_p(85, "preparing_ws")
            wsid, url = _build_window_url(initial_project_id)
            main_win = webview.create_window(
                "Nikk Slicer",
                url,
                width=1440,
                height=920,
                min_size=(1100, 720),
                maximized=True,
                background_color="#020617",
                js_api=DesktopApi(),
            )
            if main_win is not None:
                _register_window(wsid, main_win)

            closed_splash = threading.Event()

            def _close_splash() -> None:
                if closed_splash.is_set():
                    return
                closed_splash.set()
                _set_p(100, "ready")
                time.sleep(0.18)
                try:
                    if main_win is not None:
                        main_win.maximize()
                except Exception:
                    pass
                try:
                    if s_win is not None:
                        s_win.destroy()
                except Exception:
                    pass
                _install_macos_archivo_menu(logger)

            if main_win is not None:
                try:
                    main_win.events.loaded += lambda: threading.Thread(target=_close_splash, daemon=True).start()
                except Exception:
                    pass
            time.sleep(0.6)
            if not closed_splash.is_set():
                _close_splash()
        except Exception as exc:
            logger.exception("Error en arranque macOS con splash: %s", exc)
            state["exit_code"] = 1
            try:
                if s_win is not None:
                    s_win.destroy()
            except Exception:
                pass

    webview.start(func=_bootstrap, args=(splash_win,))
    srv = state.get("server")
    srv_thr = state.get("server_thread")
    if srv is not None and srv_thr is not None:
        logger.info("Ventana cerrada: deteniendo uvicorn...")
        srv.should_exit = True
        srv_thr.join(timeout=1.2)
        logger.info("Nikk Slicer detenido correctamente.")
        os._exit(0)
    return int(state.get("exit_code", 0))


def main() -> int:
    logger = setup_logging()
    logger.info("=== Iniciando Nikk Slicer Desktop Launcher ===")

    initial_project_id: str | None = None
    for arg in sys.argv[1:]:
        if arg.startswith("--project-id="):
            initial_project_id = arg.split("=", 1)[1].strip() or None
        elif not arg.startswith("-"):
            _queue_open_file(arg, logger)

    if IS_MACOS:
        return _run_macos_with_splash(logger, initial_project_id=initial_project_id, version="v1.3.0")

    splash = _SplashScreen(version="v1.3.0")
    splash.start()
    splash.set_progress(20, "loading_cfg")

    reused_existing = False
    server = None
    server_thread = None

    splash.set_progress(50, "starting_engine")
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
            splash.close()
            if server is not None:
                server.should_exit = True
            return 1

    splash.set_progress(80, "preparing_ws")
    try:
        open_desktop_window(logger, initial_project_id=initial_project_id, splash=splash)
    finally:
        splash.close()
        if server is not None and server_thread is not None:
            logger.info("Ventana cerrada: deteniendo uvicorn...")
            server.should_exit = True
            server_thread.join(timeout=1.2)
            logger.info("Nikk Slicer detenido correctamente.")
            os._exit(0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
