"""Запуск: python -m voicebot [run|console|devices] [--config config.toml]"""

from __future__ import annotations

from . import compat  # noqa: F401 — до torch: прячет сломанный torchcodec

import argparse
import asyncio
import logging
import sys

from .app import VoiceBot
from .config import load_config
from .engines import create_engine
from .overlay import OverlayServer
from .twitch_irc import ChatMessage, TwitchChat
from .voices import VoicePicker, load_voices

log = logging.getLogger("voicebot")


def parse_console_line(line: str) -> ChatMessage | None:
    """Строки для режима console:
        текст            → первое сообщение зрителя
        mod ник: текст   → сообщение модератора
        user ник: текст  → обычное сообщение (не озвучивается)
        !tts skip        → команда модератора
    """
    line = line.strip()
    if not line:
        return None
    kind, login, text = "fm", "viewer", line
    for prefix in ("mod ", "user "):
        if line.startswith(prefix) and ":" in line:
            login, text = line[len(prefix):].split(":", 1)
            kind, login, text = prefix.strip(), login.strip().lower(), text.strip()
    is_mod = kind == "mod" or text.startswith("!tts")
    return ChatMessage(id="", login=login, display_name=login, text=text,
                       first_message=kind == "fm" and not is_mod, is_moderator=is_mod,
                       is_broadcaster=False, is_vip=False)


async def _stdin_lines():
    loop = asyncio.get_running_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            return
        yield line


async def main_async(args: argparse.Namespace) -> None:
    from pathlib import Path

    if not Path(args.config).exists():
        raise SystemExit(f"Нет файла {args.config}. Сначала запустите setup.bat "
                         f"(или скопируйте config.example.toml в config.toml).")
    cfg = load_config(args.config)
    if args.engine:
        cfg.engine.name = args.engine
    if args.audio:
        cfg.audio.output = args.audio
    log.info("Звук: %s", "в колонки (устройство по умолчанию)" if cfg.audio.output == "device" and not cfg.audio.device
             else f"устройство {cfg.audio.device}" if cfg.audio.output == "device"
             else "только в странице-оверлее (OBS «Браузер» / вкладка браузера)")
    voices = load_voices(cfg.path(cfg.voices.dir))
    if not voices:
        raise SystemExit("\nНет ни одного голоса персонажа в папке voices\\.\n"
                         "Запустите add-voices.bat — он нарежет персонажей по ссылкам из voices.csv "
                         "(5–15 минут в первый раз), — затем снова этот батник.")
    log.info("Голосов загружено: %d (%s)", len(voices), ", ".join(v.name for v in voices))
    picker = VoicePicker(voices, cfg.voices.avoid_repeat, cfg.voices.moderator_mode, cfg.voices.moderator_voices)

    log.info("Загрузка движка %s…", cfg.engine.name)
    engine = create_engine(cfg.engine)

    chat = None
    if args.command == "run":
        if not cfg.twitch.channel:
            raise SystemExit("Укажите [twitch] channel в config.toml")
        chat = TwitchChat(cfg.twitch.channel, cfg.twitch.login, cfg.twitch.oauth_token)

    bot: VoiceBot | None = None
    overlay = None
    if cfg.overlay.enabled:
        overlay = OverlayServer(cfg.overlay.host, cfg.overlay.port, cfg.audio.sample_rate,
                                on_command=lambda c, a: bot.run_command(c, a),  # type: ignore[union-attr]
                                get_state=lambda: bot.state())  # type: ignore[union-attr]
    bot = VoiceBot(cfg, engine, picker, overlay=overlay, chat=chat)
    if overlay:
        await overlay.start()
        if args.open:
            import webbrowser

            path = "overlay" if args.open == "overlay" else ""
            webbrowser.open(f"http://{cfg.overlay.host}:{cfg.overlay.port}/{path}")
        log.info("Бот готов.")

    async def feed():
        if chat is not None:
            async for event in chat.events():
                await bot.handle_event(event)
        else:
            print(parse_console_line.__doc__)
            async for line in _stdin_lines():
                msg = parse_console_line(line)
                if msg:
                    await bot.handle_event(msg)

    await asyncio.gather(bot.run(), feed())


def main() -> None:
    p = argparse.ArgumentParser(prog="voicebot", description="Озвучка ФМ и модераторов голосами персонажей")
    p.add_argument("command", nargs="?", default="run", choices=["run", "console", "devices"],
                   help="run — Twitch-чат; console — сообщения с клавиатуры; devices — список звуковых устройств")
    p.add_argument("--config", default="config.toml")
    p.add_argument("--engine", choices=["f5", "xtts", "dummy"], help="переопределить движок из конфига")
    p.add_argument("--audio", choices=["device", "overlay"], help="куда звук: колонки или страница-оверлей")
    p.add_argument("--open", choices=["panel", "overlay"], help="открыть страницу в браузере, когда бот готов")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    if args.command == "devices":
        from .audio import list_devices

        print(list_devices())
        return
    try:
        asyncio.run(main_async(args))
    except KeyboardInterrupt:
        pass
    except OSError as e:
        if getattr(e, "winerror", None) == 10048 or e.errno in (98, 48, 10048):
            raise SystemExit("Порт 8790 занят: бот уже запущен в другом окне — закройте его.") from e
        raise


if __name__ == "__main__":
    main()
