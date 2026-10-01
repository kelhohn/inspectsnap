import asyncio
import random
from pathlib import Path

import numpy as np
import scipy.signal  # noqa: F401 — прогрев импорта, чтобы не влиял на тайминги

from voicebot.app import VoiceBot
from voicebot.config import Config, FilterConfig
from voicebot.engines import DummyEngine
from voicebot.filters import clean_text, decide, parse_command
from voicebot.twitch_irc import ChatMessage, Moderation, parse_line, to_event
from voicebot.voices import Voice, VoicePicker, load_voices


def msg(text="привет всем", *, first=True, mod=False, login="viewer", broadcaster=False, mid="m1"):
    return ChatMessage(id=mid, login=login, display_name=login, text=text, first_message=first,
                       is_moderator=mod, is_broadcaster=broadcaster, is_vip=False)


def voices(n=4):
    return [Voice(id=f"v{i}", name=f"Voice{i}", ref_wav=Path(f"v{i}.wav"), ref_text="") for i in range(n)]


# ---------- IRC ----------

FIRST_MSG = ("@badge-info=;badges=;color=#FF0000;display-name=Новичок;emotes=;first-msg=1;"
             "id=abc-123;mod=0;returning-chatter=0;room-id=1;subscriber=0;tmi-sent-ts=1;turbo=0;"
             "user-id=2;user-type= :novichok!novichok@novichok.tmi.twitch.tv PRIVMSG #chan :Всем привет!")
MOD_MSG = ("@badges=moderator/1,subscriber/12;display-name=Mod\\sGuy;first-msg=0;id=def;mod=1 "
           ":modguy!modguy@modguy.tmi.twitch.tv PRIVMSG #chan :\x01ACTION залетел\x01")


def test_parse_first_message():
    e = to_event(parse_line(FIRST_MSG))
    assert isinstance(e, ChatMessage)
    assert e.first_message and not e.is_moderator
    assert e.login == "novichok" and e.display_name == "Новичок"
    assert e.text == "Всем привет!" and e.id == "abc-123"


def test_parse_moderator_action_and_tag_escape():
    e = to_event(parse_line(MOD_MSG))
    assert e.is_moderator and not e.first_message
    assert e.display_name == "Mod Guy"
    assert e.text == "залетел"


def test_parse_moderation_events():
    clearmsg = to_event(parse_line("@login=bad;target-msg-id=abc-123 :tmi.twitch.tv CLEARMSG #chan :текст"))
    assert clearmsg == Moderation(message_id="abc-123", login="bad")
    ban = to_event(parse_line("@ban-duration=600 :tmi.twitch.tv CLEARCHAT #chan :BadUser"))
    assert ban == Moderation(login="baduser")
    assert to_event(parse_line(":tmi.twitch.tv CLEARCHAT #chan")) == Moderation(clear_all=True)


# ---------- фильтры ----------

def test_decide_first_and_regular():
    cfg = FilterConfig()
    assert decide(msg(), cfg).reason == "first"
    assert not decide(msg(first=False), cfg).speak


def test_decide_moderator_prefix_and_commands():
    cfg = FilterConfig(moderator_prefix="~")
    assert not decide(msg("обычное", first=False, mod=True), cfg).speak
    d = decide(msg("~в эфир", first=False, mod=True), cfg)
    assert d.speak and d.text == "в эфир" and d.reason == "moderator"
    assert decide(msg("!discord"), FilterConfig()).reason == "команда бота"


def test_decide_rejects_junk_and_banned():
    cfg = FilterConfig(banned_words=["плохое"])
    assert not decide(msg("))))) 123 :)"), cfg).speak
    assert decide(msg("это ПЛОХОЕ слово"), cfg).reason == "запрещённое слово"
    assert decide(msg("ёжик", login="nightbot"), cfg).reason == "игнор-лист"


def test_clean_text():
    assert clean_text("смотри https://example.com/x круто", 200) == "смотри ссылка круто"
    assert clean_text("@стример ааааааааа", 200) == "стример ааа"
    assert clean_text("го го го го го", 200) == "го го"
    out = clean_text(" ".join(f"слово{i}" for i in range(100)), 50)
    assert len(out) <= 51 and out.endswith("…")


def test_parse_command_only_for_mods():
    assert parse_command(msg("!tts skip")) is None
    assert parse_command(msg("!tts skip", mod=True)).name == "skip"
    c = parse_command(msg("!tts громкость 40", mod=True))
    assert (c.name, c.arg) == ("volume", "40")


# ---------- голоса ----------

def test_picker_avoids_repeats_and_fixes_moderators():
    p = VoicePicker(voices(4), avoid_repeat=2, rng=random.Random(1))
    picks = [p.random_voice().id for _ in range(50)]
    assert all(picks[i] not in picks[max(0, i - 2):i] for i in range(len(picks)))
    assert p.for_moderator("modguy") is p.for_moderator("modguy")
    pinned = VoicePicker(voices(4), moderator_voices={"modguy": "v3"})
    assert pinned.for_moderator("modguy").id == "v3"


def test_load_voices(tmp_path):
    (tmp_path / "arthas").mkdir()
    (tmp_path / "arthas" / "ref.wav").write_bytes(b"")
    (tmp_path / "arthas" / "ref.txt").write_text("Фростморн жаждет\n", encoding="utf-8")
    (tmp_path / "arthas" / "voice.toml").write_text('name = "Артас"\nweight = 2\n', encoding="utf-8")
    (tmp_path / "broken").mkdir()
    vs = load_voices(tmp_path)
    assert len(vs) == 1 and vs[0].name == "Артас" and vs[0].ref_text == "Фростморн жаждет" and vs[0].weight == 2


# ---------- конвейер ----------

class FakeOverlay:
    def __init__(self):
        self.played, self.events = [], []
        self.duration = 0.05

    async def broadcast(self, event):
        self.events.append(event)

    async def play(self, clip_id, wav, volume, stop):
        self.played.append(clip_id)
        try:
            await asyncio.wait_for(stop.wait(), timeout=self.duration)
        except asyncio.TimeoutError:
            pass


def make_bot(**queue):
    cfg = Config()
    cfg.audio.output = "overlay"
    cfg.queue.delay_seconds = queue.get("delay", 0.0)
    cfg.queue.gap_seconds = 0.0
    cfg.queue.max_size = queue.get("max_size", 15)
    overlay = FakeOverlay()
    bot = VoiceBot(cfg, DummyEngine(), VoicePicker(voices(3)), overlay=overlay)
    return bot, overlay


def spoken(overlay):
    return [e["text"] for e in overlay.events if e["type"] == "speak"]


async def run_for(bot, seconds):
    task = asyncio.ensure_future(bot.run())
    await asyncio.sleep(seconds)
    task.cancel()


def test_pipeline_speaks_first_and_mod_messages_mods_first():
    async def go():
        bot, overlay = make_bot(delay=0.05)
        await bot.handle_event(msg("ФМ зрителя", mid="a"))
        await bot.handle_event(msg("обычное", first=False, mid="b"))
        await bot.handle_event(msg("слово модера", first=False, mod=True, login="mod", mid="c"))
        await run_for(bot, 0.6)
        return spoken(overlay)

    assert asyncio.run(go()) == ["слово модера", "ФМ зрителя"]


def test_deleted_message_and_ban_are_not_spoken():
    async def go():
        bot, overlay = make_bot(delay=0.2)
        await bot.handle_event(msg("удалят", mid="x"))
        await bot.handle_event(msg("забанят", login="troll", mid="y"))
        await bot.handle_event(msg("останется", login="ok", mid="z"))
        await bot.handle_event(Moderation(message_id="x"))
        await bot.handle_event(Moderation(login="troll"))
        await run_for(bot, 0.6)
        return spoken(overlay)

    assert asyncio.run(go()) == ["останется"]


def test_commands_skip_pause_clear_volume():
    async def go():
        bot, overlay = make_bot()
        overlay.duration = 5
        await bot.handle_event(msg("длинное", mid="1"))
        task = asyncio.ensure_future(bot.run())
        await asyncio.sleep(0.2)
        assert bot.current is not None
        await bot.handle_event(msg("!tts skip", first=False, mod=True, login="mod"))
        await asyncio.sleep(0.1)
        assert bot.current is None
        await bot.run_command("pause")
        await bot.handle_event(msg("на паузе", mid="2"))
        await asyncio.sleep(0.2)
        assert bot.current is None and "на паузе" not in spoken(overlay)
        await bot.run_command("clear")
        await bot.run_command("resume")
        await asyncio.sleep(0.2)
        assert spoken(overlay) == ["длинное"]
        assert await bot.run_command("volume", "150") == "громкость 100%"
        task.cancel()

    asyncio.run(go())


def test_full_queue_mod_evicts_viewer():
    async def go():
        bot, _ = make_bot(max_size=2)
        await bot.handle_event(msg("раз", mid="1"))
        await bot.handle_event(msg("два", mid="2"))
        await bot.handle_event(msg("три", mid="3"))  # не влезло
        await bot.handle_event(msg("модер", first=False, mod=True, login="m", mid="4"))
        return [i.text for i in bot.pending]

    # модератор вытесняет самое новое сообщение зрителя, порядок остальных сохраняется
    assert asyncio.run(go()) == ["модер", "раз"]


def test_dummy_engine_output():
    wav, sr = DummyEngine().synth("привет мир", voices(1)[0])
    assert sr == 24000 and wav.dtype == np.float32 and wav.size > 0
