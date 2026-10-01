"""Подготовка звука и вывод на звуковое устройство."""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from math import gcd

import numpy as np

try:
    from scipy.signal import resample_poly
except ImportError:  # без scipy — линейная интерполяция
    resample_poly = None

log = logging.getLogger(__name__)


def resample(wav: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    if sr == target_sr or wav.size == 0:
        return wav
    if resample_poly is not None:
        g = gcd(sr, target_sr)
        return resample_poly(wav, target_sr // g, sr // g).astype(np.float32)
    n = int(round(wav.size * target_sr / sr))
    return np.interp(np.linspace(0, wav.size - 1, n), np.arange(wav.size), wav).astype(np.float32)


def normalize(wav: np.ndarray, target_rms: float = 0.1, peak: float = 0.95) -> np.ndarray:
    """Выравнивает громкость, чтобы тихие и громкие персонажи звучали одинаково."""
    if wav.size == 0:
        return wav
    rms = float(np.sqrt(np.mean(wav**2)))
    if rms > 1e-5:
        wav = wav * (target_rms / rms)
    m = float(np.max(np.abs(wav)))
    if m > peak:
        wav = wav * (peak / m)
    return wav.astype(np.float32)


def prepare(wav: np.ndarray, sr: int, target_sr: int) -> np.ndarray:
    wav = np.asarray(wav, dtype=np.float32).reshape(-1)
    pad = np.zeros(int(target_sr * 0.08), dtype=np.float32)
    return np.concatenate([pad, normalize(resample(wav, sr, target_sr)), pad])


def to_wav_bytes(wav: np.ndarray, sr: int) -> bytes:
    pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class DevicePlayer:
    """Играет на звуковое устройство (например, CABLE Input для OBS)."""

    def __init__(self, device: str | int | None, sample_rate: int):
        import sounddevice as sd

        self.sd = sd
        self.sr = sample_rate
        if isinstance(device, str) and device.isdigit():
            device = int(device)
        self.device = device or None
        if self.device is not None:
            info = sd.query_devices(self.device, "output")
            log.info("Звук идёт на устройство: %s", info["name"])

    async def play(self, wav: np.ndarray, volume: float, stop: asyncio.Event) -> None:
        self.sd.play(wav * volume, self.sr, device=self.device)
        duration = wav.size / self.sr
        try:
            await asyncio.wait_for(stop.wait(), timeout=duration + 0.1)
            self.sd.stop()
        except asyncio.TimeoutError:
            pass


def list_devices() -> str:
    import sounddevice as sd

    return str(sd.query_devices())
