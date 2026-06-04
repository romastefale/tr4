from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from aiogram import Bot

from app.security.managed_groups import is_managed_group, list_managed_groups, update_group_status

logger = logging.getLogger(__name__)

_CACHE_TTL = timedelta(seconds=60)


class BotRightsError(RuntimeError):
    """Raised when a moderation/governance action is blocked before Telegram call."""


@dataclass(frozen=True)
class BotRights:
    chat_id: int
    status: str
    is_admin: bool
    can_delete_messages: bool = False
    can_restrict_members: bool = False
    can_pin_messages: bool = False
    can_manage_tags: bool = False
    can_change_info: bool = False
    can_promote_members: bool = False
    can_invite_users: bool = False
    can_manage_topics: bool = False
    can_manage_video_chats: bool = False
    checked_at: datetime | None = None
    error: str | None = None

    @property
    def musical_only_reason(self) -> str | None:
        if self.error:
            return self.error
        if not self.is_admin:
            return "bot não é administrador neste grupo; modo musical-only"
        return None


_cache: dict[int, BotRights] = {}


def is_group_chat_id(chat_id: int | str | None) -> bool:
    try:
        return int(chat_id) < 0  # Telegram groups/supergroups are negative IDs.
    except (TypeError, ValueError):
        return False


def _normalize_status(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw).lower()
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text


def _bool_attr(obj: Any, name: str, *, default: bool = False) -> bool:
    return bool(getattr(obj, name, default))


def _rights_from_member(chat_id: int, member: Any) -> BotRights:
    status = _normalize_status(getattr(member, "status", "unknown"))
    is_creator = status in {"creator", "owner"}
    is_admin = is_creator or status == "administrator"
    if is_creator:
        return BotRights(
            chat_id=chat_id,
            status=status,
            is_admin=True,
            can_delete_messages=True,
            can_restrict_members=True,
            can_pin_messages=True,
            can_manage_tags=True,
            can_change_info=True,
            can_promote_members=True,
            can_invite_users=True,
            can_manage_topics=True,
            can_manage_video_chats=True,
            checked_at=datetime.now(timezone.utc),
        )
    return BotRights(
        chat_id=chat_id,
        status=status,
        is_admin=is_admin,
        can_delete_messages=_bool_attr(member, "can_delete_messages"),
        can_restrict_members=_bool_attr(member, "can_restrict_members"),
        can_pin_messages=_bool_attr(member, "can_pin_messages"),
        can_manage_tags=_bool_attr(member, "can_manage_tags"),
        can_change_info=_bool_attr(member, "can_change_info"),
        can_promote_members=_bool_attr(member, "can_promote_members"),
        can_invite_users=_bool_attr(member, "can_invite_users"),
        can_manage_topics=_bool_attr(member, "can_manage_topics"),
        can_manage_video_chats=_bool_attr(member, "can_manage_video_chats"),
        checked_at=datetime.now(timezone.utc),
    )


def _store_status(rights: BotRights) -> None:
    update_group_status(
        chat_id=rights.chat_id,
        bot_status=rights.status,
        can_delete_messages=rights.can_delete_messages,
        can_restrict_members=rights.can_restrict_members,
        can_pin_messages=rights.can_pin_messages,
        can_manage_tags=rights.can_manage_tags,
        can_change_info=rights.can_change_info,
        can_promote_members=rights.can_promote_members,
        can_invite_users=rights.can_invite_users,
        can_manage_topics=rights.can_manage_topics,
        can_manage_video_chats=rights.can_manage_video_chats,
        last_error=rights.error,
    )


async def get_bot_rights(bot: Bot, chat_id: int, *, force_refresh: bool = False) -> BotRights:
    now = datetime.now(timezone.utc)
    cached = _cache.get(int(chat_id))
    if (
        cached is not None
        and not force_refresh
        and cached.checked_at is not None
        and now - cached.checked_at <= _CACHE_TTL
    ):
        return cached
    try:
        me = await bot.get_me()
        member = await bot.get_chat_member(chat_id=int(chat_id), user_id=me.id)
        rights = _rights_from_member(int(chat_id), member)
    except Exception as exc:
        logger.warning("BOT_RIGHTS_LOOKUP_FAILED | chat_id=%s | %s", chat_id, exc)
        rights = BotRights(
            chat_id=int(chat_id),
            status="unknown",
            is_admin=False,
            checked_at=now,
            error=f"falha ao consultar permissões do bot: {type(exc).__name__}",
        )
    _cache[int(chat_id)] = rights
    try:
        _store_status(rights)
    except Exception:
        logger.exception("BOT_RIGHTS_STATUS_STORE_FAILED | chat_id=%s", chat_id)
    return rights


def _capability_allowed(rights: BotRights, capability: str) -> bool:
    if capability == "admin":
        return rights.is_admin
    if capability == "delete":
        return rights.is_admin and rights.can_delete_messages
    if capability == "restrict":
        return rights.is_admin and rights.can_restrict_members
    if capability == "pin":
        return rights.is_admin and rights.can_pin_messages
    if capability == "tags":
        return rights.is_admin and rights.can_manage_tags
    if capability == "change_info":
        return rights.is_admin and rights.can_change_info
    if capability == "invite":
        return rights.is_admin and rights.can_invite_users
    if capability == "topics":
        return rights.is_admin and rights.can_manage_topics
    return False


def _capability_label(capability: str) -> str:
    return {
        "admin": "ser administrador",
        "delete": "can_delete_messages",
        "restrict": "can_restrict_members",
        "pin": "can_pin_messages",
        "tags": "can_manage_tags",
        "change_info": "can_change_info",
        "invite": "can_invite_users",
        "topics": "can_manage_topics",
    }.get(capability, capability)


async def check_group_capability(
    bot: Bot,
    chat_id: int | str,
    capability: str,
) -> tuple[bool, str, BotRights | None]:
    if not is_group_chat_id(chat_id):
        return True, "não é grupo", None
    cid = int(chat_id)
    if not is_managed_group(cid):
        return False, "grupo não está na lista de grupos gerenciados", None
    rights = await get_bot_rights(bot, cid)
    if not rights.is_admin:
        return False, rights.musical_only_reason or "bot não é administrador", rights
    if not _capability_allowed(rights, capability):
        return False, f"bot não possui {_capability_label(capability)} neste grupo", rights
    return True, "ok", rights


async def require_group_capability(bot: Bot, chat_id: int | str, capability: str) -> None:
    allowed, reason, _rights = await check_group_capability(bot, chat_id, capability)
    if not allowed:
        raise BotRightsError(reason)


def bot_rights_capabilities(rights: BotRights | None) -> set[str]:
    """Capacidades operacionais derivadas do status Telegram real."""
    if rights is None or not rights.is_admin:
        return set()
    caps: set[str] = {"admin"}
    if rights.can_delete_messages:
        caps.add("delete")
    if rights.can_restrict_members:
        caps.add("restrict")
    if rights.can_pin_messages:
        caps.add("pin")
    if rights.can_manage_tags:
        caps.add("tags")
    if rights.can_change_info:
        caps.add("change_info")
    if rights.can_invite_users:
        caps.add("invite")
    if rights.can_manage_topics:
        caps.add("topics")
    if rights.can_manage_video_chats:
        caps.add("video_chats")
    if rights.can_promote_members:
        caps.add("promote")
    return caps


def bot_rights_payload(rights: BotRights | None) -> dict[str, Any]:
    if rights is None:
        return {"ok": False, "status": "unknown", "capabilities": []}
    return {
        "ok": not bool(rights.error),
        "chat_id": rights.chat_id,
        "status": rights.status,
        "is_admin": rights.is_admin,
        "capabilities": sorted(bot_rights_capabilities(rights)),
        "can_delete_messages": rights.can_delete_messages,
        "can_restrict_members": rights.can_restrict_members,
        "can_pin_messages": rights.can_pin_messages,
        "can_manage_tags": rights.can_manage_tags,
        "can_change_info": rights.can_change_info,
        "can_promote_members": rights.can_promote_members,
        "can_invite_users": rights.can_invite_users,
        "can_manage_topics": rights.can_manage_topics,
        "can_manage_video_chats": rights.can_manage_video_chats,
        "checked_at": rights.checked_at.isoformat() if rights.checked_at else None,
        "error": rights.error,
    }


def format_bot_rights(rights: BotRights | None) -> str:
    """Linha humana curta para painel privado."""
    if rights is None:
        return "Direitos do bot: grupo não selecionado."
    if rights.error:
        return f"{rights.chat_id}: erro ao consultar ({rights.error})"
    if not rights.is_admin:
        return f"{rights.chat_id}: status={rights.status}; modo musical-only"
    caps = bot_rights_capabilities(rights)
    labels = []
    for cap, label in (
        ("delete", "apagar"),
        ("restrict", "ban/mute"),
        ("pin", "fixar"),
        ("tags", "tags"),
        ("change_info", "info"),
        ("invite", "convites"),
        ("topics", "tópicos"),
    ):
        labels.append(f"{label}={'sim' if cap in caps else 'não'}")
    return f"{rights.chat_id}: admin; " + ", ".join(labels)


async def refresh_managed_group_rights(bot: Bot, *, limit: int = 50) -> dict[str, Any]:
    """Força refresh dos direitos reais do bot nos grupos gerenciados.

    Não altera grants internos. Apenas consulta Telegram, atualiza cache/status e
    retorna resumo para o painel de Segurança.
    """
    groups = [g for g in list_managed_groups(limit=limit) if int(g.get("enabled") or 0) == 1]
    rows: list[dict[str, Any]] = []
    for group in groups:
        chat_id = int(group["chat_id"])
        rights = await get_bot_rights(bot, chat_id, force_refresh=True)
        row = bot_rights_payload(rights)
        row["title"] = group.get("title")
        rows.append(row)
    return {
        "total": len(rows),
        "admin": sum(1 for row in rows if row.get("is_admin")),
        "musical_only": sum(1 for row in rows if not row.get("is_admin") and not row.get("error")),
        "error": sum(1 for row in rows if row.get("error")),
        "rows": rows,
    }


def format_rights_refresh_report(result: dict[str, Any], *, max_rows: int = 20) -> str:
    lines = [
        "Direitos reais do bot — diagnóstico",
        "",
        f"Total: {result.get('total', 0)}",
        f"Admin: {result.get('admin', 0)}",
        f"Musical-only: {result.get('musical_only', 0)}",
        f"Erro: {result.get('error', 0)}",
        "",
        "Grupos:",
    ]
    for row in list(result.get("rows") or [])[:max_rows]:
        if row.get("error"):
            lines.append(f"- {row.get('chat_id')} — erro: {row.get('error')}")
            continue
        if not row.get("is_admin"):
            lines.append(f"- {row.get('chat_id')} — status={row.get('status')} — musical-only")
            continue
        caps = set(row.get("capabilities") or [])
        labels = []
        for cap, label in (
            ("delete", "apagar"),
            ("restrict", "ban/mute"),
            ("pin", "fixar"),
            ("change_info", "info"),
            ("invite", "convites"),
        ):
            labels.append(f"{label}:{'sim' if cap in caps else 'não'}")
        lines.append(f"- {row.get('chat_id')} — admin — " + ", ".join(labels))
    remaining = int(result.get("total", 0)) - max_rows
    if remaining > 0:
        lines.append(f"... +{remaining} grupos omitidos.")
    return "\n".join(lines)


def clear_bot_rights_cache(chat_id: int | str | None = None) -> None:
    if chat_id is None:
        _cache.clear()
        return
    try:
        _cache.pop(int(chat_id), None)
    except (TypeError, ValueError):
        return
