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
    voice_first_messages: bool = True
    voice_moderators: bool = True
    voice_broadcaster: bool = False
    voice_vips: bool = False
    # Если задан (например "~"), модераторов озвучиваем только когда сообщение начинается с префикса.
    moderator_prefix: str = ""
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
    moderator_voices: dict[str, str] = field(default_factory=dict)


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
    # "device" — звуковое устройство (VB-CABLE/колонки); "overlay" — звук играет страница-оверлей в OBS.
    output: str = "overlay"
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
        section = raw.get(name, {})
        known = cls.__dataclass_fields__
        unknown = set(section) - set(known)
        if unknown:
            raise ValueError(f"[{name}]: неизвестные параметры {sorted(unknown)}")
        setattr(cfg, name, cls(**section))
    cfg.twitch.channel = cfg.twitch.channel.lstrip("#").lower()
    cfg.voices.moderator_voices = {k.lower(): v for k, v in cfg.voices.moderator_voices.items()}
    cfg.filters.ignore_users = [u.lower() for u in cfg.filters.ignore_users]
    return cfg
