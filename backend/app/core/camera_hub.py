"""Hub de cámara MJPEG con conexión única por impresora para evitar saturar :8080 (Creator 5 Pro)."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

logger = logging.getLogger("slicerhub.camera_hub")


@dataclass
class _CameraChannel:
    camera_url: str
    latest_jpeg: bytes | None = None
    latest_ts: float = 0.0
    frame_seq: int = 0
    subscribers: int = 0
    last_subscriber_ts: float = 0.0
    task: asyncio.Task[None] | None = None
    force_reconnect_event: asyncio.Event = field(default_factory=asyncio.Event)
    frame_cond: asyncio.Condition = field(default_factory=asyncio.Condition)


class CameraHub:
    """Mantiene como máximo 1 conexión upstream por URL de cámara y comparte frames en RAM."""

    def __init__(self) -> None:
        self._channels: dict[str, _CameraChannel] = {}

    def _get_or_create(self, camera_url: str) -> _CameraChannel:
        ch = self._channels.get(camera_url)
        if ch is None:
            ch = _CameraChannel(camera_url=camera_url)
            self._channels[camera_url] = ch
        return ch

    def get_recent_frame(self, camera_url: str, max_age_sec: float = 5.0) -> bytes | None:
        """Devuelve el último JPEG en RAM si está vigente (evita abrir otro socket a la impresora)."""
        ch = self._channels.get(camera_url)
        if ch is None or not ch.latest_jpeg:
            return None
        if (time.time() - ch.latest_ts) <= max_age_sec:
            return ch.latest_jpeg
        return None

    async def force_reconnect(self, camera_url: str) -> None:
        """Fuerza el cierre de la conexión upstream actual para reconectar limpio."""
        ch = self._channels.get(camera_url)
        if ch is None:
            return
        ch.latest_jpeg = None
        ch.latest_ts = 0.0
        ch.force_reconnect_event.set()
        if ch.task is not None and not ch.task.done():
            ch.task.cancel()
            try:
                await ch.task
            except BaseException:
                pass
            ch.task = None
        ch.force_reconnect_event.clear()

    def _ensure_worker(self, ch: _CameraChannel) -> None:
        if ch.task is None or ch.task.done():
            ch.task = asyncio.create_task(self._upstream_loop(ch))

    async def _publish_frame(self, ch: _CameraChannel, jpg: bytes) -> None:
        ch.latest_jpeg = jpg
        ch.latest_ts = time.time()
        ch.frame_seq += 1
        async with ch.frame_cond:
            ch.frame_cond.notify_all()

    async def _upstream_loop(self, ch: _CameraChannel) -> None:
        timeout = httpx.Timeout(connect=3.5, read=6.0, write=3.0, pool=3.0)
        try:
            while ch.subscribers > 0 or (time.time() - ch.last_subscriber_ts) < 8.0:
                if ch.force_reconnect_event.is_set():
                    ch.force_reconnect_event.clear()
                    await asyncio.sleep(0.25)
                try:
                    async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                        async with client.stream("GET", ch.camera_url) as resp:
                            if resp.status_code >= 400:
                                await asyncio.sleep(1.5)
                                continue
                            buf = bytearray()
                            async for chunk in resp.aiter_bytes(chunk_size=16384):
                                if ch.subscribers <= 0 and (time.time() - ch.last_subscriber_ts) >= 8.0:
                                    return
                                if ch.force_reconnect_event.is_set():
                                    break
                                if not chunk:
                                    continue
                                buf.extend(chunk)
                                # Extraer todos los frames JPEG completos del buffer
                                while True:
                                    soi = buf.find(b"\xff\xd8")
                                    if soi < 0:
                                        if len(buf) > 131072:
                                            del buf[:-4096]
                                        break
                                    eoi = buf.find(b"\xff\xd9", soi + 2)
                                    if eoi < 0:
                                        if soi > 0:
                                            del buf[:soi]
                                        if len(buf) > 2_000_000:
                                            buf.clear()
                                        break
                                    jpg = bytes(buf[soi : eoi + 2])
                                    del buf[: eoi + 2]
                                    if len(jpg) > 512:
                                        await self._publish_frame(ch, jpg)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.debug("Stream cámara %s interrumpido (%s), reintentando...", ch.camera_url, type(exc).__name__)
                    await asyncio.sleep(1.2)
        except asyncio.CancelledError:
            pass

    async def stream_mjpeg(self, camera_url: str) -> AsyncIterator[bytes]:
        """Genera un stream `multipart/x-mixed-replace` para el visor UI sin abrir múltiples sockets a la impresora."""
        ch = self._get_or_create(camera_url)
        ch.subscribers += 1
        ch.last_subscriber_ts = time.time()
        self._ensure_worker(ch)
        last_seq = -1
        try:
            while True:
                if ch.latest_jpeg and ch.frame_seq != last_seq:
                    last_seq = ch.frame_seq
                    jpg = ch.latest_jpeg
                    header = (
                        f"--frame\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpg)}\r\n\r\n"
                    ).encode("ascii")
                    yield header + jpg + b"\r\n"
                    continue
                async with ch.frame_cond:
                    try:
                        await asyncio.wait_for(ch.frame_cond.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        # Mantener vivo el stream o salir si no hay señal tras espera
                        if not ch.latest_jpeg:
                            break
        finally:
            ch.subscribers = max(0, ch.subscribers - 1)
            ch.last_subscriber_ts = time.time()


camera_hub = CameraHub()
