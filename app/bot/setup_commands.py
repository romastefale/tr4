from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandDef:
    command: str
    description: str


_PUBLIC_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("playing", "Música tocando agora"),
    CommandDef("albnow", "Álbum atual"),
    CommandDef("tcanvas", "Canvas do Spotify"),
    CommandDef("tstory", "Story da música"),
    CommandDef("tly", "Trecho com letra"),
    CommandDef("radiofm", "Buscar música"),
    CommandDef("tnow", "Mosaico do grupo"),
    CommandDef("nowp", "Enviar música ao grupo"),
    CommandDef("myself", "Extrato pessoal"),
    CommandDef("weekfm", "Resumo semanal"),
    CommandDef("monthfm", "Resumo mensal"),
    CommandDef("songcharts", "Ranking do grupo"),
    CommandDef("lastfm", "Conectar Last.fm"),
    CommandDef("lastfmoff", "Desconectar Last.fm"),
    CommandDef("login", "Conectar Spotify"),
    CommandDef("help", "Ajuda"),
    CommandDef("start", "Boas-vindas"),
)

_PRIVATE_COMMANDS: tuple[CommandDef, ...] = _PUBLIC_COMMANDS + (
    CommandDef("show", "Painel owner do Equalizador"),
    CommandDef("broadcast", "Broadcast musical owner"),
)


def _to_bot_commands(commands: tuple[CommandDef, ...]) -> list[BotCommand]:
    return [BotCommand(command=item.command, description=item.description[:256]) for item in commands]


def command_scope_summary() -> dict[str, object]:
    return {"public": [item.command for item in _PUBLIC_COMMANDS], "private": [item.command for item in _PRIVATE_COMMANDS]}


async def setup_bot_commands(bot: Bot) -> None:
    public_commands = _to_bot_commands(_PUBLIC_COMMANDS)
    private_commands = _to_bot_commands(_PRIVATE_COMMANDS)
    public_scopes = (
        BotCommandScopeDefault(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    )
    try:
        for scope in public_scopes:
            await bot.set_my_commands(public_commands, scope=scope)
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
        logger.info(
            "BOT_COMMANDS_SET | public=%s | private=%s | public_scopes=%s",
            len(public_commands),
            len(private_commands),
            len(public_scopes),
        )
    except Exception:
        logger.warning("BOT_COMMANDS_PUBLIC_FAILED", exc_info=True)
