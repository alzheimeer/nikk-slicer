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
        target = win.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=suggested_name,
        )
        if not target:
            return {"saved": False, "cancelled": True}
        dest = Path(target[0] if isinstance(target, (list, tuple)) else target)
        with urllib.request.urlopen(url, timeout=45) as resp:
            dest.write_bytes(resp.read())
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
            background_color="#020617",
            js_api=DesktopApi(),
        )
        if win is not None:
            _register_window(wsid, win)
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


def open_desktop_window(logger: logging.Logger, initial_project_id: str | None = None) -> None:
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
            background_color="#020617",
            js_api=DesktopApi(),
        )
        if main_win is not None:
            _register_window(wsid, main_win)
        if IS_MACOS:
            _set_macos_dock_icon(logger)

        def _on_webview_ready():
            time.sleep(0.35)
            if IS_MACOS:
                _install_macos_archivo_menu(logger)

        start_kwargs: dict[str, object] = {"func": _on_webview_ready}
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


def main() -> int:
    logger = setup_logging()
    logger.info("=== Iniciando Nikk Slicer Desktop Launcher ===")

    initial_project_id: str | None = None
    for arg in sys.argv[1:]:
        if arg.startswith("--project-id="):
            initial_project_id = arg.split("=", 1)[1].strip() or None
        elif not arg.startswith("-"):
            _queue_open_file(arg, logger)

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
        open_desktop_window(logger, initial_project_id=initial_project_id)
    finally:
        if server is not None and server_thread is not None:
            logger.info("Ventana cerrada: deteniendo uvicorn...")
            server.should_exit = True
            server_thread.join(timeout=1.2)
            logger.info("Nikk Slicer detenido correctamente.")
            os._exit(0)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
