from __future__ import annotations

import contextvars
from contextvars import Token
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import text

from app.config.settings import MANAGED_GROUP_IDS, MODERATOR_IDS, ROOT_USER_ID
from app.db.database import engine

_current_actor_id: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "tr3_security_current_actor_id", default=None
)

_ANY_GRANT_CACHE: dict[int, tuple[bool, datetime]] = {}
_ANY_GRANT_CACHE_TTL_SECONDS = 60
_ANY_GRANT_CACHE_MAX = 1000

MODERATION_GRANT_PERMISSIONS: tuple[str, ...] = (
    "moderation.view",
    "moderation.delete",
    "moderation.warn",
    "moderation.mute",
    "moderation.ban",
    "moderation.unban",
    "moderation.reactions.delete",
    "moderation.reactions.delete_all_recent",
    "moderation.ddx.manage",
    "moderation.ddx_soft.manage",
    "moderation.tags.manage",
    "moderation.pinned.manage",
    "btb.use",
    "btb.allowlist.manage",
    "logs.read",
    "moderators.manage_group",
)

RADIO_GRANT_PERMISSIONS: tuple[str, ...] = (
    "radio.view",
    "radio.post_text",
    "radio.post_media",
    "radio.pin",
    "radio.templates.use",
    "radio.templates.manage",
    "radio.history.read",
    "radio.schedule",
    "radio.quiet_hours.manage",
    "radio.broadcast",
)

DELEGABLE_GRANT_PERMISSIONS: tuple[str, ...] = MODERATION_GRANT_PERMISSIONS + RADIO_GRANT_PERMISSIONS

OWNER_ONLY_PERMISSIONS: tuple[str, ...] = (
    "group.governance.view",
    "group.settings.change_info",
    "group.settings.change_title",
    "group.settings.change_photo",
    "group.settings.change_description",
    "group.admins.promote",
    "group.admins.demote",
    "group.admins.default_rights",
    "group.invites.create",
    "group.invites.revoke",
    "group.join_requests.manage_policy",
    "group.topics.manage",
    "group.video_chats.manage",
    "group.stories.manage",
    "group.channel_messages.manage",
    "group.direct_messages.manage",
    "group.default_permissions.manage",
    "security.panic_stop",
    "security.resume_global",
    "security.manage_config",
    "moderators.manage_global",
)

LEGACY_BOOTSTRAP_GRANTS: tuple[str, ...] = MODERATION_GRANT_PERMISSIONS


class PermissionDeniedError(PermissionError):
    """Raised before a Telegram call when actor lacks TR3 permission."""


class OwnerOnlyError(PermissionDeniedError):
    """Raised when a non-root actor attempts Owner-only governance."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def set_current_actor(user_id: int | None) -> Token[int | None]:
    return _current_actor_id.set(user_id)


def reset_current_actor(token: Token[int | None] | None) -> None:
    if token is not None:
        _current_actor_id.reset(token)


def get_current_actor() -> int | None:
    return _current_actor_id.get()


def is_root_user(user_id: int | None) -> bool:
    return bool(user_id and ROOT_USER_ID and int(user_id) == int(ROOT_USER_ID))


def _normalize_chat_id(chat_id: int | str | None) -> int | None:
    if chat_id is None:
        return None
    try:
        return int(chat_id)
    except (TypeError, ValueError):
        return None


def is_group_chat_id(chat_id: int | str | None) -> bool:
    cid = _normalize_chat_id(chat_id)
    return cid is not None and cid < 0


def ensure_tables() -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS moderation_grants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    permission TEXT NOT NULL,
                    granted_by_user_id INTEGER NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    expires_at DATETIME,
                    notes TEXT,
                    UNIQUE(user_id, chat_id, permission)
                );
                """
            )
        )
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_moderation_grants_user_id ON moderation_grants(user_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_moderation_grants_chat_id ON moderation_grants(chat_id)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_moderation_grants_permission ON moderation_grants(permission)"))


def _forget_any_grant_cache(user_id: int) -> None:
    _ANY_GRANT_CACHE.pop(int(user_id), None)

def _audit_rbac_event(
    *,
    action: str,
    status: str,
    user_id: int,
    chat_id: int,
    permission: str | None = None,
    actor_user_id: int | None = None,
    reason: str | None = None,
) -> None:
    try:
        from app.security.audit import log_audit_event

        log_audit_event(
            category="rbac",
            action=action,
            status=status,
            actor_user_id=actor_user_id,
            chat_id=int(chat_id),
            target_user_id=int(user_id),
            reason=reason,
            payload={"permission": permission} if permission else {},
        )
    except Exception:
        # Auditoria não pode quebrar o fluxo principal de permissão.
        return


def grant_permission(
    *,
    user_id: int,
    chat_id: int,
    permission: str,
    granted_by_user_id: int | None = None,
    enabled: bool = True,
    expires_at: datetime | None = None,
    notes: str | None = None,
) -> None:
    ensure_tables()
    if permission in OWNER_ONLY_PERMISSIONS:
        raise OwnerOnlyError(f"permissão Owner-only não pode ser delegada: {permission}")
    if permission not in DELEGABLE_GRANT_PERMISSIONS:
        raise PermissionDeniedError(f"permissão desconhecida ou não delegável: {permission}")
    _forget_any_grant_cache(user_id)
    now = utcnow()
    granter = granted_by_user_id or ROOT_USER_ID or 0
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO moderation_grants (
                    user_id, chat_id, permission, granted_by_user_id,
                    enabled, created_at, expires_at, notes
                ) VALUES (
                    :user_id, :chat_id, :permission, :granted_by_user_id,
                    :enabled, :created_at, :expires_at, :notes
                )
                ON CONFLICT(user_id, chat_id, permission) DO UPDATE SET
                    enabled = excluded.enabled,
                    expires_at = excluded.expires_at,
                    notes = COALESCE(excluded.notes, moderation_grants.notes)
                """
            ),
            {
                "user_id": int(user_id),
                "chat_id": int(chat_id),
                "permission": permission,
                "granted_by_user_id": int(granter),
                "enabled": 1 if enabled else 0,
                "created_at": now,
                "expires_at": expires_at,
                "notes": notes,
            },
        )
    _audit_rbac_event(
        action="grant",
        status="success",
        user_id=int(user_id),
        chat_id=int(chat_id),
        permission=permission,
        actor_user_id=int(granter),
    )


def revoke_permission(*, user_id: int, chat_id: int, permission: str) -> None:
    ensure_tables()
    _forget_any_grant_cache(user_id)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE moderation_grants
                SET enabled=0
                WHERE user_id=:user_id AND chat_id=:chat_id AND permission=:permission
                """
            ),
            {"user_id": int(user_id), "chat_id": int(chat_id), "permission": permission},
        )
    _audit_rbac_event(
        action="revoke",
        status="success",
        user_id=int(user_id),
        chat_id=int(chat_id),
        permission=permission,
        actor_user_id=get_current_actor(),
    )


def bootstrap_legacy_moderator_grants_from_env() -> None:
    """Create per-group grants for legacy TR3_SECOND/THIRD moderator IDs.

    Root remains implicit and does not need DB grants. This bootstrap is only
    for managed groups listed in TR3_MANAGED_GROUP_IDS and only for moderation
    permissions, never governance/Owner-only permissions.
    """
    ensure_tables()
    legacy_users = [uid for uid in MODERATOR_IDS if uid and uid != ROOT_USER_ID]
    if not legacy_users or not MANAGED_GROUP_IDS:
        return
    for uid in legacy_users:
        for chat_id in MANAGED_GROUP_IDS:
            for permission in LEGACY_BOOTSTRAP_GRANTS:
                grant_permission(
                    user_id=int(uid),
                    chat_id=int(chat_id),
                    permission=permission,
                    granted_by_user_id=ROOT_USER_ID or 0,
                    notes="bootstrap:legacy_moderator_env",
                )


def has_any_grant(user_id: int | None) -> bool:
    if not user_id:
        return False
    if is_root_user(user_id):
        return True
    uid = int(user_id)
    now = utcnow()
    cached = _ANY_GRANT_CACHE.get(uid)
    if cached is not None:
        value, cached_at = cached
        if (now - cached_at).total_seconds() <= _ANY_GRANT_CACHE_TTL_SECONDS:
            return value
    ensure_tables()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM moderation_grants
                WHERE user_id=:user_id AND enabled=1
                  AND (expires_at IS NULL OR expires_at > :now)
                LIMIT 1
                """
            ),
            {"user_id": uid, "now": now},
        ).first()
    value = row is not None
    if len(_ANY_GRANT_CACHE) >= _ANY_GRANT_CACHE_MAX:
        _ANY_GRANT_CACHE.clear()
    _ANY_GRANT_CACHE[uid] = (value, now)
    return value


def has_any_permission_prefix(user_id: int | None, prefix: str) -> bool:
    """True se o usuário tem qualquer grant ativo com o prefixo informado.

    Usado para expor painéis modulares, por exemplo `radio.` sem misturar
    permissões de moderação com permissões de postagem.
    """
    if not user_id:
        return False
    if is_root_user(user_id):
        return True
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM moderation_grants
                WHERE user_id=:user_id
                  AND permission LIKE :prefix
                  AND enabled=1
                  AND (expires_at IS NULL OR expires_at > :now)
                LIMIT 1
                """
            ),
            {"user_id": int(user_id), "prefix": f"{prefix}%", "now": now},
        ).first()
    return row is not None


def has_any_radio_permission(user_id: int | None) -> bool:
    return has_any_permission_prefix(user_id, "radio.")


def has_permission(user_id: int | None, chat_id: int | str | None, permission: str) -> bool:
    if is_root_user(user_id):
        return True
    if not user_id:
        return False
    if permission in OWNER_ONLY_PERMISSIONS:
        return False
    cid = _normalize_chat_id(chat_id)
    if cid is None:
        return False
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT 1 FROM moderation_grants
                WHERE user_id=:user_id
                  AND chat_id=:chat_id
                  AND permission=:permission
                  AND enabled=1
                  AND (expires_at IS NULL OR expires_at > :now)
                LIMIT 1
                """
            ),
            {"user_id": int(user_id), "chat_id": cid, "permission": permission, "now": now},
        ).first()
    return row is not None


def require_current_actor_permission(chat_id: int | str | None, permission: str) -> None:
    actor = get_current_actor()
    cid = _normalize_chat_id(chat_id)
    try:
        from app.security.panic import record_security_signal, should_block_delegate_actions

        if should_block_delegate_actions(is_root_user(actor)):
            record_security_signal(
                "permission.denied",
                reason=f"restricted mode blocks {permission}",
            )
            raise PermissionDeniedError(
                f"modo restrito bloqueia ação delegada {permission} no grupo {cid or chat_id or '-'}"
            )
    except PermissionDeniedError:
        raise
    except Exception:
        # Falha de leitura do modo de segurança não deve liberar permissão;
        # cai para a checagem RBAC normal abaixo.
        pass
    if has_permission(actor, chat_id, permission):
        return
    try:
        from app.security.panic import record_security_signal

        record_security_signal(
            "permission.denied",
            reason=f"actor={actor or '-'} permission={permission} chat={cid or chat_id or '-'}",
        )
    except Exception:
        pass
    raise PermissionDeniedError(
        f"ator {actor or '-'} sem permissão {permission} no grupo {cid or chat_id or '-'}"
    )


def require_current_actor_owner(action: str = "governance") -> None:
    actor = get_current_actor()
    if is_root_user(actor):
        return
    try:
        from app.security.panic import record_security_signal

        record_security_signal("permission.denied", reason=f"owner-only {action} actor={actor or '-'}")
    except Exception:
        pass
    raise OwnerOnlyError(f"ação Owner-only bloqueada para ator {actor or '-'}: {action}")


def list_user_grants(user_id: int) -> list[dict]:
    ensure_tables()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, user_id, chat_id, permission, granted_by_user_id,
                       enabled, created_at, expires_at, notes
                FROM moderation_grants
                WHERE user_id=:user_id
                ORDER BY chat_id, permission
                """
            ),
            {"user_id": int(user_id)},
        ).mappings().all()
    return [dict(row) for row in rows]


def list_chat_grants(chat_id: int) -> list[dict]:
    ensure_tables()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, user_id, chat_id, permission, granted_by_user_id,
                       enabled, created_at, expires_at, notes
                FROM moderation_grants
                WHERE chat_id=:chat_id
                ORDER BY user_id, permission
                """
            ),
            {"chat_id": int(chat_id)},
        ).mappings().all()
    return [dict(row) for row in rows]


def list_active_chat_grants(chat_id: int) -> list[dict]:
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, user_id, chat_id, permission, granted_by_user_id,
                       enabled, created_at, expires_at, notes
                FROM moderation_grants
                WHERE chat_id=:chat_id
                  AND enabled=1
                  AND (expires_at IS NULL OR expires_at > :now)
                ORDER BY user_id, permission
                """
            ),
            {"chat_id": int(chat_id), "now": now},
        ).mappings().all()
    return [dict(row) for row in rows]


def list_active_grant_user_ids() -> list[int]:
    """Usuários com pelo menos um grant ativo em qualquer grupo."""
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT DISTINCT user_id
                  FROM moderation_grants
                 WHERE enabled=1
                   AND (expires_at IS NULL OR expires_at > :now)
                 ORDER BY user_id
                """
            ),
            {"now": now},
        ).fetchall()
    return [int(row[0]) for row in rows]


def list_active_user_grants(user_id: int) -> list[dict]:
    """Grants ativos de um usuário em todos os grupos."""
    ensure_tables()
    now = utcnow()
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT id, user_id, chat_id, permission, granted_by_user_id,
                       enabled, created_at, expires_at, notes
                  FROM moderation_grants
                 WHERE user_id=:user_id
                   AND enabled=1
                   AND (expires_at IS NULL OR expires_at > :now)
                 ORDER BY chat_id, permission
                """
            ),
            {"user_id": int(user_id), "now": now},
        ).mappings().all()
    return [dict(row) for row in rows]


def grant_permissions(
    *,
    user_id: int,
    chat_id: int,
    permissions: Iterable[str],
    granted_by_user_id: int | None = None,
    notes: str | None = None,
) -> None:
    for permission in permissions:
        if permission in OWNER_ONLY_PERMISSIONS:
            raise OwnerOnlyError(f"permissão Owner-only não pode ser delegada: {permission}")
        if permission not in DELEGABLE_GRANT_PERMISSIONS:
            raise PermissionDeniedError(f"permissão desconhecida ou não delegável: {permission}")
        grant_permission(
            user_id=user_id,
            chat_id=chat_id,
            permission=permission,
            granted_by_user_id=granted_by_user_id,
            notes=notes,
        )


def revoke_permissions(*, user_id: int, chat_id: int, permissions: Iterable[str]) -> None:
    for permission in permissions:
        revoke_permission(user_id=user_id, chat_id=chat_id, permission=permission)


def revoke_all_chat_permissions(*, user_id: int, chat_id: int) -> int:
    active = list_active_chat_grants(chat_id)
    permissions = [row["permission"] for row in active if int(row["user_id"]) == int(user_id)]
    revoke_permissions(user_id=user_id, chat_id=chat_id, permissions=permissions)
    return len(permissions)


def moderation_full_permissions() -> tuple[str, ...]:
    return MODERATION_GRANT_PERMISSIONS


def radio_full_permissions() -> tuple[str, ...]:
    return RADIO_GRANT_PERMISSIONS


def delegable_full_permissions() -> tuple[str, ...]:
    return DELEGABLE_GRANT_PERMISSIONS
