"""Configura o menu nativo de comandos do Telegram por escopo.

Objetivo da Fase 10B:

- comandos públicos continuam musicais;
- comandos sensíveis não aparecem no menu global;
- Owner recebe menu privado com /tigrao, /owner e /radio;
- moderadores legados recebem menu privado com /tigrao;
- grupos recebem apenas comandos seguros para uso público.

Observação: delegados dinâmicos `radio.*` são controlados pelo RBAC no runtime.
O Telegram não oferece um escopo "por permissão interna" automático, então o
menu deles é atualizado apenas se seus user_ids forem conhecidos por env/escopo.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
)

from app.config.settings import MODERATOR_IDS, ROOT_USER_ID

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
    CommandDef("lastfm", "Conectar Last.fm"),
    CommandDef("lastfmoff", "Desconectar Last.fm"),
    CommandDef("help", "Lista de comandos"),
    CommandDef("start", "Boas-vindas e instruções"),
)

_GROUP_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("playing", "Música tocando agora"),
    CommandDef("albnow", "Foco no álbum atual"),
    CommandDef("tcanvas", "Canvas do Spotify"),
    CommandDef("tstory", "Story da música tocando"),
    CommandDef("tly", "Canvas com trecho da letra"),
    CommandDef("radiofm", "Buscar e enviar uma música"),
    CommandDef("tnow", "Mosaico do grupo"),
    CommandDef("nowp", "Enviar sua música pra um grupo"),
    CommandDef("help", "Lista de comandos"),
)

_OWNER_PRIVATE_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("tigrao", "Entrada dos painéis"),
    CommandDef("owner", "Painel Owner"),
    CommandDef("radio", "Painel Radio"),
    CommandDef("btb", "Painel BTB"),
    *_PUBLIC_COMMANDS,
)

_MODERATION_PRIVATE_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("tigrao", "Entrada da moderação delegada"),
    *_PUBLIC_COMMANDS,
)

_RADIO_PRIVATE_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("tigrao", "Entrada dos painéis"),
    CommandDef("radio", "Painel Radio"),
    *_PUBLIC_COMMANDS,
)

_DELEGATE_PRIVATE_COMMANDS: tuple[CommandDef, ...] = (
    CommandDef("tigrao", "Entrada dos painéis delegados"),
    CommandDef("radio", "Painel Radio"),
    *_PUBLIC_COMMANDS,
)


def _to_bot_commands(commands: tuple[CommandDef, ...]) -> list[BotCommand]:
    return [BotCommand(command=item.command, description=item.description[:256]) for item in commands]


def private_commands_for_access(
    *,
    is_root: bool,
    has_delegate_access: bool,
    has_radio_access: bool | None = None,
) -> tuple[CommandDef, ...]:
    """Escolhe o menu privado sem consultar banco.

    A autorização real continua nos handlers. Esta função só decide UX do menu
    nativo conforme estado já resolvido. `has_delegate_access` significa que o
    usuário possui algum grant; `has_radio_access` permite ocultar /radio quando
    o grant é apenas de moderação.
    """
    if is_root:
        return _OWNER_PRIVATE_COMMANDS
    if has_delegate_access and bool(has_radio_access):
        return _DELEGATE_PRIVATE_COMMANDS
    if has_delegate_access:
        return _MODERATION_PRIVATE_COMMANDS
    if bool(has_radio_access):
        return _RADIO_PRIVATE_COMMANDS
    return _PUBLIC_COMMANDS


def private_command_names_for_access(
    *,
    is_root: bool,
    has_delegate_access: bool,
    has_radio_access: bool | None = None,
) -> list[str]:
    return [
        item.command
        for item in private_commands_for_access(
            is_root=is_root,
            has_delegate_access=has_delegate_access,
            has_radio_access=has_radio_access,
        )
    ]


def command_scope_summary() -> dict[str, object]:
    """Resumo determinístico para smoke tests e readiness/docs."""
    delegate_users = sorted({int(uid) for uid in MODERATOR_IDS if uid and int(uid) != int(ROOT_USER_ID or 0)})
    return {
        "public": [item.command for item in _PUBLIC_COMMANDS],
        "groups": [item.command for item in _GROUP_COMMANDS],
        "owner_private": [item.command for item in _OWNER_PRIVATE_COMMANDS],
        "moderation_private": [item.command for item in _MODERATION_PRIVATE_COMMANDS],
        "radio_private": [item.command for item in _RADIO_PRIVATE_COMMANDS],
        "delegate_private": [item.command for item in _DELEGATE_PRIVATE_COMMANDS],
        "root_user_id": int(ROOT_USER_ID or 0),
        "legacy_delegate_user_ids": delegate_users,
    }


async def _set_commands(bot: Bot, commands: tuple[CommandDef, ...], *, scope, label: str) -> bool:
    try:
        await bot.set_my_commands(_to_bot_commands(commands), scope=scope)
        logger.info("BOT_COMMANDS_SCOPE_SET | scope=%s | count=%s", label, len(commands))
        return True
    except Exception:
        logger.warning("BOT_COMMANDS_SCOPE_SET_FAILED | scope=%s", label, exc_info=True)
        return False


async def sync_user_command_scope(bot: Bot, user_id: int) -> dict[str, object]:
    """Sincroniza o menu nativo privado para um usuário específico.

    Usado após grants/revokes. Falhas são retornadas no payload e registradas,
    mas não devem reverter a operação de RBAC.
    """
    from app.security.permissions import has_any_grant, has_any_radio_permission, is_root_user

    uid = int(user_id)
    is_root = is_root_user(uid)
    has_radio_access = bool(has_any_radio_permission(uid))
    has_delegate_access = bool(has_any_grant(uid) or has_radio_access)
    commands = private_commands_for_access(
        is_root=is_root,
        has_delegate_access=has_delegate_access,
        has_radio_access=has_radio_access,
    )
    label = "owner" if is_root else "delegate_radio" if has_radio_access else "delegate" if has_delegate_access else "public"
    ok = await _set_commands(
        bot,
        commands,
        scope=BotCommandScopeChat(chat_id=uid),
        label=f"sync:{label}:{uid}",
    )
    return {
        "user_id": uid,
        "ok": ok,
        "scope": label,
        "commands": [item.command for item in commands],
    }


async def sync_active_grant_command_scopes(bot: Bot, *, include_root: bool = True) -> dict[str, object]:
    """Ressincroniza menus privados de todos os usuários com grants ativos.

    Também inclui Owner e moderadores legados quando configurados. Útil quando o
    menu nativo ficou desatualizado por falha temporária do Telegram ou mudança
    manual de permissões no banco.
    """
    from app.security.permissions import list_active_grant_user_ids

    user_ids = set(list_active_grant_user_ids())
    if include_root and ROOT_USER_ID:
        user_ids.add(int(ROOT_USER_ID))
    for user_id in MODERATOR_IDS:
        if user_id:
            user_ids.add(int(user_id))

    results = await sync_user_command_scopes(bot, sorted(user_ids))
    return {
        "total": len(results),
        "ok": sum(1 for row in results if row.get("ok")),
        "error": sum(1 for row in results if not row.get("ok")),
        "results": results,
    }


async def sync_user_command_scopes(bot: Bot, user_ids: set[int] | list[int] | tuple[int, ...]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for user_id in sorted({int(uid) for uid in user_ids if uid}):
        results.append(await sync_user_command_scope(bot, user_id))
    return results


async def setup_bot_commands(bot: Bot) -> None:
    """Registra comandos por escopo. Falhas não bloqueiam startup."""
    results: dict[str, bool] = {}

    results["default"] = await _set_commands(
        bot,
        _PUBLIC_COMMANDS,
        scope=BotCommandScopeDefault(),
        label="default",
    )
    results["all_groups"] = await _set_commands(
        bot,
        _GROUP_COMMANDS,
        scope=BotCommandScopeAllGroupChats(),
        label="all_groups",
    )

    if ROOT_USER_ID:
        results["owner_private"] = await _set_commands(
            bot,
            _OWNER_PRIVATE_COMMANDS,
            scope=BotCommandScopeChat(chat_id=int(ROOT_USER_ID)),
            label=f"owner:{ROOT_USER_ID}",
        )

    for user_id in sorted({int(uid) for uid in MODERATOR_IDS if uid and int(uid) != int(ROOT_USER_ID or 0)}):
        results[f"delegate:{user_id}"] = await _set_commands(
            bot,
            _DELEGATE_PRIVATE_COMMANDS,
            scope=BotCommandScopeChat(chat_id=user_id),
            label=f"delegate:{user_id}",
        )

    logger.info("BOT_COMMANDS_SETUP_DONE | results=%s", results)
