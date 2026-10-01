"""Нарезает голоса персонажей по ссылкам из voices.csv → voices/<id>/ref.wav + ref.txt + voice.toml.

    python add_voices.py              # все строки voices.csv, уже готовые голоса пропускаются
    python add_voices.py --force arthas
    python add_voices.py --no-clean   # не вычищать музыку (быстрее, если фон чистый)

Источник — ссылка YouTube/VK/... (через yt-dlp) или путь к файлу на диске.
Музыка и шумы вычищаются нейросетью Demucs, текст образца распознаётся Whisper.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VOICES = ROOT / "voices"


@dataclass
class VoiceRow:
    id: str
    name: str
    source: str
    start: float
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
                                 start=parse_time(r.get("start", "")),
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


_asr = None


def transcribe(wav: Path) -> str:
    global _asr
    if _asr is None:
        from f5_tts.infer.utils_infer import transcribe as f5_transcribe

        _asr = f5_transcribe
    return _asr(str(wav), "ru")


def build_voice(row: VoiceRow, clean: bool, ffmpeg: str) -> Path:
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        src = fetch(row.source, tmp)
        # Режем с запасом в 2 с по краям: Demucs точнее на более длинном куске.
        pad = 2.0 if clean else 0.0
        rough = tmp / "rough.wav"
        cut(src, rough, max(0.0, row.start - pad), row.duration + 2 * pad, ffmpeg, sr=44100)
        if clean:
            rough = separate_vocals(rough, tmp)
        d = VOICES / row.id
        d.mkdir(parents=True, exist_ok=True)
        ref = d / "ref.wav"
        cut(rough, ref, min(pad, row.start), row.duration, ffmpeg)
    (d / "ref.txt").write_text(transcribe(ref) + "\n", encoding="utf-8")
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
    rows = [r for r in read_rows(csv_path) if not args.ids or r.id in args.ids]
    if not rows:
        raise SystemExit(f"В {csv_path.name} нет строк со ссылкой (колонка source).")

    ffmpeg = ffmpeg_exe()
    ok, failed = [], []
    for row in rows:
        if (VOICES / row.id / "ref.wav").exists() and not args.force:
            print(f"· {row.name}: уже есть (пересоздать: --force {row.id})")
            continue
        print(f"→ {row.name}: {row.source} с {row.start:.1f} с, {row.duration:.0f} с…", flush=True)
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
