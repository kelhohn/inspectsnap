"""Загрузка config.toml в простые dataclass-объекты."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TwitchConfig:
    channel: str = ""
    # Пусто = анонимное подключение (только чтение) — для озвучки этого достаточно.
    login: str = ""
    oauth_token: str = ""


@dataclass
class FilterConfig:
    voice_first_messages: bool = True  # автоматически озвучивать первое сообщение зрителя (ФМ)
    # «!tts текст» — озвучка по команде; кому можно: broadcaster, moderator, vip.
    tts_command: str = "!tts"
    tts_roles: list[str] = field(default_factory=lambda: ["broadcaster", "moderator", "vip"])
    max_chars: int = 200
    min_chars: int = 2
    banned_words: list[str] = field(default_factory=list)
    ignore_users: list[str] = field(default_factory=lambda: ["nightbot", "streamelements", "moobot"])


@dataclass
class QueueConfig:
    max_size: int = 15
    # Пауза перед озвучкой — успевает прилететь удаление сообщения или бан.
    delay_seconds: float = 2.0
    gap_seconds: float = 0.4


@dataclass
class VoicesConfig:
    dir: str = "voices"
    # "random" — каждое сообщение случайным голосом; "fixed" — у каждого модератора свой постоянный голос.
    moderator_mode: str = "fixed"
    avoid_repeat: int = 2
    # Постоянный голос по роли для !tts (папка в voices/). Пусто — по moderator_mode.
    broadcaster_voice: str = "illidan"
    moderator_voice: str = "arthas"
    vip_voice: str = ""
    moderator_voices: dict[str, str] = field(default_factory=dict)  # конкретный ник → голос (важнее роли)


@dataclass
class EngineConfig:
    name: str = "f5"  # f5 | xtts | dummy
    device: str = "cuda"
    # F5-TTS
    f5_model: str = "F5TTS_v1_Base"
    f5_ckpt_file: str = ""
    f5_vocab_file: str = ""
    f5_nfe_step: int = 32
    f5_speed: float = 1.0
    f5_accent: bool = True  # расставлять ударения через RUAccent
    # XTTS-v2
    xtts_model: str = "tts_models/multilingual/multi-dataset/xtts_v2"
    xtts_language: str = "ru"


@dataclass
class AudioConfig:
    # "device" — колонки/звуковое устройство; "overlay" — звук играет только страница-оверлей в OBS.
    output: str = "device"
    device: str = ""  # имя или номер устройства для output = "device"
    volume: float = 0.8
    sample_rate: int = 48000


@dataclass
class OverlayConfig:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8790


@dataclass
class Config:
    twitch: TwitchConfig = field(default_factory=TwitchConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    queue: QueueConfig = field(default_factory=QueueConfig)
    voices: VoicesConfig = field(default_factory=VoicesConfig)
    engine: EngineConfig = field(default_factory=EngineConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)
    base_dir: Path = field(default_factory=Path.cwd)

    def path(self, p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else self.base_dir / q


# Параметры старых версий: модеров/VIP теперь озвучивает только !tts.
_DEPRECATED = {"filters": {"voice_moderators", "voice_broadcaster", "voice_vips", "moderator_prefix"}}

_SECTIONS = {
    "twitch": TwitchConfig,
    "filters": FilterConfig,
    "queue": QueueConfig,
    "voices": VoicesConfig,
    "engine": EngineConfig,
    "audio": AudioConfig,
    "overlay": OverlayConfig,
}


def load_config(path: str | Path) -> Config:
    path = Path(path)
    with path.open("rb") as f:
        raw = tomllib.load(f)
    cfg = Config(base_dir=path.resolve().parent)
    for name, cls in _SECTIONS.items():
        section = {k: v for k, v in raw.get(name, {}).items() if k not in _DEPRECATED.get(name, ())}
        known = cls.__dataclass_fields__
        unknown = set(section) - set(known)
        if unknown:
            raise ValueError(f"[{name}]: неизвестные параметры {sorted(unknown)}")
        setattr(cfg, name, cls(**section))
    cfg.twitch.channel = cfg.twitch.channel.lstrip("#").lower()
    cfg.voices.moderator_voices = {k.lower(): v for k, v in cfg.voices.moderator_voices.items()}
    cfg.filters.ignore_users = [u.lower() for u in cfg.filters.ignore_users]
    cfg.filters.tts_roles = [r.lower() for r in cfg.filters.tts_roles]
    bad = set(cfg.filters.tts_roles) - {"broadcaster", "moderator", "vip"}
    if bad:
        raise ValueError(f"[filters] tts_roles: неизвестные роли {sorted(bad)} (можно broadcaster, moderator, vip)")
    return cfg
