import wave
from pathlib import Path

import numpy as np
import pytest

from add_voices import auto_reference, cut, ffmpeg_exe, parse_time, read_rows, speech_segments
from download_models import model_arch, pick_checkpoint, set_config_values
from voicebot.audio import to_wav_bytes


def test_pick_checkpoint_prefers_v1_latest_with_vocab():
    files = [
        "README.md",
        "F5TTS_Base/model_100000.pt",
        "F5TTS_Base/vocab.txt",
        "F5TTS_v1_Base/model_240000_inference.safetensors",
        "F5TTS_v1_Base/model_120000_inference.safetensors",
        "F5TTS_v1_Base/vocab.txt",
        "vocos/model.safetensors",
    ]
    ckpt, vocab = pick_checkpoint(files)
    assert ckpt == "F5TTS_v1_Base/model_240000_inference.safetensors"
    assert vocab == "F5TTS_v1_Base/vocab.txt"
    assert model_arch(ckpt) == "F5TTS_v1_Base"
    assert model_arch("F5TTS_Base/model_100000.pt") == "F5TTS_Base"


def test_pick_checkpoint_uses_parent_vocab():
    ckpt, vocab = pick_checkpoint(["vocab.txt", "ckpts/v1/model_5.safetensors"])
    assert (ckpt, vocab) == ("ckpts/v1/model_5.safetensors", "vocab.txt")


def test_set_config_values_on_example():
    text = (Path(__file__).resolve().parents[1] / "config.example.toml").read_text(encoding="utf-8")
    out = set_config_values(text, {"f5_ckpt_file": "models/f5_russian/m.safetensors", "channel": "mychan"})
    assert 'f5_ckpt_file = "models/f5_russian/m.safetensors"' in out
    assert 'channel = "mychan"' in out
    import tomllib

    cfg = tomllib.loads(out)
    assert cfg["twitch"]["channel"] == "mychan"


def test_parse_time():
    assert parse_time("83") == 83
    assert parse_time("1:23") == 83
    assert parse_time("0:01:23,5") == 83.5
    assert parse_time("") == 0


def test_read_rows_skips_comments_and_empty_sources(tmp_path):
    p = tmp_path / "voices.csv"
    p.write_text("# комментарий\nid;name;source;start;duration\n"
                 "arthas;Артас;https://youtu.be/x;1:05;\nshrek;Шрек;;;10\nkain;Каин;https://youtu.be/y;;12\n",
                 encoding="utf-8")
    rows = read_rows(p)
    assert len(rows) == 2
    r = rows[0]
    assert (r.id, r.name, r.source, r.start, r.duration) == ("arthas", "Артас", "https://youtu.be/x", 65, 10)
    assert rows[1].start is None and rows[1].duration == 12  # пустой start — авто-поиск речи


def test_cut_with_real_ffmpeg(tmp_path):
    try:
        ffmpeg = ffmpeg_exe()
    except ImportError:
        pytest.skip("нет ffmpeg")
    sr = 44100
    t = np.arange(sr * 5) / sr
    src = tmp_path / "src.wav"
    src.write_bytes(to_wav_bytes((0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32), sr))
    dest = tmp_path / "ref.wav"
    cut(src, dest, start=1.0, duration=2.5, ffmpeg=ffmpeg)
    with wave.open(str(dest)) as w:
        assert w.getnchannels() == 1 and w.getframerate() == 24000
        assert abs(w.getnframes() / 24000 - 2.5) < 0.05


def _phrases(sr, layout):
    """layout: [(секунды тишины, секунды «речи»), ...] → сигнал с тоном вместо речи."""
    parts = []
    for silence, speech in layout:
        parts.append(np.zeros(int(silence * sr), dtype=np.float32))
        t = np.arange(int(speech * sr)) / sr
        parts.append((0.3 * np.sin(2 * np.pi * 200 * t)).astype(np.float32))
    parts.append(np.zeros(sr, dtype=np.float32))
    return np.concatenate(parts)


def test_speech_segments_finds_phrases():
    sr = 16000
    wav = _phrases(sr, [(1.0, 2.0), (1.5, 3.0), (0.1, 1.0)])  # пауза 0.1 с склеивается с предыдущей фразой
    segs = [(a / sr, b / sr) for a, b in speech_segments(wav, sr)]
    assert len(segs) == 2
    assert abs(segs[0][0] - 1.0) < 0.05 and abs(segs[0][1] - 3.0) < 0.05
    assert abs(segs[1][0] - 4.5) < 0.05 and abs(segs[1][1] - 8.6) < 0.05


def test_auto_reference_skips_intro_and_squeezes_pauses():
    sr = 16000
    # интро 2 с (до skip_head), затем фразы по 3 с с паузами по 2 с
    wav = _phrases(sr, [(0.5, 2.0)] + [(2.0, 3.0)] * 6)
    ref = auto_reference(wav, sr, duration=10, skip_head=4.0)
    seconds = ref.size / sr
    assert 9.0 <= seconds <= 12.0  # 3 фразы по 3 с + 2 паузы по 0.3 с = 9.6 с
    assert abs(seconds - 9.6) < 0.15


def test_auto_references_takes_distinct_parts():
    from add_voices import auto_references

    sr = 16000
    wav = _phrases(sr, [(0.5, 2.0)] + [(2.0, 3.0)] * 9)  # 9 фраз по 3 с после интро
    refs = auto_references(wav, sr, duration=10, count=3, skip_head=4.0)
    assert len(refs) == 3
    assert all(9.0 <= r.size / sr <= 12.0 for r in refs)
    # просим больше, чем есть речи — лишних огрызков не делаем
    assert len(auto_references(wav, sr, duration=10, count=5, skip_head=4.0)) == 3


def test_variants_and_multiple_starts(tmp_path):
    p = tmp_path / "voices.csv"
    p.write_text("id;name;source;start;duration;variants\n"
                 "briar;Брайер;https://y/1;;10;3\nvaas;Ваас;https://y/2;0:10|1:05;;\nold;Старый;https://y/3;;;\n",
                 encoding="utf-8")
    rows = {r.id: r for r in read_rows(p)}
    assert rows["briar"].count == 3 and rows["briar"].starts == []
    assert rows["vaas"].starts == [10, 65] and rows["vaas"].count == 2
    assert rows["old"].count == 1


def test_merge_example_adds_new_and_fills_empty(tmp_path):
    from add_voices import merge_example

    mine = tmp_path / "voices.csv"
    mine.write_text("id;name;source;start;duration\narthas;Артас;https://my/link;;10\nshrek;Шрек;;;10\n",
                    encoding="utf-8")
    example = tmp_path / "voices.example.csv"
    example.write_text("# комментарий\nid;name;source;start;duration;variants\n"
                       "arthas;Артас;https://example/a;;10;2\nshrek;Шрек;https://example/s;;10;1\n"
                       "briar;Брайер;https://example/b;;10;3\n", encoding="utf-8")
    added = merge_example(mine, example)
    assert set(added) == {"briar", "shrek"}
    rows = {r.id: r for r in read_rows(mine)}
    assert rows["arthas"].source == "https://my/link"  # своё не трогаем
    assert rows["shrek"].source == "https://example/s"  # пустая заготовка заполнена
    assert rows["briar"].count == 3
    assert merge_example(mine, example) == []  # повторно — ничего


def test_ref_name():
    from add_voices import ref_name

    assert [ref_name(i) for i in range(3)] == ["ref", "ref2", "ref3"]
