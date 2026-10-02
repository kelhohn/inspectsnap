"""Включает движок Fish Audio: спрашивает API-ключ и записывает его в config.toml (только локально).

    python configure_fish.py            # спросит ключ
    python configure_fish.py --off      # вернуть локальный F5
"""

from __future__ import annotations

import argparse
import getpass
import shutil
from pathlib import Path

from download_models import set_config_values

ROOT = Path(__file__).resolve().parent


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default=str(ROOT / "config.toml"))
    p.add_argument("--off", action="store_true", help="вернуться на локальный F5")
    args = p.parse_args()

    cfg = Path(args.config)
    if not cfg.exists():
        shutil.copyfile(ROOT / "config.example.toml", cfg)
    text = cfg.read_text(encoding="utf-8")
    if args.off:
        cfg.write_text(set_config_values(text, {"name": "f5"}), encoding="utf-8")
        print("Движок: локальный F5.")
        return
    key = getpass.getpass("Вставьте API-ключ Fish Audio (ввод не отображается) и нажмите Enter: ").strip()
    if not key:
        raise SystemExit("Ключ не введён — ничего не изменено.")
    cfg.write_text(set_config_values(text, {"name": "fish", "fish_api_key": key}), encoding="utf-8")
    print(f"Готово: движок fish, ключ записан в {cfg.name} (этот файл не попадает в git).")


if __name__ == "__main__":
    main()
