import pytest
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


def msg(text="привет всем", *, first=True, mod=False, login="viewer", broadcaster=False, vip=False, mid="m1"):
    return ChatMessage(id=mid, login=login, display_name=login, text=text, first_message=first,
                       is_moderator=mod, is_broadcaster=broadcaster, is_vip=vip)


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


def test_decide_tts_only_for_vip_mod_broadcaster():
    cfg = FilterConfig()
    # обычные сообщения модеров/VIP больше не озвучиваются сами
    assert not decide(msg("обычное", first=False, mod=True), cfg).speak
    assert not decide(msg("обычное", first=False, vip=True), cfg).speak
    for kw, reason in ((dict(mod=True), "moderator"), (dict(vip=True), "vip"), (dict(broadcaster=True), "broadcaster")):
        d = decide(msg("!tts в эфир", first=False, **kw), cfg)
        assert (d.speak, d.text, d.reason) == (True, "в эфир", reason)
    assert decide(msg("!TTS громко", first=False, mod=True), cfg).text == "громко"
    # зрителю — нельзя, даже если это его первое сообщение
    d = decide(msg("!tts хочу озвучку"), cfg)
    assert not d.speak and "только для" in d.reason
    assert not decide(msg("!tts", first=False, mod=True), cfg).speak
    assert decide(msg("!discord"), cfg).reason == "команда бота"
    # без VIP в tts_roles
    assert not decide(msg("!tts привет", first=False, vip=True), FilterConfig(tts_roles=["moderator"])).speak


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


def test_parse_command_roles_and_text_vs_command():
    cfg = FilterConfig()
    assert parse_command(msg("!tts skip"), cfg) is None  # зритель
    assert parse_command(msg("!tts skip", mod=True), cfg).name == "skip"
    assert parse_command(msg("!tts стоп", vip=True), cfg).name == "pause"
    assert parse_command(msg("!tts старт", broadcaster=True), cfg).name == "resume"
    c = parse_command(msg("!tts громкость 40", mod=True), cfg)
    assert (c.name, c.arg) == ("volume", "40")
    # служебное слово, но дальше текст — это озвучка, а не команда
    assert parse_command(msg("!tts стоп, это ограбление", mod=True), cfg) is None
    assert parse_command(msg("!tts громкость у тебя бешеная", mod=True), cfg) is None
    assert parse_command(msg("!tts привет", mod=True), cfg) is None


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
        self.overlay_clients = 1

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
        await bot.handle_event(msg("!tts слово модера", first=False, mod=True, login="mod", mid="c"))
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
        await bot.handle_event(msg("!tts модер", first=False, mod=True, login="m", mid="4"))
        return [i.text for i in bot.pending]

    # модератор вытесняет самое новое сообщение зрителя, порядок остальных сохраняется
    assert asyncio.run(go()) == ["модер", "раз"]


def test_dummy_engine_output():
    wav, sr = DummyEngine().synth("привет мир", voices(1)[0])
    assert sr == 24000 and wav.dtype == np.float32 and wav.size > 0


def test_console_line_roles():
    from voicebot.__main__ import parse_console_line

    owner = parse_console_line("!tts привет")
    assert owner.is_broadcaster and not owner.first_message
    assert parse_console_line("vip petya: !tts hi").is_vip
    assert parse_console_line("mod vasya: !tts hi").is_moderator
    assert parse_console_line("просто текст").first_message
    viewer = parse_console_line("user kolya: !tts hi")
    assert not (viewer.is_vip or viewer.is_moderator or viewer.is_broadcaster or viewer.first_message)


def test_old_config_keys_are_ignored(tmp_path):
    from voicebot.config import load_config

    p = tmp_path / "config.toml"
    p.write_text('[filters]\nvoice_moderators = true\nmoderator_prefix = "~"\nvoice_vips = false\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.filters.tts_roles == ["broadcaster", "moderator", "vip"]


def test_overlay_mode_without_open_overlay_falls_back_to_speakers():
    async def go():
        bot, overlay = make_bot()
        overlay.overlay_clients = 0
        played = []

        class Speakers:
            async def play(self, wav, volume, stop):
                played.append(wav.size)

        bot._speakers = Speakers()
        await bot.handle_event(msg("в колонки", mid="1"))
        await run_for(bot, 0.5)
        return played, overlay.played

    played, overlay_played = asyncio.run(go())
    assert len(played) == 1 and overlay_played == []


def test_accentuator_survives_broken_word_model():
    from voicebot.engines import Accentuator, harden_accent_model

    class FakeModel:
        def put_accent(self, word):
            if word == "мужичара":
                raise RuntimeError("onnx упал")
            return word.replace("о", "+о", 1)

    class FakeRUAccent:
        def __init__(self):
            self.accent_model = FakeModel()

        def process_all(self, text):
            return " ".join(self.accent_model.put_accent(w) for w in text.split())

    ru = FakeRUAccent()
    harden_accent_model(ru)
    acc = Accentuator.__new__(Accentuator)
    acc._acc = ru
    assert acc("вова мужичара") == "в+ова мужичара"  # сломанное слово — без ударения, фраза цела

    class Broken:
        def process_all(self, text):
            raise ValueError("совсем сломалось")

    acc._acc = Broken()
    assert acc("привет") == "привет"


def test_load_voices_with_several_refs(tmp_path):
    d = tmp_path / "briar"
    d.mkdir()
    for name, text in (("ref", "спокойно"), ("ref2", "КРОООВЬ"), ("ref3", "ещё")):
        (d / f"{name}.wav").write_bytes(b"")
        (d / f"{name}.txt").write_text(text, encoding="utf-8")
    v = load_voices(tmp_path)[0]
    assert [t for _, t in v.refs] == ["спокойно", "КРОООВЬ", "ещё"]
    picked = {v.pick_ref(random.Random(i))[1] for i in range(30)}
    assert picked == {"спокойно", "КРОООВЬ", "ещё"}


def test_role_voices_owner_and_mods_and_reserved_from_viewers():
    vs = [Voice(id=i, name=i, ref_wav=Path(f"{i}.wav"), ref_text="") for i in ("illidan", "arthas", "briar", "vaas")]
    p = VoicePicker(vs, rng=random.Random(3), role_voices={"broadcaster": "illidan", "moderator": "arthas", "vip": ""})
    assert p.for_role("kelhohn", "broadcaster").id == "illidan"
    assert p.for_role("any_mod", "moderator").id == "arthas"
    assert p.for_role("other_mod", "moderator").id == "arthas"
    assert p.for_role("vip1", "vip").id == p.for_role("vip1", "vip").id  # VIP — свой постоянный
    # зрителям не выпадают голоса стримера и модеров
    assert {p.random_voice().id for _ in range(40)} == {"briar", "vaas"}
    # ник из moderator_voices важнее роли
    p2 = VoicePicker(vs, moderator_voices={"special": "vaas"}, role_voices={"moderator": "arthas"})
    assert p2.for_role("special", "moderator").id == "vaas"


def test_catchphrases_choose(tmp_path):
    from voicebot.catchphrases import choose, load_catchphrases

    (tmp_path / "c.toml").write_text('[briar]\naliases = ["брайер"]\nphrases = ["КРОООВЬ!", "Вся эта кровь мне!"]\n'
                                     '[ghost]\nphrases = ["нет такого голоса"]\n', encoding="utf-8")
    vs = [Voice(id="briar", name="Брайер", ref_wav=Path("b.wav"), ref_text=""),
          Voice(id="johnny", name="Джонни Сильверхенд", ref_wav=Path("j.wav"), ref_text="")]
    cp = load_catchphrases(tmp_path / "c.toml", vs)
    assert "ghost" not in cp.phrases
    rng = random.Random(1)
    vid, text = choose("Брайер", cp, rng)
    assert vid == "briar" and text in ("КРОООВЬ!", "Вся эта кровь мне!")
    assert choose("брайер: привет чат", cp) == ("briar", "привет чат")
    assert choose("джонни: проснись", cp) == ("johnny", "проснись")  # первое слово подписи
    assert choose("johnny", cp) == (None, "johnny")  # реплик нет — просто слово
    assert choose("фраза", cp, rng)[0] == "briar"
    assert choose("просто текст: с двоеточием", cp) == (None, "просто текст: с двоеточием")


def test_tts_with_character_name_uses_that_voice():
    async def go():
        bot, overlay = make_bot()
        from voicebot.catchphrases import Catchphrases

        bot.catchphrases = Catchphrases(aliases={"voice1": "v1"}, phrases={"v1": ["КРОООВЬ!"]})
        await bot.handle_event(msg("!tts voice1", first=False, mod=True, login="m", mid="1"))
        await bot.handle_event(msg("!tts voice1: свой текст", first=False, mod=True, login="m", mid="2"))
        return [(i.voice.id, i.text) for i in bot.pending]

    assert asyncio.run(go()) == [("v1", "КРОООВЬ!"), ("v1", "свой текст")]


def test_fish_engine_uses_fish_id_or_own_sample(tmp_path, monkeypatch):
    pytest.importorskip("fishaudio")
    from voicebot.audio import to_wav_bytes
    from voicebot.config import EngineConfig
    from voicebot.engines import FishEngine

    calls = []

    class FakeTTS:
        def convert(self, **kw):
            calls.append(kw)
            return to_wav_bytes(np.zeros(4410, dtype=np.float32), 44100)

    eng = FishEngine(EngineConfig(name="fish", fish_api_key="test-key"))
    eng.client = type("FakeClient", (), {"tts": FakeTTS()})()
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"RIFF")
    wav, sr = eng.synth("привет", Voice(id="a", name="A", ref_wav=ref, ref_text="текст", fish_id="abc123"))
    assert sr == 44100 and wav.size == 4410
    assert calls[-1]["reference_id"] == "abc123" and calls[-1]["format"] == "wav"
    eng.synth("привет", Voice(id="b", name="B", ref_wav=ref, ref_text="текст"))
    assert "reference_id" not in calls[-1] and calls[-1]["references"][0].text == "текст"


def test_fish_voice_folder_without_ref_wav(tmp_path):
    d = tmp_path / "briar"
    d.mkdir()
    (d / "voice.toml").write_text('name = "Брайер"\nfish_id = "xyz"\n', encoding="utf-8")
    v = load_voices(tmp_path)[0]
    assert v.fish_id == "xyz" and v.name == "Брайер"


def test_fish_id_accepts_link_to_voice_page():
    from voicebot.voices import fish_id_from

    vid = "802e3bc2b27e49c2995d23ef70e6ac89"
    assert fish_id_from(f"https://fish.audio/m/{vid}/") == vid
    assert fish_id_from(f"https://fish.audio/ru/m/{vid.upper()}") == vid
    assert fish_id_from(f"  {vid} ") == vid
    assert fish_id_from(None) == ""
