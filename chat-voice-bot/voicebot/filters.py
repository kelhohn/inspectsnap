"""Что озвучивать и как подготовить текст к озвучке."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import FilterConfig
from .twitch_irc import ChatMessage

_URL = re.compile(r"(https?://\S+|www\.\S+|\b\S+\.(?:com|ru|net|org|tv|gg|io|me|su|рф)\b\S*)", re.IGNORECASE)
_MENTION = re.compile(r"@(\w+)")
_REPEAT_CHARS = re.compile(r"(.)\1{3,}")
_REPEAT_WORDS = re.compile(r"\b(\w+)(?:\s+\1\b){2,}", re.IGNORECASE)
_SPACES = re.compile(r"\s+")
_LETTERS = re.compile(r"[a-zа-яё]", re.IGNORECASE)


@dataclass
class Decision:
    speak: bool
    reason: str  # "first" | "moderator" | "broadcaster" | "vip" | почему пропущено
    text: str = ""


def clean_text(text: str, max_chars: int) -> str:
    text = _URL.sub(" ссылка ", text)
    text = _MENTION.sub(r"\1", text)
    text = _REPEAT_CHARS.sub(r"\1\1\1", text)
    text = _REPEAT_WORDS.sub(r"\1 \1", text)
    text = _SPACES.sub(" ", text).strip()
    if len(text) > max_chars:
        cut = text[:max_chars]
        space = cut.rfind(" ")
        text = (cut[:space] if space > max_chars // 2 else cut).rstrip(" ,.;:-") + "…"
    return text


def contains_banned(text: str, banned: list[str]) -> bool:
    low = text.lower().replace("ё", "е")
    return any(w and w.lower().replace("ё", "е") in low for w in banned)


def decide(msg: ChatMessage, cfg: FilterConfig) -> Decision:
    if msg.login in cfg.ignore_users:
        return Decision(False, "игнор-лист")

    reason = ""
    text = msg.text.strip()
    if msg.is_broadcaster:
        if cfg.voice_broadcaster:
            reason = "broadcaster"
    elif msg.is_moderator and cfg.voice_moderators:
        if cfg.moderator_prefix:
            if text.startswith(cfg.moderator_prefix):
                text = text[len(cfg.moderator_prefix):].strip()
                reason = "moderator"
        else:
            reason = "moderator"
    if not reason and msg.first_message and cfg.voice_first_messages:
        reason = "first"
    if not reason and msg.is_vip and cfg.voice_vips:
        reason = "vip"
    if not reason:
        return Decision(False, "не ФМ и не модератор")

    if text.startswith("!"):
        return Decision(False, "команда бота")
    if contains_banned(text, cfg.banned_words):
        return Decision(False, "запрещённое слово")
    text = clean_text(text, cfg.max_chars)
    if len(_LETTERS.findall(text)) < cfg.min_chars:
        return Decision(False, "нечего озвучивать (эмоуты/символы)")
    return Decision(True, reason, text)


@dataclass
class Command:
    name: str  # skip | pause | resume | clear | volume | voices
    arg: str = ""


_ALIASES = {
    "skip": "skip", "s": "skip", "скип": "skip",
    "stop": "pause", "pause": "pause", "стоп": "pause",
    "start": "resume", "resume": "resume", "старт": "resume",
    "clear": "clear", "очистить": "clear",
    "volume": "volume", "vol": "volume", "громкость": "volume",
    "voices": "voices", "голоса": "voices",
}


def parse_command(msg: ChatMessage) -> Command | None:
    """!tts <команда> — только для модераторов и стримера."""
    if not (msg.is_moderator or msg.is_broadcaster):
        return None
    parts = msg.text.strip().split()
    if len(parts) < 2 or parts[0].lower() not in ("!tts", "!озвучка"):
        return None
    name = _ALIASES.get(parts[1].lower())
    if name is None:
        return None
    return Command(name, " ".join(parts[2:]))
