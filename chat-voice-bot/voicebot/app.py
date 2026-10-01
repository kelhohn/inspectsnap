"""Ядро бота: чат → фильтр → очередь → синтез → воспроизведение."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np

from .audio import DevicePlayer, prepare
from .config import Config
from .engines import Engine
from .catchphrases import Catchphrases, choose
from .filters import decide, parse_command
from .twitch_irc import ChatMessage, Moderation
from .voices import Voice, VoicePicker

log = logging.getLogger(__name__)

PRIORITY = {"moderator": 0, "broadcaster": 0, "vip": 0, "first": 1}
REASON_LABEL = {"moderator": "модератор", "broadcaster": "стример", "first": "первое сообщение", "vip": "VIP"}


@dataclass
class Item:
    id: str
    login: str
    display_name: str
    text: str
    voice: Voice
    reason: str
    message_id: str = ""
    created: float = field(default_factory=time.monotonic)
    cancelled: bool = False
    audio: np.ndarray | None = None

    @property
    def priority(self) -> int:
        return PRIORITY.get(self.reason, 3)

    def public(self) -> dict:
        return {"id": self.id, "user": self.display_name, "text": self.text,
                "voice": self.voice.name, "reason": REASON_LABEL.get(self.reason, self.reason)}


class VoiceBot:
    def __init__(self, cfg: Config, engine: Engine, picker: VoicePicker, overlay=None, chat=None,
                 catchphrases: Catchphrases | None = None):
        self.cfg = cfg
        self.catchphrases = catchphrases or Catchphrases()
        self.engine = engine
        self.picker = picker
        self.overlay = overlay
        self.chat = chat
        self.player = DevicePlayer(cfg.audio.device, cfg.audio.sample_rate) if cfg.audio.output == "device" else None
        if cfg.audio.output == "overlay" and overlay is None:
            raise ValueError("audio.output = \"overlay\" требует [overlay] enabled = true")
        self.volume = cfg.audio.volume
        self._speakers: DevicePlayer | bool | None = None  # запасной вывод в колонки для overlay-режима
        self.paused = False
        self.pending: list[Item] = []
        self.ready: asyncio.Queue[Item] = asyncio.Queue(maxsize=1)
        self.current: Item | None = None
        self.synthesizing: Item | None = None
        self.waiting: Item | None = None  # готово, ждёт снятия паузы
        self._stop_current = asyncio.Event()
        self._resumed = asyncio.Event()
        self._resumed.set()
        self._changed = asyncio.Event()
        self._ids = itertools.count(1)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tts")

    # ---------- входящие события ----------

    async def handle_event(self, event: ChatMessage | Moderation) -> None:
        if isinstance(event, Moderation):
            self.moderate(event)
            return
        tags = "".join(t for t, on in (("[стример]", event.is_broadcaster), ("[мод]", event.is_moderator),
                                       ("[VIP]", event.is_vip), ("[ФМ]", event.first_message)) if on)
        log.info("Чат %s%s: %s", event.display_name, tags, event.text)
        cmd = parse_command(event, self.cfg.filters)
        if cmd is not None:
            reply = await self.run_command(cmd.name, cmd.arg)
            log.info("Команда %s от %s: %s", cmd.name, event.login, reply)
            if reply and self.chat is not None:
                await self.chat.say(f"@{event.display_name} {reply}")
            return
        decision = decide(event, self.cfg.filters)
        if not decision.speak:
            if event.first_message or event.text.lstrip().lower().startswith(self.cfg.filters.tts_command.lower()):
                log.info("Пропуск %s (%s): %s", event.login, decision.reason, event.text)
            return
        text = decision.text
        if decision.reason in ("moderator", "broadcaster", "vip"):
            # «!tts брайер», «!tts брайер: текст», «!tts фраза» — выбор персонажа/реплики.
            chosen, text = choose(text, self.catchphrases)
            voice = self.picker.by_id[chosen] if chosen else self.picker.for_role(event.login, decision.reason)
        else:
            voice = self.picker.random_voice()
        self.enqueue(Item(id=str(next(self._ids)), login=event.login, display_name=event.display_name,
                          text=text, voice=voice, reason=decision.reason, message_id=event.id))

    def enqueue(self, item: Item) -> bool:
        if len(self.pending) >= self.cfg.queue.max_size:
            # Очередь полна: модератор вытесняет самое новое сообщение зрителя, зрителя просто пропускаем.
            victims = [i for i in self.pending if i.priority > item.priority]
            if not victims:
                log.info("Очередь полна, пропуск: %s", item.text)
                return False
            self.pending.remove(max(victims, key=lambda i: (i.priority, i.created)))
        self.pending.append(item)
        self.pending.sort(key=lambda i: (i.priority, i.created))
        log.info("В очередь [%s → %s]: %s", item.display_name, item.voice.name, item.text)
        self._changed.set()
        asyncio.ensure_future(self._push_state())
        return True

    def moderate(self, m: Moderation) -> None:
        def hit(i: Item) -> bool:
            return m.clear_all or (m.message_id and i.message_id == m.message_id) or \
                (not m.message_id and m.login and i.login == m.login)

        removed = [i for i in self.pending if hit(i)]
        for i in removed:
            self.pending.remove(i)
        for i in self._in_flight():
            if hit(i):
                i.cancelled = True
        if self.current and hit(self.current):
            self._stop_current.set()
        if removed or (self.current and hit(self.current)):
            log.info("Модерация: убрано из озвучки (%s)", m)
        asyncio.ensure_future(self._push_state())

    async def run_command(self, name: str, arg: str = "") -> str:
        if name == "skip":
            self._stop_current.set()
            return "пропущено"
        if name == "pause":
            self.paused = True
            self._resumed.clear()
            self._stop_current.set()
            reply = "озвучка на паузе"
        elif name == "resume":
            self.paused = False
            self._resumed.set()
            reply = "озвучка включена"
        elif name == "clear":
            self.pending.clear()
            for i in self._in_flight():
                i.cancelled = True
            self._stop_current.set()
            reply = "очередь очищена"
        elif name == "volume":
            try:
                self.volume = max(0.0, min(1.0, float(arg.replace("%", "")) / 100))
                reply = f"громкость {round(self.volume * 100)}%"
            except ValueError:
                return f"громкость {round(self.volume * 100)}% (пример: !tts volume 60)"
        elif name == "voices":
            return "голоса: " + ", ".join(v.name for v in self.picker.voices)
        elif name == "say":
            # Тестовое сообщение из панели управления — как будто ФМ от зрителя.
            text = arg.strip()
            if not text:
                return "пустой текст"
            msg = ChatMessage(id="", login="test", display_name="Тест", text=text,
                              first_message=True, is_moderator=False, is_broadcaster=False, is_vip=False)
            await self.handle_event(msg)
            return "добавлено"
        else:
            return f"неизвестная команда {name}"
        await self._push_state()
        return reply

    # ---------- конвейер ----------

    def _in_flight(self) -> list[Item]:
        """Уже взятые из очереди, но ещё не играющие: синтезируется + готово к показу."""
        items = list(self.ready._queue)  # type: ignore[attr-defined]
        items += [i for i in (self.synthesizing, self.waiting) if i is not None]
        return items

    async def run(self) -> None:
        await asyncio.gather(self._synth_loop(), self._play_loop())

    async def _next_due(self) -> Item:
        while True:
            self._changed.clear()
            if self.pending:
                item = self.pending[0]
                wait = item.created + self.cfg.queue.delay_seconds - time.monotonic()
                if wait <= 0:
                    self.pending.pop(0)
                    return item
            else:
                wait = None
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass

    async def _synth_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            item = await self._next_due()
            t0 = time.perf_counter()
            self.synthesizing = item
            try:
                wav, sr = await loop.run_in_executor(self._executor, self.engine.synth, item.text, item.voice)
            except Exception:  # noqa: BLE001 — одна неудачная фраза не должна ронять бота
                log.exception("Ошибка синтеза для %r голосом %s", item.text, item.voice.id)
                continue
            finally:
                self.synthesizing = None
            item.audio = prepare(wav, sr, self.cfg.audio.sample_rate)
            log.info("Синтез %.2f с (%s, %.1f с звука)", time.perf_counter() - t0, item.voice.name,
                     item.audio.size / self.cfg.audio.sample_rate)
            if not item.cancelled:
                await self.ready.put(item)

    async def _play_loop(self) -> None:
        while True:
            item = await self.ready.get()
            self.waiting = item
            await self._resumed.wait()
            self.waiting = None
            if item.cancelled or item.audio is None:
                continue
            self.current = item
            self._stop_current.clear()
            await self._broadcast({"type": "speak", **item.public()})
            try:
                player = self.player or self._fallback_player()
                if player is not None:
                    await player.play(item.audio, self.volume, self._stop_current)
                elif self.overlay is not None:
                    await self.overlay.play(item.id, item.audio, self.volume, self._stop_current)
            except Exception:  # noqa: BLE001
                log.exception("Ошибка воспроизведения")
            self.current = None
            await self._broadcast({"type": "done", "id": item.id})
            await self._push_state()
            await asyncio.sleep(self.cfg.queue.gap_seconds)

    def _fallback_player(self) -> DevicePlayer | None:
        """output = "overlay", но оверлей нигде не открыт — играем в колонки, чтобы звук не пропал."""
        if self.overlay is None or getattr(self.overlay, "overlay_clients", 1) > 0:
            return None
        if self._speakers is None:
            try:
                self._speakers = DevicePlayer(None, self.cfg.audio.sample_rate)
            except Exception:  # noqa: BLE001 — нет звуковой библиотеки/устройства
                self._speakers = False
                log.exception("Не удалось открыть колонки")
            else:
                log.warning("Оверлей не открыт ни в OBS, ни в браузере — играю в колонки. "
                            "Чтобы всегда так, поставьте в config.toml: output = \"device\"")
        return self._speakers or None

    # ---------- состояние для панели ----------

    def state(self) -> dict:
        return {
            "paused": self.paused,
            "volume": round(self.volume * 100),
            "engine": self.engine.name,
            "current": self.current.public() if self.current else None,
            "queue": [i.public() for i in self.pending],
            "voices": [v.name for v in self.picker.voices],
        }

    async def _push_state(self) -> None:
        await self._broadcast({"type": "state", **self.state()})

    async def _broadcast(self, event: dict) -> None:
        if self.overlay is not None:
            await self.overlay.broadcast(event)
