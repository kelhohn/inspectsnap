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


def role(msg: ChatMessage) -> str:
    """Старшая роль автора: broadcaster > moderator > vip > ""."""
    if msg.is_broadcaster:
        return "broadcaster"
    if msg.is_moderator:
        return "moderator"
    if msg.is_vip:
        return "vip"
    return ""


def can_use_tts(msg: ChatMessage, cfg: FilterConfig) -> bool:
    return role(msg) in cfg.tts_roles


def strip_tts_command(text: str, cfg: FilterConfig) -> str | None:
    """«!tts привет» → «привет»; не команда — None."""
    head, _, rest = text.strip().partition(" ")
    if head.lower() in (cfg.tts_command.lower(), "!озвучка"):
        return rest.strip()
    return None


def decide(msg: ChatMessage, cfg: FilterConfig) -> Decision:
    if msg.login in cfg.ignore_users:
        return Decision(False, "игнор-лист")

    text = msg.text.strip()
    spoken = strip_tts_command(text, cfg)
    if spoken is not None:
        # !tts текст — озвучка по команде: только VIP, модераторы и владелец канала.
        if not can_use_tts(msg, cfg):
            return Decision(False, f"{cfg.tts_command} только для VIP, модераторов и стримера")
        if not spoken:
            return Decision(False, "пустая команда")
        reason, text = role(msg), spoken
    elif msg.first_message and cfg.voice_first_messages:
        if text.startswith("!"):
            return Decision(False, "команда бота")
        reason = "first"
    else:
        return Decision(False, "не ФМ и не !tts")

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


def parse_command(msg: ChatMessage, cfg: FilterConfig) -> Command | None:
    """Управление: «!tts skip», «!tts громкость 60». Одно служебное слово после !tts —
    команда; всё остальное («!tts стоп, это ограбление») — текст для озвучки."""
    if not can_use_tts(msg, cfg):
        return None
    rest = strip_tts_command(msg.text, cfg)
    if not rest:
        return None
    parts = rest.split()
    name = _ALIASES.get(parts[0].lower())
    if name is None:
        return None
    if name == "volume":
        if len(parts) > 2 or (len(parts) == 2 and not parts[1].rstrip("%").replace(".", "", 1).isdigit()):
            return None
    elif len(parts) > 1:
        return None
    return Command(name, " ".join(parts[1:]))
