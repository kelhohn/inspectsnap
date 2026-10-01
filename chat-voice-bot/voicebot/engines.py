"""Движки озвучки. Тяжёлые библиотеки импортируются только при выборе движка."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import numpy as np

from .config import EngineConfig
from .voices import Voice

log = logging.getLogger(__name__)


class Engine:
    name = "base"

    def synth(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        """Возвращает (моно float32 [-1..1], частота дискретизации)."""
        raise NotImplementedError


class DummyEngine(Engine):
    """Без нейросетей: пищит мелодией по слогам. Для проверки бота без видеокарты."""

    name = "dummy"

    def synth(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        sr = 24000
        base = 180 + (sum(map(ord, voice.id)) % 7) * 40
        vowels = [c for c in text.lower() if c in "аеёиоуыэюяaeiou"] or ["a"]
        notes = []
        for i, _ in enumerate(vowels[:60]):
            t = np.arange(int(sr * 0.09)) / sr
            f = base * (1.0 + 0.15 * ((i * 7) % 5) / 4)
            notes.append(0.3 * np.sin(2 * np.pi * f * t) * np.hanning(t.size))
            notes.append(np.zeros(int(sr * 0.02)))
        return np.concatenate(notes).astype(np.float32), sr


class Accentuator:
    """Ударения для русского через RUAccent: «прив+ет». Без библиотеки — текст как есть."""

    def __init__(self, device: str):
        try:
            from ruaccent import RUAccent
        except ImportError:
            log.warning("ruaccent не установлен — ударения расставляться не будут")
            self._acc = None
            return
        self._acc = RUAccent()
        self._acc.load(omograph_model_size="turbo2", use_dictionary=True,
                       device="CUDA" if device.startswith("cuda") else "CPU")

    def __call__(self, text: str) -> str:
        return self._acc.process_all(text) if self._acc else text


class F5Engine(Engine):
    name = "f5"

    def __init__(self, cfg: EngineConfig):
        from f5_tts.api import F5TTS

        if not cfg.f5_ckpt_file:
            log.warning("f5_ckpt_file не задан — будет базовая модель F5 (английский/китайский), "
                        "русский будет звучать плохо. См. README.")
        self.cfg = cfg
        self.tts = F5TTS(model=cfg.f5_model, ckpt_file=cfg.f5_ckpt_file,
                         vocab_file=cfg.f5_vocab_file, device=cfg.device)
        self.accent = Accentuator(cfg.device) if cfg.f5_accent else (lambda s: s)
        self._ref_text = lru_cache(maxsize=256)(self.accent)

    def synth(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        ref_text = self._ref_text(voice.ref_text) if voice.ref_text else ""
        wav, sr, _ = self.tts.infer(
            ref_file=str(voice.ref_wav),
            ref_text=ref_text,
            gen_text=self.accent(text),
            nfe_step=self.cfg.f5_nfe_step,
            speed=self.cfg.f5_speed * voice.speed,
            show_info=lambda *a, **k: None,
            progress=None,
        )
        return np.asarray(wav, dtype=np.float32), int(sr)


class XttsEngine(Engine):
    name = "xtts"

    def __init__(self, cfg: EngineConfig):
        # Лицензия модели XTTS-v2 — Coqui Public Model License (некоммерческая).
        os.environ.setdefault("COQUI_TOS_AGREED", "1")
        from TTS.api import TTS

        self.cfg = cfg
        self.tts = TTS(cfg.xtts_model, progress_bar=False).to(cfg.device)
        self.sr = int(self.tts.synthesizer.output_sample_rate)

    def synth(self, text: str, voice: Voice) -> tuple[np.ndarray, int]:
        wav = self.tts.tts(text=text, speaker_wav=str(voice.ref_wav), language=self.cfg.xtts_language,
                           speed=voice.speed)
        return np.asarray(wav, dtype=np.float32), self.sr


def create_engine(cfg: EngineConfig, name: str | None = None) -> Engine:
    name = name or cfg.name
    if name == "f5":
        return F5Engine(cfg)
    if name == "xtts":
        return XttsEngine(cfg)
    if name == "dummy":
        return DummyEngine()
    raise ValueError(f"Неизвестный движок {name!r}: f5 | xtts | dummy")
