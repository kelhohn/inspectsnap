"""Локальный веб-сервер: оверлей для OBS (субтитры + звук) и панель управления."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict
from pathlib import Path
from typing import Awaitable, Callable

import numpy as np
from aiohttp import WSMsgType, web

from .audio import to_wav_bytes

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


class OverlayServer:
    def __init__(self, host: str, port: int, sample_rate: int,
                 on_command: Callable[[str, str], Awaitable[str]],
                 get_state: Callable[[], dict]):
        self.host, self.port, self.sr = host, port, sample_rate
        self.on_command = on_command
        self.get_state = get_state
        self.clients: set[web.WebSocketResponse] = set()
        self.clips: OrderedDict[str, bytes] = OrderedDict()
        self._runner: web.AppRunner | None = None

    @property
    def overlay_clients(self) -> int:
        return sum(1 for ws in self.clients if getattr(ws, "_role", "") == "overlay")

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/", lambda r: web.FileResponse(STATIC / "panel.html"))
        app.router.add_get("/overlay", lambda r: web.FileResponse(STATIC / "overlay.html"))
        app.router.add_get("/ws", self._ws)
        app.router.add_get("/audio/{id}.wav", self._audio)
        app.router.add_get("/api/state", lambda r: web.json_response(self.get_state()))
        app.router.add_post("/api/{cmd}", self._api)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()
        log.info("Панель: http://%s:%d/   Оверлей для OBS: http://%s:%d/overlay",
                 self.host, self.port, self.host, self.port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        ws._role = request.query.get("role", "panel")  # type: ignore[attr-defined]
        self.clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            self.clients.discard(ws)
        return ws

    async def _audio(self, request: web.Request) -> web.Response:
        data = self.clips.get(request.match_info["id"])
        if data is None:
            raise web.HTTPNotFound()
        return web.Response(body=data, content_type="audio/wav")

    async def _api(self, request: web.Request) -> web.Response:
        arg = ""
        if request.can_read_body:
            try:
                arg = str((await request.json()).get("arg", ""))
            except (json.JSONDecodeError, AttributeError):
                pass
        result = await self.on_command(request.match_info["cmd"], arg)
        return web.json_response({"result": result, "state": self.get_state()})

    async def broadcast(self, event: dict) -> None:
        data = json.dumps(event, ensure_ascii=False)
        for ws in list(self.clients):
            try:
                await ws.send_str(data)
            except ConnectionError:
                self.clients.discard(ws)

    def add_clip(self, clip_id: str, wav: np.ndarray) -> str:
        self.clips[clip_id] = to_wav_bytes(wav, self.sr)
        while len(self.clips) > 20:
            self.clips.popitem(last=False)
        return f"/audio/{clip_id}.wav"

    async def play(self, clip_id: str, wav: np.ndarray, volume: float, stop: asyncio.Event) -> None:
        """Звук играет страница оверлея в OBS; здесь ждём конца клипа или команды skip."""
        if self.overlay_clients == 0:
            log.warning("Оверлей не открыт ни в OBS, ни в браузере — звук никто не услышит")
        url = self.add_clip(clip_id, wav)
        await self.broadcast({"type": "audio", "id": clip_id, "url": url, "volume": volume})
        try:
            await asyncio.wait_for(stop.wait(), timeout=wav.size / self.sr + 0.3)
            await self.broadcast({"type": "stop", "id": clip_id})
        except asyncio.TimeoutError:
            pass
