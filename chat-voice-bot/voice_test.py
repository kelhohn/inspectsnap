"""Тест A/B: озвучить мемные фразы всеми голосами из voices/ разными движками.

    python voice_test.py                       # f5 и xtts, все голоса
    python voice_test.py --engines f5 --voices arthas spongebob
    python voice_test.py --phrases "Привет, чат!" "Это мой первый месседж"

Результат: out/<движок>/<голос>_<N>.wav + время синтеза в консоли.
"""

from __future__ import annotations

import voicebot.compat  # noqa: F401 — до torch: прячет сломанный torchcodec
import argparse
import gc
import time
from pathlib import Path

import numpy as np

from voicebot.audio import normalize, to_wav_bytes
from voicebot.catchphrases import load_catchphrases
from voicebot.config import Config, load_config
from voicebot.engines import create_engine
from voicebot.voices import load_voices

PHRASES = [
    "Всем привет, я тут впервые, а что тут происходит?",
    "Стример, ты опять проиграл? Ну это уже классика.",
    "Я готов, я готов, я готов!",
    "Чат, не спамьте, а то модераторы всех забанят.",
    "Сколько можно сидеть в этом лобби, давай уже играть!",
]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.toml")
    p.add_argument("--engines", nargs="+", default=["f5", "xtts"], choices=["f5", "xtts", "fish", "dummy"])
    p.add_argument("--voices", nargs="*", help="id голосов (имена папок); по умолчанию все")
    p.add_argument("--phrases", nargs="*", help="свои фразы вместо встроенных")
    p.add_argument("--out", default="out")
    args = p.parse_args()

    cfg = load_config(args.config) if Path(args.config).exists() else Config()
    voices = load_voices(cfg.path(cfg.voices.dir))
    if args.voices:
        voices = [v for v in voices if v.id in args.voices]
    if not voices:
        raise SystemExit("Нет голосов: положите ref.wav (+ ref.txt) в voices/<имя>/ — см. voices/README.md")
    own = load_catchphrases(cfg.path("catchphrases.toml"), voices).phrases

    def phrases_for(voice_id: str) -> list[str]:
        # Свои фразы из --phrases; иначе — реплики персонажа из catchphrases.toml + общие мемные.
        return args.phrases or own.get(voice_id, [])[:4] + PHRASES[: 5 - min(3, len(own.get(voice_id, [])))]

    summary = []
    for name in args.engines:
        print(f"\n=== {name}: загрузка модели… ===")
        t0 = time.perf_counter()
        engine = create_engine(cfg.engine, name)
        print(f"загружено за {time.perf_counter() - t0:.1f} с")
        out_dir = Path(args.out) / name
        out_dir.mkdir(parents=True, exist_ok=True)
        times = []
        for voice in voices:
            for n, text in enumerate(phrases_for(voice.id), 1):
                t0 = time.perf_counter()
                wav, sr = engine.synth(text, voice)
                dt = time.perf_counter() - t0
                seconds = wav.size / sr
                times.append((dt, seconds))
                (out_dir / f"{voice.id}_{n}.wav").write_bytes(to_wav_bytes(normalize(np.asarray(wav)), sr))
                print(f"{voice.name:>20} #{n}: {dt:5.2f} с синтеза на {seconds:4.1f} с звука")
        avg = sum(t for t, _ in times) / len(times)
        rtf = sum(t for t, _ in times) / max(1e-6, sum(s for _, s in times))
        summary.append(f"{name}: в среднем {avg:.2f} с на фразу, RTF {rtf:.2f} (меньше 1 — быстрее реального времени)")
        del engine
        gc.collect()
        try:
            import torch

            torch.cuda.empty_cache()
        except ImportError:
            pass

    print("\n" + "\n".join(summary))
    print(f"Файлы: {Path(args.out).resolve()}")


if __name__ == "__main__":
    main()
