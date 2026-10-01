"""Реплики персонажей и выбор голоса по имени в команде !tts.

    !tts брайер          → случайная реплика Брайер её голосом
    !tts брайер: текст   → текст голосом Брайер
    !tts фраза           → случайный персонаж со своей репликой
"""

from __future__ import annotations

import logging
import random
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .voices import Voice

log = logging.getLogger(__name__)

RANDOM_PHRASE_WORDS = {"фраза", "реплика", "phrase"}
_NAMED = re.compile(r"^\s*([^:]{1,40}?)\s*:\s*(.+)$", re.S)


@dataclass
class Catchphrases:
    aliases: dict[str, str] = field(default_factory=dict)       # «брайер» → briar
    phrases: dict[str, list[str]] = field(default_factory=dict)  # briar → [...]


def _norm(s: str) -> str:
    return s.strip().lower().replace("ё", "е")


def load_catchphrases(path: Path, voices: list[Voice]) -> Catchphrases:
    raw: dict = {}
    if path.exists():
        with path.open("rb") as f:
            raw = tomllib.load(f)
    known = {v.id for v in voices}
    cp = Catchphrases()
    for v in voices:  # имя папки, подпись и первое слово подписи — всегда работают
        for a in {v.id, v.name, v.name.split()[0] if v.name.split() else v.name}:
            cp.aliases.setdefault(_norm(a), v.id)
    for vid, entry in raw.items():
        if vid not in known or not isinstance(entry, dict):
            continue
        for a in entry.get("aliases", []):
            cp.aliases[_norm(a)] = vid
        phrases = [p for p in entry.get("phrases", []) if isinstance(p, str) and p.strip()]
        if phrases:
            cp.phrases[vid] = phrases
    return cp


def choose(text: str, cp: Catchphrases, rng: random.Random | None = None,
           exclude: set[str] | None = None) -> tuple[str | None, str]:
    """→ (id голоса или None, текст для озвучки)."""
    rng = rng or random
    key = _norm(text)
    if key in RANDOM_PHRASE_WORDS:
        pool = [vid for vid in cp.phrases if vid not in (exclude or set())] or list(cp.phrases)
        if pool:
            vid = rng.choice(pool)
            return vid, rng.choice(cp.phrases[vid])
        return None, text
    if key in cp.aliases:
        vid = cp.aliases[key]
        if cp.phrases.get(vid):
            return vid, rng.choice(cp.phrases[vid])
        return None, text  # реплик нет — просто озвучиваем слово
    m = _NAMED.match(text)
    if m and _norm(m.group(1)) in cp.aliases:
        return cp.aliases[_norm(m.group(1))], m.group(2).strip()
    return None, text
