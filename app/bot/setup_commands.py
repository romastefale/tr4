from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from app.config.settings import CODE_OWNER_IDS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandDef:
    command: str
    description: str


_PRIVATE_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("start", "Boas-vindas e conexão"),
    CommandDef("help", "Comandos disponíveis"),
    CommandDef("lastfm", "Conectar ou ver Last.fm"),
    CommandDef("lastfmoff", "Desconectar Last.fm"),
    CommandDef("login", "Conectar Spotify"),
    CommandDef("logout", "Desconectar Spotify"),
    CommandDef("playing", "Sua música tocando agora"),
    CommandDef("albnow", "Álbum da música atual"),
    CommandDef("tcanvas", "Canvas Spotify da música atual"),
    CommandDef("tstory", "Story da música atual"),
    CommandDef("tly", "Trecho de letra da música atual"),
    CommandDef("radiofm", "Buscar uma música"),
    CommandDef("nowp", "Enviar sua música para grupo"),
    CommandDef("myself", "Menu de extratos pessoais"),
    CommandDef("weekfm", "Extrato semanal Last.fm"),
    CommandDef("monthfm", "Extrato mensal Last.fm"),
)

_GROUP_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("help", "Comandos musicais do grupo"),
    CommandDef("lastfm", "Conectar ou ver Last.fm"),
    CommandDef("lastfmoff", "Desconectar Last.fm"),
    CommandDef("playing", "Sua música no grupo"),
    CommandDef("albnow", "Álbum da música atual"),
    CommandDef("tcanvas", "Canvas Spotify da música atual"),
    CommandDef("tstory", "Story da música atual"),
    CommandDef("tly", "Trecho de letra da música atual"),
    CommandDef("radiofm", "Buscar uma música no grupo"),
    CommandDef("tnow", "Mosaico de ouvintes do grupo"),
    CommandDef("myself", "Menu de extratos pessoais"),
    CommandDef("weekfm", "Extrato semanal Last.fm"),
    CommandDef("monthfm", "Extrato mensal Last.fm"),
    CommandDef("songcharts", "Ranking musical do grupo"),
)

_OWNER_ONLY_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("tnowall", "Mosaico consolidado por DM"),
    CommandDef("songchartsall", "Ranking consolidado por DM"),
    CommandDef("weekall", "Ranking semanal consolidado"),
    CommandDef("monthall", "Ranking mensal consolidado"),
    CommandDef("tmn", "Cadastrar usuário Last.fm manualmente"),
    CommandDef("tpv", "Privacidade visual no mosaico"),
    CommandDef("onoff", "Silenciar usuários comuns"),
    CommandDef("legacy", "Restringir logins antigos"),
    CommandDef("listening", "Exportar logins salvos"),
)

_OWNER_PRIVATE_COMMANDS: tuple[CommandDef, ...] = _PRIVATE_COMMANDS + _OWNER_ONLY_COMMANDS

# Compatibilidade com testes e scripts antigos: "public" representa os comandos
# comuns de DM. Os escopos reais são private, group e owner_private.
_PUBLIC_COMMANDS = _PRIVATE_COMMANDS


def _to_bot_commands(commands: tuple[CommandDef, ...]) -> list[BotCommand]:
    return [BotCommand(command=item.command, description=item.description[:256]) for item in commands]


def command_scope_summary() -> dict[str, object]:
    return {
        "public": [item.command for item in _PUBLIC_COMMANDS],
        "private": [item.command for item in _PRIVATE_COMMANDS],
        "group": [item.command for item in _GROUP_COMMANDS],
        "owner_private": [item.command for item in _OWNER_PRIVATE_COMMANDS],
        "owner_only": [item.command for item in _OWNER_ONLY_COMMANDS],
    }


async def setup_bot_commands(bot: Bot) -> None:
    private_commands = _to_bot_commands(_PRIVATE_COMMANDS)
    group_commands = _to_bot_commands(_GROUP_COMMANDS)
    owner_commands = _to_bot_commands(_OWNER_PRIVATE_COMMANDS)
    try:
        await bot.set_my_commands(private_commands, scope=BotCommandScopeDefault())
        await bot.set_my_commands(private_commands, scope=BotCommandScopeAllPrivateChats())
        await bot.set_my_commands(group_commands, scope=BotCommandScopeAllGroupChats())
        logger.info(
            "BOT_COMMANDS_MUSIC_ONLY_SET | private=%s group=%s owner_ids=%s",
            len(private_commands),
            len(group_commands),
            len(CODE_OWNER_IDS),
        )
    except Exception:
        logger.warning("BOT_COMMANDS_MUSIC_ONLY_FAILED", exc_info=True)
        return

    for owner_id in CODE_OWNER_IDS:
        try:
            await bot.set_my_commands(owner_commands, scope=BotCommandScopeChat(chat_id=owner_id))
        except Exception:
            logger.warning("BOT_OWNER_COMMANDS_SET_FAILED", exc_info=True)
        else:
            logger.info("BOT_OWNER_COMMANDS_SET | count=%s", len(owner_commands))
