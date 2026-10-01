"""Коллекция голосов персонажей из папки voices/.

Каждый голос — подпапка:
    voices/arthas/ref.wav     10–15 секунд чистой речи персонажа
    voices/arthas/ref.txt     точная расшифровка ref.wav (нужна F5-TTS)
    voices/arthas/voice.toml  необязательно: name, weight, speed, enabled
"""

from __future__ import annotations

import hashlib
import logging
import random
import tomllib
from collections import deque
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Voice:
    id: str
    name: str
    ref_wav: Path
    ref_text: str
    weight: float = 1.0
    speed: float = 1.0


def load_voices(directory: Path) -> list[Voice]:
    voices = []
    if not directory.is_dir():
        return voices
    for d in sorted(p for p in directory.iterdir() if p.is_dir()):
        wav = d / "ref.wav"
        if not wav.exists():
            log.warning("Голос %s пропущен: нет ref.wav", d.name)
            continue
        meta = {}
        if (d / "voice.toml").exists():
            with (d / "voice.toml").open("rb") as f:
                meta = tomllib.load(f)
        if not meta.get("enabled", True):
            continue
        txt = d / "ref.txt"
        voices.append(
            Voice(
                id=d.name,
                name=meta.get("name", d.name),
                ref_wav=wav,
                ref_text=txt.read_text(encoding="utf-8").strip() if txt.exists() else "",
                weight=float(meta.get("weight", 1.0)),
                speed=float(meta.get("speed", 1.0)),
            )
        )
    return voices


class VoicePicker:
    def __init__(self, voices: list[Voice], avoid_repeat: int = 2,
                 moderator_mode: str = "fixed", moderator_voices: dict[str, str] | None = None,
                 rng: random.Random | None = None):
        if not voices:
            raise ValueError("Нет ни одного голоса в папке voices/ (см. voices/README.md)")
        self.voices = voices
        self.by_id = {v.id: v for v in voices}
        self.recent: deque[str] = deque(maxlen=max(0, min(avoid_repeat, len(voices) - 1)))
        self.moderator_mode = moderator_mode
        self.moderator_voices = moderator_voices or {}
        self.rng = rng or random.Random()
        for login, vid in self.moderator_voices.items():
            if vid not in self.by_id:
                log.warning("Голос %r для модератора %s не найден", vid, login)

    def random_voice(self) -> Voice:
        pool = [v for v in self.voices if v.id not in self.recent] or self.voices
        voice = self.rng.choices(pool, weights=[v.weight for v in pool])[0]
        self.recent.append(voice.id)
        return voice

    def for_moderator(self, login: str) -> Voice:
        pinned = self.by_id.get(self.moderator_voices.get(login, ""))
        if pinned:
            return pinned
        if self.moderator_mode == "fixed":
            # Стабильный голос по нику: один и тот же модератор всегда звучит одинаково.
            h = int(hashlib.sha1(login.encode()).hexdigest(), 16)
            return self.voices[h % len(self.voices)]
        return self.random_voice()
