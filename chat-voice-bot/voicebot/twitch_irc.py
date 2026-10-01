"""Минимальный клиент чата Twitch по IRC (TLS).

IRC выбран вместо EventSub, потому что только в IRC есть тег first-msg=1 —
признак первого сообщения зрителя на канале («ФМ»). Анонимное подключение
(justinfan) читает чат без токена.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import AsyncIterator

log = logging.getLogger(__name__)

HOST = "irc.chat.twitch.tv"
PORT = 6697

_TAG_UNESCAPE = {":": ";", "s": " ", "\\": "\\", "r": "\r", "n": "\n"}


def _unescape_tag(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            out.append(_TAG_UNESCAPE.get(value[i + 1], value[i + 1]))
            i += 2
            continue
        if ch != "\\":
            out.append(ch)
        i += 1
    return "".join(out)


@dataclass
class IrcLine:
    tags: dict[str, str] = field(default_factory=dict)
    prefix: str = ""
    command: str = ""
    params: list[str] = field(default_factory=list)

    @property
    def nick(self) -> str:
        return self.prefix.split("!", 1)[0]


def parse_line(line: str) -> IrcLine:
    msg = IrcLine()
    rest = line.rstrip("\r\n")
    if rest.startswith("@"):
        raw_tags, rest = rest[1:].split(" ", 1)
        for item in raw_tags.split(";"):
            key, _, value = item.partition("=")
            msg.tags[key] = _unescape_tag(value)
    if rest.startswith(":"):
        msg.prefix, rest = rest[1:].split(" ", 1)
    trailing = None
    if " :" in rest:
        rest, trailing = rest.split(" :", 1)
    parts = rest.split()
    msg.command = parts[0] if parts else ""
    msg.params = parts[1:]
    if trailing is not None:
        msg.params.append(trailing)
    return msg


@dataclass
class ChatMessage:
    id: str
    login: str
    display_name: str
    text: str
    first_message: bool
    is_moderator: bool
    is_broadcaster: bool
    is_vip: bool


@dataclass
class Moderation:
    """CLEARMSG/CLEARCHAT: удалить сообщение, сообщения пользователя или весь чат."""

    message_id: str = ""
    login: str = ""
    clear_all: bool = False


def to_event(line: IrcLine) -> ChatMessage | Moderation | None:
    if line.command == "PRIVMSG" and len(line.params) >= 2:
        text = line.params[1]
        if text.startswith("\x01ACTION ") and text.endswith("\x01"):
            text = text[8:-1]
        badges = line.tags.get("badges", "")
        badge_names = {b.split("/", 1)[0] for b in badges.split(",") if b}
        login = line.nick.lower()
        return ChatMessage(
            id=line.tags.get("id", ""),
            login=login,
            display_name=line.tags.get("display-name") or login,
            text=text,
            first_message=line.tags.get("first-msg") == "1",
            is_moderator=line.tags.get("mod") == "1" or "moderator" in badge_names,
            is_broadcaster="broadcaster" in badge_names,
            is_vip="vip" in badge_names or line.tags.get("vip") == "1",
        )
    if line.command == "CLEARMSG":
        return Moderation(message_id=line.tags.get("target-msg-id", ""), login=line.tags.get("login", "").lower())
    if line.command == "CLEARCHAT":
        if len(line.params) >= 2:
            return Moderation(login=line.params[1].lower())
        return Moderation(clear_all=True)
    return None


class TwitchChat:
    def __init__(self, channel: str, login: str = "", oauth_token: str = ""):
        self.channel = channel.lstrip("#").lower()
        self.login = login.lower() if oauth_token else f"justinfan{random.randint(10000, 99999)}"
        self.token = oauth_token
        self._writer: asyncio.StreamWriter | None = None

    async def events(self) -> AsyncIterator[ChatMessage | Moderation]:
        """Бесконечный поток событий с автоматическим переподключением."""
        backoff = 1.0
        while True:
            try:
                async for event in self._session():
                    backoff = 1.0
                    yield event
            except (OSError, asyncio.IncompleteReadError, ConnectionError) as e:
                log.warning("Соединение с Twitch потеряно: %s", e)
            log.info("Переподключение через %.0f с", backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def _session(self) -> AsyncIterator[ChatMessage | Moderation]:
        reader, writer = await asyncio.open_connection(HOST, PORT, ssl=True)
        self._writer = writer
        try:
            await self._send("CAP REQ :twitch.tv/tags twitch.tv/commands")
            if self.token:
                token = self.token if self.token.startswith("oauth:") else f"oauth:{self.token}"
                await self._send(f"PASS {token}")
            await self._send(f"NICK {self.login}")
            await self._send(f"JOIN #{self.channel}")
            log.info("Подключено к чату #%s как %s", self.channel, self.login)
            while True:
                raw = await asyncio.wait_for(reader.readline(), timeout=360)
                if not raw:
                    raise ConnectionError("сервер закрыл соединение")
                line = parse_line(raw.decode("utf-8", errors="replace"))
                if line.command == "PING":
                    await self._send("PONG :" + (line.params[0] if line.params else "tmi.twitch.tv"))
                elif line.command == "RECONNECT":
                    raise ConnectionError("Twitch попросил переподключиться")
                elif line.command == "NOTICE" and "authentication failed" in " ".join(line.params).lower():
                    raise SystemExit("Twitch отклонил токен: проверьте [twitch] login/oauth_token")
                else:
                    event = to_event(line)
                    if event is not None:
                        yield event
        except asyncio.TimeoutError as e:
            raise ConnectionError("нет данных от Twitch 6 минут") from e
        finally:
            self._writer = None
            writer.close()

    async def say(self, text: str) -> None:
        """Ответ в чат — только при авторизованном подключении."""
        if self.token and self._writer is not None:
            await self._send(f"PRIVMSG #{self.channel} :{text}")

    async def _send(self, line: str) -> None:
        assert self._writer is not None
        self._writer.write((line + "\r\n").encode("utf-8"))
        await self._writer.drain()
