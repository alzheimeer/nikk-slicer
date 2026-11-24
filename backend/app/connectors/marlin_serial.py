"""Conector USB Serial (protocolo ping-pong `ok` + `M105`) y Tarjeta SD para Ender 3 S1 Pro (Marlin 2)."""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import serial

from app.models.schemas import PrinterId, PrinterLiveStatus

M105_RE = re.compile(
    r"T:([0-9.]+)(?:\s*/\s*([0-9.]+))?.*?B:([0-9.]+)(?:\s*/\s*([0-9.]+))?",
    re.IGNORECASE,
)


@dataclass
class _SerialState:
    state: str = "idle"
    nozzle_temp: float | None = None
    nozzle_target: float | None = None
    bed_temp: float | None = None
    bed_target: float | None = None
    progress_percent: float = 0.0
    current_file: str | None = None
    last_message: str = "Listo para USB Serial o SD /Volumes/"
    last_error: str | None = None
    paused: bool = False
    cancel_requested: bool = False


class MarlinSerialManager:
    """Gestor en segundo plano con hilo dedicado y bloqueo seguro para Marlin por USB."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = _SerialState()
        self._print_thread: threading.Thread | None = None

    def _parse_temps(self, line: str) -> None:
        m = M105_RE.search(line)
        if not m:
            return
        with self._lock:
            self._state.nozzle_temp = float(m.group(1))
            if m.group(2) is not None:
                self._state.nozzle_target = float(m.group(2))
            self._state.bed_temp = float(m.group(3))
            if m.group(4) is not None:
                self._state.bed_target = float(m.group(4))

    def _poll_m105_once(self, port_path: str, baudrate: int, timeout: float = 1.2) -> bool:
        """Consulta rápida M105 cuando no hay una impresión serial en curso."""
        try:
            with serial.Serial(port_path, baudrate=baudrate, timeout=timeout) as ser:
                ser.reset_input_buffer()
                ser.write(b"M105\n")
                ser.flush()
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    raw = ser.readline().decode("ascii", errors="ignore").strip()
                    if not raw:
                        continue
                    self._parse_temps(raw)
                    if "ok" in raw.lower():
                        return True
        except (serial.SerialException, OSError):
            return False
        return False

    def query_status(
        self,
        printer_id: PrinterId,
        display_name: str,
        cfg: dict[str, Any],
    ) -> PrinterLiveStatus:
        """Retorna telemetría USB Serial (o estado SD si el cable USB está desconectado)."""
        port_path = str(cfg.get("serial_port", "")).strip()
        baudrate = int(cfg.get("baudrate", 115200) or 115200)
        sd_path = str(cfg.get("sd_volume_path", "")).strip()
        camera_url = str(cfg.get("camera_url", "")).strip()
        profile_id = cfg.get("profile_id")
        enabled = bool(cfg.get("enabled", True))

        is_printing_thread = (
            self._print_thread is not None and self._print_thread.is_alive()
        )
        online = False

        if is_printing_thread:
            online = True
        elif port_path and Path(port_path).exists():
            online = self._poll_m105_once(port_path, baudrate, timeout=1.0)

        with self._lock:
            st = self._state
            if is_printing_thread:
                cur_state = "paused" if st.paused else "printing"
                msg = st.last_message
            elif online:
                cur_state = "standby"
                msg = f"Marlin conectado en {port_path} ({baudrate} bps)"
            elif sd_path and Path(sd_path).is_dir():
                cur_state = "sd_ready"
                msg = f"Tarjeta SD montada en {sd_path} (USB sin conexión)"
            else:
                cur_state = "offline"
                msg = (
                    f"Puerto {port_path} no conectado"
                    if port_path
                    else "Sin puerto USB ni tarjeta SD configurada"
                )

            return PrinterLiveStatus(
                printer_id=printer_id,
                profile_id=profile_id,
                display_name=display_name,
                protocol="marlin_serial",
                ip=port_path,
                port=baudrate,
                enabled=enabled,
                online=online,
                state=cur_state,
                nozzle_temp=st.nozzle_temp,
                nozzle_target=st.nozzle_target,
                bed_temp=st.bed_temp,
                bed_target=st.bed_target,
                progress_percent=round(st.progress_percent, 1),
                current_file=st.current_file,
                camera_url=camera_url,
                message=msg,
                error_code=(
                    "MARLIN_ERROR"
                    if (st.state == "error" or st.last_error)
                    else None
                ),
                error_message=st.last_error or (msg if st.state == "error" else None),
            )

    def start_print(self, cfg: dict[str, Any], gcode_path: Path, filename: str) -> str:
        """Inicia transmisión en hilo daemon siguiendo estrictamente `ok` (ping-pong)."""
        port_path = str(cfg.get("serial_port", "")).strip()
        baudrate = int(cfg.get("baudrate", 115200) or 115200)
        if not port_path or not Path(port_path).exists():
            raise RuntimeError(
                f"Puerto USB serial '{port_path}' no disponible en macOS."
            )
        if self._print_thread is not None and self._print_thread.is_alive():
            raise RuntimeError(
                "Ya hay una impresión USB activa en la Ender 3 S1 Pro."
            )

        lines = [
            ln.split(";", 1)[0].strip()
            for ln in gcode_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        ]
        commands = [ln for ln in lines if ln]
        if not commands:
            raise RuntimeError("El archivo G-code no contiene comandos ejecutables.")

        with self._lock:
            self._state = _SerialState(
                state="printing",
                progress_percent=0.0,
                current_file=filename,
                last_message=f"Transmitiendo {len(commands)} líneas vía {port_path}...",
                paused=False,
                cancel_requested=False,
            )

        def _worker() -> None:
            total = len(commands)
            last_m105 = time.monotonic()
            try:
                with serial.Serial(port_path, baudrate=baudrate, timeout=2.0) as ser:
                    time.sleep(1.5)  # Esperar reset DTR típico de placa Marlin
                    ser.reset_input_buffer()

                    for idx, cmd in enumerate(commands, start=1):
                        while True:
                            with self._lock:
                                cancelled = self._state.cancel_requested
                                paused = self._state.paused
                            if cancelled:
                                for stop_cmd in ("M104 S0", "M140 S0", "M107", "M84"):
                                    ser.write(f"{stop_cmd}\n".encode("ascii"))
                                    ser.flush()
                                with self._lock:
                                    self._state.state = "cancelled"
                                    self._state.last_message = "Impresión USB cancelada por usuario."
                                return
                            if not paused:
                                break
                            time.sleep(0.25)

                        # Polling periódico M105 cada ~4s entre comandos
                        now = time.monotonic()
                        if now - last_m105 >= 4.0:
                            last_m105 = now
                            ser.write(b"M105\n")
                            ser.flush()
                            self._wait_ok(ser, timeout=5.0)

                        ser.write(f"{cmd}\n".encode("ascii"))
                        ser.flush()
                        self._wait_ok(ser, timeout=30.0)

                        with self._lock:
                            self._state.progress_percent = (idx / total) * 100.0
                            self._state.last_message = (
                                f"Imprimiendo línea {idx}/{total} ({self._state.progress_percent:.1f}%)"
                            )

                with self._lock:
                    self._state.state = "complete"
                    self._state.progress_percent = 100.0
                    self._state.last_message = f"Finalizado por USB Serial: {filename}"
            except (serial.SerialException, OSError, TimeoutError) as exc:
                with self._lock:
                    self._state.state = "error"
                    self._state.last_message = f"Error serial Marlin: {exc}"

        self._print_thread = threading.Thread(
            target=_worker,
            name="slicerhub-marlin-serial",
            daemon=True,
        )
        self._print_thread.start()
        return f"Impresión USB Serial iniciada en {port_path} ({len(commands)} líneas)."

    def _wait_ok(self, ser: serial.Serial, timeout: float = 15.0) -> None:
        """Espera estricto `ok` del firmware Marlin (protocolo ping-pong)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            raw = ser.readline().decode("ascii", errors="ignore").strip()
            if not raw:
                continue
            self._parse_temps(raw)
            low = raw.lower()
            if low.startswith("error:") or raw.startswith("!!"):
                with self._lock:
                    self._state.last_error = raw
                    self._state.state = "error"
                    self._state.last_message = raw
                raise RuntimeError(raw)
            if "ok" in low:
                return
        raise TimeoutError("Timeout esperando respuesta 'ok' de Marlin.")

    def control(self, action: str) -> str:
        """Pausa, reanuda o cancela la transmisión serial activa."""
        with self._lock:
            if action == "pause":
                self._state.paused = True
                self._state.last_message = "Impresión USB en pausa."
                return "Impresión USB pausada."
            if action == "resume":
                self._state.paused = False
                self._state.last_message = "Reanudando impresión USB..."
                return "Impresión USB reanudada."
            if action == "cancel":
                self._state.cancel_requested = True
                self._state.paused = False
                self._state.last_message = "Cancelando impresión USB..."
                return "Cancelación solicitada a Marlin USB."
        raise ValueError(f"Acción no soportada: {action}")

    def save_to_sd(self, gcode_path: Path, sd_volume_path: str, filename: str) -> Path:
        """Copia el `.gcode` directamente a la tarjeta SD montada en `/Volumes/`."""
        target_dir = Path(sd_volume_path)
        if not sd_volume_path or not target_dir.is_dir():
            raise RuntimeError(
                f"La carpeta o tarjeta SD '{sd_volume_path}' no está montada."
            )
        if not os.access(target_dir, os.W_OK):
            raise RuntimeError(
                f"No hay permiso de escritura en '{sd_volume_path}'."
            )
        dst = target_dir / filename
        shutil.copy2(gcode_path, dst)
        with self._lock:
            self._state.current_file = filename
            self._state.last_message = f"G-code guardado en SD: {dst}"
        return dst


marlin_manager = MarlinSerialManager()
