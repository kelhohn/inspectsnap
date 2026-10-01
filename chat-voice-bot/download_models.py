"""Скачивает русскую модель F5-TTS и прописывает пути в config.toml.

    python download_models.py
    python download_models.py --repo Misha24-10/F5-TTS_RUSSIAN --file путь/к/чекпоинту.safetensors
"""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent
DEFAULT_REPO = "Misha24-10/F5-TTS_RUSSIAN"
CKPT_EXT = (".safetensors", ".pt")


def _step(name: str) -> int:
    nums = re.findall(r"\d+", PurePosixPath(name).name)
    return int(nums[-1]) if nums else -1


def pick_checkpoint(files: list[str]) -> tuple[str, str]:
    """Выбирает (чекпоинт, vocab.txt): чекпоинт рядом со своим vocab.txt, версия v1 и самый поздний шаг."""
    vocabs = {str(PurePosixPath(f).parent): f for f in files if PurePosixPath(f).name == "vocab.txt"}
    if not vocabs:
        raise SystemExit("В репозитории модели нет vocab.txt — укажите файлы вручную (см. README)")
    ckpts = [f for f in files if f.endswith(CKPT_EXT) and "vocos" not in f.lower()]
    if not ckpts:
        raise SystemExit("В репозитории модели нет чекпоинта .safetensors/.pt")

    def vocab_for(ckpt: str) -> str | None:
        p = PurePosixPath(ckpt).parent
        while True:
            if str(p) in vocabs:
                return vocabs[str(p)]
            if str(p) in (".", ""):
                return None
            p = p.parent

    def score(ckpt: str) -> tuple:
        return (vocab_for(ckpt) is not None, "v1" in ckpt.lower(), ckpt.endswith(".safetensors"), _step(ckpt))

    best = max(ckpts, key=score)
    return best, vocab_for(best) or next(iter(vocabs.values()))


def model_arch(ckpt: str) -> str:
    return "F5TTS_v1_Base" if "v1" in ckpt.lower() else "F5TTS_Base"


def set_config_values(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        line = f'{key} = "{value}"'
        text, n = re.subn(rf"(?m)^{key}\s*=.*$", line.replace("\\", "\\\\"), text)
        if n == 0:
            text = text.replace("[engine]\n", f"[engine]\n{line}\n", 1)
    return text


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--repo", default=DEFAULT_REPO)
    p.add_argument("--file", help="путь чекпоинта внутри репозитория (если автовыбор ошибся)")
    p.add_argument("--vocab", help="путь vocab.txt внутри репозитория")
    p.add_argument("--config", default=str(ROOT / "config.toml"))
    p.add_argument("--channel", default="", help="заодно вписать канал Twitch в config.toml")
    args = p.parse_args()

    from huggingface_hub import hf_hub_download, list_repo_files

    files = list_repo_files(args.repo)
    ckpt, vocab = pick_checkpoint(files)
    ckpt, vocab = args.file or ckpt, args.vocab or vocab
    print(f"Модель:  {args.repo}\nЧекпоинт: {ckpt}\nСловарь:  {vocab}")

    out = ROOT / "models" / "f5_russian"
    out.mkdir(parents=True, exist_ok=True)
    local = {}
    for name, remote in (("ckpt", ckpt), ("vocab", vocab)):
        cached = Path(hf_hub_download(args.repo, remote))
        dest = out / PurePosixPath(remote).name
        if not dest.exists() or dest.stat().st_size != cached.stat().st_size:
            shutil.copyfile(cached, dest)
        local[name] = dest.relative_to(ROOT).as_posix()

    cfg = Path(args.config)
    if not cfg.exists():
        shutil.copyfile(ROOT / "config.example.toml", cfg)
    values = {"f5_model": model_arch(ckpt), "f5_ckpt_file": local["ckpt"], "f5_vocab_file": local["vocab"]}
    channel = args.channel.strip().lstrip("#").lower()
    if channel:
        values["channel"] = channel
    cfg.write_text(set_config_values(cfg.read_text(encoding="utf-8"), values), encoding="utf-8")
    print(f"Готово: {local['ckpt']} (архитектура {model_arch(ckpt)}), пути записаны в {cfg.name}")
    print(f"Если звучит плохо — сверьтесь с https://huggingface.co/{args.repo} и укажите --file вручную.")


if __name__ == "__main__":
    main()
