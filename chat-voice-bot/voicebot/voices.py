"""Коллекция голосов персонажей из папки voices/.

Каждый голос — подпапка:
    voices/arthas/ref.wav     10–15 секунд чистой речи персонажа
    voices/arthas/ref.txt     точная расшифровка ref.wav (нужна F5-TTS)
    voices/arthas/ref2.wav    необязательно: ещё образцы (ref2, ref3, …) — например спокойный и кричащий;
    voices/arthas/ref2.txt    на каждое сообщение берётся случайный, F5 копирует и его интонацию
    voices/arthas/voice.toml  необязательно: name, weight, speed, enabled
"""

from __future__ import annotations

import hashlib
import logging
import random
import re
import tomllib
from collections import deque
from dataclasses import dataclass, field
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
    extra_refs: list[tuple[Path, str]] = field(default_factory=list)  # ref2.wav, ref3.wav, …
    fish_id: str = ""  # ID голоса в библиотеке Fish Audio (voice.toml: fish_id = "...")

    @property
    def refs(self) -> list[tuple[Path, str]]:
        return [(self.ref_wav, self.ref_text)] + self.extra_refs

    def pick_ref(self, rng: random.Random | None = None) -> tuple[Path, str]:
        return (rng or random).choice(self.refs)


_EXTRA_REF = re.compile(r"^ref(\d+)\.wav$")


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def load_voices(directory: Path) -> list[Voice]:
    voices = []
    if not directory.is_dir():
        return voices
    for d in sorted(p for p in directory.iterdir() if p.is_dir()):
        wav = d / "ref.wav"
        meta = {}
        if (d / "voice.toml").exists():
            with (d / "voice.toml").open("rb") as f:
                meta = tomllib.load(f)
        if not meta.get("enabled", True):
            continue
        if not wav.exists() and not meta.get("fish_id"):
            log.warning("Голос %s пропущен: нет ref.wav (и fish_id в voice.toml)", d.name)
            continue
        extra = sorted((int(m.group(1)), f) for f in d.iterdir() if (m := _EXTRA_REF.match(f.name)))
        voices.append(
            Voice(
                id=d.name,
                name=meta.get("name", d.name),
                ref_wav=wav,
                ref_text=_read_text(d / "ref.txt"),
                weight=float(meta.get("weight", 1.0)),
                speed=float(meta.get("speed", 1.0)),
                extra_refs=[(f, _read_text(f.with_suffix(".txt"))) for _, f in extra],
                fish_id=str(meta.get("fish_id", "")),
            )
        )
    return voices


class VoicePicker:
    def __init__(self, voices: list[Voice], avoid_repeat: int = 2,
                 moderator_mode: str = "fixed", moderator_voices: dict[str, str] | None = None,
                 rng: random.Random | None = None, role_voices: dict[str, str] | None = None):
        if not voices:
            raise ValueError("Нет ни одного голоса в папке voices/ (см. voices/README.md)")
        self.voices = voices
        self.by_id = {v.id: v for v in voices}
        self.recent: deque[str] = deque(maxlen=max(0, min(avoid_repeat, len(voices) - 1)))
        self.moderator_mode = moderator_mode
        self.moderator_voices = moderator_voices or {}
        self.rng = rng or random.Random()
        self.role_voices = {k: v for k, v in (role_voices or {}).items() if v}
        for login, vid in self.moderator_voices.items():
            if vid not in self.by_id:
                log.warning("Голос %r для модератора %s не найден", vid, login)
        for r, vid in self.role_voices.items():
            if vid not in self.by_id:
                log.warning("Голос %r для роли %s не найден в voices/ — будет обычный выбор", vid, r)

    def random_voice(self) -> Voice:
        # Голоса стримера/модеров/VIP не выпадают зрителям — чтобы зритель не звучал как стример.
        reserved = set(self.role_voices.values())
        allowed = [v for v in self.voices if v.id not in reserved] or self.voices
        pool = [v for v in allowed if v.id not in self.recent] or allowed
        voice = self.rng.choices(pool, weights=[v.weight for v in pool])[0]
        self.recent.append(voice.id)
        return voice

    def for_role(self, login: str, role: str) -> Voice:
        """Голос для !tts: ник из moderator_voices → голос роли (стример/модеры/VIP) → как for_moderator."""
        pinned = self.by_id.get(self.moderator_voices.get(login, "")) or self.by_id.get(self.role_voices.get(role, ""))
        return pinned or self.for_moderator(login)

    def for_moderator(self, login: str) -> Voice:
        pinned = self.by_id.get(self.moderator_voices.get(login, ""))
        if pinned:
            return pinned
        if self.moderator_mode == "fixed":
            # Стабильный голос по нику: один и тот же модератор всегда звучит одинаково.
            h = int(hashlib.sha1(login.encode()).hexdigest(), 16)
            return self.voices[h % len(self.voices)]
        return self.random_voice()
