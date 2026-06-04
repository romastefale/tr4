from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeDefault

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CommandDef:
    command: str
    description: str


_PUBLIC_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("playing", "Música tocando agora"),
    CommandDef("albnow", "Foco no álbum atual"),
    CommandDef("tcanvas", "Canvas do Spotify"),
    CommandDef("tstory", "Story da música tocando"),
    CommandDef("tly", "Canvas com trecho da letra"),
    CommandDef("radiofm", "Buscar e enviar uma música"),
    CommandDef("tnow", "Mosaico do grupo"),
    CommandDef("nowp", "Enviar sua música pra um grupo"),
    CommandDef("myself", "Seu extrato pessoal Last.fm"),
    CommandDef("weekfm", "Resumo semanal Last.fm"),
    CommandDef("monthfm", "Resumo mensal Last.fm"),
    CommandDef("songcharts", "Ranking musical do grupo"),
    CommandDef("lastfm", "Conectar Last.fm"),
    CommandDef("lastfmoff", "Desconectar Last.fm"),
    CommandDef("help", "Lista de comandos"),
    CommandDef("start", "Boas-vindas e instruções"),
)


def _to_bot_commands(commands: tuple[CommandDef, ...]) -> list[BotCommand]:
    return [BotCommand(command=item.command, description=item.description[:256]) for item in commands]


def command_scope_summary() -> dict[str, object]:
    return {"public": [item.command for item in _PUBLIC_COMMANDS]}


async def setup_bot_commands(bot: Bot) -> None:
    commands = _to_bot_commands(_PUBLIC_COMMANDS)
    try:
        await bot.set_my_commands(commands, scope=BotCommandScopeDefault())
        await bot.set_my_commands(commands, scope=BotCommandScopeAllGroupChats())
        logger.info("BOT_COMMANDS_MUSIC_ONLY_SET | count=%s", len(commands))
    except Exception:
        logger.warning("BOT_COMMANDS_MUSIC_ONLY_FAILED", exc_info=True)
