"""Нарезает голоса персонажей по ссылкам из voices.csv → voices/<id>/ref.wav + ref.txt + voice.toml.

    python add_voices.py              # все строки voices.csv, уже готовые голоса пропускаются
    python add_voices.py --force arthas
    python add_voices.py --no-clean   # не вычищать музыку (быстрее, если фон чистый)

Если в voices.csv не указано время начала (start), скрипт сам находит в первых минутах ролика
куски речи и склеивает из них образец нужной длины — подходит для подборок «все фразы персонажа».

Источник — ссылка YouTube/VK/... (через yt-dlp) или путь к файлу на диске.
Музыка и шумы вычищаются нейросетью Demucs, текст образца распознаётся Whisper.
"""

from __future__ import annotations

import voicebot.compat  # noqa: F401 — до torch: прячет сломанный torchcodec
import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from voicebot.audio import normalize, to_wav_bytes  # noqa: E402

VOICES = ROOT / "voices"


@dataclass
class VoiceRow:
    id: str
    name: str
    source: str
    start: float | None  # None — найти речь автоматически
    duration: float


def parse_time(s: str) -> float:
    """"83", "1:23", "0:01:23.5" → секунды."""
    s = s.strip()
    if not s:
        return 0.0
    total = 0.0
    for part in s.split(":"):
        total = total * 60 + float(part.replace(",", "."))
    return total


def read_rows(path: Path) -> list[VoiceRow]:
    rows = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        lines = (line for line in f if line.strip() and not line.lstrip().startswith("#"))
        for r in csv.DictReader(lines, delimiter=";"):
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("id") or not r.get("source"):
                continue
            rows.append(VoiceRow(id=r["id"], name=r.get("name") or r["id"], source=r["source"],
                                 start=parse_time(r["start"]) if r.get("start") else None,
                                 duration=parse_time(r.get("duration", "")) or 10.0))
    return rows


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def run(cmd: list[str]) -> None:
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name}: {res.stderr.strip()[-800:]}")


def fetch(source: str, tmp: Path) -> Path:
    if source.startswith(("http://", "https://")):
        out = tmp / "source.%(ext)s"
        # Без перекодирования в yt-dlp: нарезку и конвертацию делает наш ffmpeg.
        run([sys.executable, "-m", "yt_dlp", "-f", "bestaudio/best", "--no-playlist", "-o", str(out), source])
        return next(tmp.glob("source.*"))
    path = Path(source)
    if not path.is_absolute():
        path = ROOT / path
    if not path.exists():
        raise FileNotFoundError(path)
    return path


def cut(src: Path, dest: Path, start: float, duration: float, ffmpeg: str, sr: int = 24000) -> None:
    run([ffmpeg, "-y", "-loglevel", "error", "-ss", f"{start:.2f}", "-t", f"{duration:.2f}", "-i", str(src),
         "-ac", "1", "-ar", str(sr), "-af", "loudnorm=I=-18:TP=-2", str(dest)])


def separate_vocals(src: Path, tmp: Path) -> Path:
    run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs", "-o", str(tmp), str(src)])
    return next(tmp.glob(f"htdemucs/{src.stem}/vocals.wav"))


AUTO_SCAN_SECONDS = 180  # сколько начала ролика анализировать в авто-режиме
AUTO_SKIP_HEAD = 4.0     # пропустить заставку канала


def speech_segments(wav: np.ndarray, sr: int, frame: float = 0.02, min_gap: float = 0.25,
                    min_len: float = 0.4) -> list[tuple[int, int]]:
    """Куски речи по громкости (после Demucs фон уже вычищен): [(начало, конец)] в сэмплах."""
    hop = max(1, int(sr * frame))
    n = wav.size // hop
    if n == 0:
        return []
    rms = np.sqrt(np.mean(wav[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    threshold = max(np.percentile(db, 95) - 30, -50)
    voiced = db > threshold
    # Заполняем короткие паузы внутри фразы.
    gap = int(min_gap / frame)
    i = 0
    while i < n:
        if not voiced[i]:
            j = i
            while j < n and not voiced[j]:
                j += 1
            if 0 < i and j < n and j - i <= gap:
                voiced[i:j] = True
            i = j
        else:
            i += 1
    segs, i = [], 0
    while i < n:
        if voiced[i]:
            j = i
            while j < n and voiced[j]:
                j += 1
            if (j - i) * frame >= min_len:
                segs.append((i * hop, j * hop))
            i = j
        else:
            i += 1
    return segs


def auto_reference(wav: np.ndarray, sr: int, duration: float, skip_head: float = AUTO_SKIP_HEAD,
                   max_len: float = 12.0, pause: float = 0.3) -> np.ndarray:
    """Склеивает подряд идущие фразы в образец ~duration секунд (паузы ужимаются до pause)."""
    segs = [s for s in speech_segments(wav, sr) if s[0] >= skip_head * sr] or speech_segments(wav, sr)
    if not segs:
        raise RuntimeError("в ролике не найдено речи")
    lengths = [(b - a) / sr for a, b in segs]
    best, best_score = (0, 1), -1.0
    for i in range(len(segs)):
        total, j = 0.0, i
        while j < len(segs) and total + lengths[j] + (pause if j > i else 0) <= max_len:
            total += lengths[j] + (pause if j > i else 0)
            j += 1
        if j == i:  # одна фраза длиннее max_len — берём её начало
            total, j = max_len, i + 1
        score = min(total, duration) - 0.1 * (j - i)  # ближе к нужной длине, меньше склеек
        if score > best_score + 1e-9:
            best, best_score = (i, j), score
    silence = np.zeros(int(pause * sr), dtype=np.float32)
    parts = []
    for k in range(*best):
        if parts:
            parts.append(silence)
        a, b = segs[k]
        parts.append(wav[a:b].astype(np.float32))
    return np.concatenate(parts)[: int(max_len * sr)]


def read_wav(path: Path, ffmpeg: str, sr: int = 24000) -> np.ndarray:
    raw = subprocess.run([ffmpeg, "-loglevel", "error", "-i", str(path), "-ac", "1", "-ar", str(sr),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768


_asr = None


def transcribe(wav: Path, ffmpeg: str) -> str:
    global _asr
    if _asr is None:
        from f5_tts.infer.utils_infer import transcribe as f5_transcribe

        _asr = f5_transcribe
    # Отдаём Whisper уже декодированный звук: иначе transformers читает файл через torchcodec,
    # который на Windows ломается (WinError 127).
    return _asr({"raw": read_wav(wav, ffmpeg, 16000), "sampling_rate": 16000}, "ru")


def build_voice(row: VoiceRow, clean: bool, ffmpeg: str) -> Path:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        src = fetch(row.source, tmp)
        d = VOICES / row.id
        d.mkdir(parents=True, exist_ok=True)
        ref = d / "ref.wav"
        rough = tmp / "rough.wav"
        if row.start is None:
            cut(src, rough, 0.0, AUTO_SCAN_SECONDS, ffmpeg, sr=44100)
            if clean:
                rough = separate_vocals(rough, tmp)
            sr = 24000
            ref.write_bytes(to_wav_bytes(normalize(auto_reference(read_wav(rough, ffmpeg, sr), sr, row.duration)), sr))
        else:
            # Режем с запасом в 2 с по краям: Demucs точнее на более длинном куске.
            pad = 2.0 if clean else 0.0
            cut(src, rough, max(0.0, row.start - pad), row.duration + 2 * pad, ffmpeg, sr=44100)
            if clean:
                rough = separate_vocals(rough, tmp)
            cut(rough, ref, min(pad, row.start), row.duration, ffmpeg)
    (d / "ref.txt").write_text(transcribe(ref, ffmpeg) + "\n", encoding="utf-8")
    meta = d / "voice.toml"
    if not meta.exists():
        meta.write_text(f'name = "{row.name}"\n', encoding="utf-8")
    return d


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("ids", nargs="*", help="только эти id (по умолчанию все строки)")
    p.add_argument("--csv", default=str(ROOT / "voices.csv"))
    p.add_argument("--force", action="store_true", help="пересоздать уже готовые голоса")
    p.add_argument("--no-clean", action="store_true", help="не вычищать музыку через Demucs")
    args = p.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        shutil.copyfile(ROOT / "voices.example.csv", csv_path)
        raise SystemExit(f"Создан {csv_path.name} — впишите ссылки на персонажей и запустите снова.")
    example = ROOT / "voices.example.csv"
    if not read_rows(csv_path) and example.exists() and read_rows(example):
        # voices.csv создан старой версией без ссылок — берём готовый список из примера.
        shutil.copyfile(example, csv_path)
        print(f"В {csv_path.name} не было ссылок — взял готовый список персонажей из {example.name}.")
    rows = [r for r in read_rows(csv_path) if not args.ids or r.id in args.ids]
    if not rows:
        raise SystemExit(f"В {csv_path.name} нет строк со ссылкой (колонка source).")

    ffmpeg = ffmpeg_exe()
    ok, failed = [], []
    for row in rows:
        done = all((VOICES / row.id / f).exists() for f in ("ref.wav", "ref.txt"))
        if done and not args.force:
            print(f"· {row.name}: уже есть (пересоздать: --force {row.id})")
            continue
        where = "поиск речи автоматически" if row.start is None else f"с {row.start:.1f} с"
        print(f"→ {row.name}: {row.source} ({where}, {row.duration:.0f} с)…", flush=True)
        try:
            d = build_voice(row, clean=not args.no_clean, ffmpeg=ffmpeg)
            print(f"  готово: {d / 'ref.txt'} → «{(d / 'ref.txt').read_text(encoding='utf-8').strip()}»")
            ok.append(row.id)
        except Exception as e:  # noqa: BLE001 — один битый источник не должен останавливать остальные
            print(f"  ОШИБКА: {e}")
            failed.append(row.id)
    print(f"\nГотово: {len(ok)}, ошибок: {len(failed)} {failed if failed else ''}")
    if ok:
        print("Проверьте расшифровки в voices/<id>/ref.txt (исправьте ошибки распознавания) и послушайте ref.wav.")


if __name__ == "__main__":
    main()
