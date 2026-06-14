from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aiogram.types import Chat, User, Message
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import settings
from app.db.database import engine as default_engine
from app.bot.music_groups import remember_group
from app.equalizador.identity import make_ui_ref, display_name_from_telegram_user
from app.equalizador.palcos import ensure_equalizador_tables, upsert_operador
from app.equalizador.mesa import ensure_phase5_tables, register_mensagem_ref, register_alvo_ref


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def safe_label(value: object, *, fallback: str = "Grupo") -> str:
    text_value = str(value or "").strip().replace("@", "")
    return text_value[:120] or fallback


def _positive_int(value: object, *, default: int, minimum: int = 1, maximum: int = 100000) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = int(default)
    return max(int(minimum), min(int(maximum), number))


def x9_message_ttl_seconds() -> int:
    return _positive_int(getattr(settings, "TR4_FSM_X9_MESSAGE_TTL_SECONDS", 46 * 60 * 60), default=46 * 60 * 60, minimum=60, maximum=7 * 24 * 60 * 60)


def x9_message_cutoff_unix() -> int:
    return now_unix() - x9_message_ttl_seconds()


def x9_max_messages_per_group() -> int:
    return _positive_int(getattr(settings, "TR4_FSM_X9_MAX_MESSAGES_PER_GROUP", 200), default=200, minimum=20, maximum=1000)


def x9_summary_max_chars() -> int:
    return _positive_int(getattr(settings, "TR4_FSM_X9_SUMMARY_MAX_CHARS", 80), default=80, minimum=24, maximum=180)


def chat_is_group(chat: Chat | None) -> bool:
    return bool(chat and chat.type in {"group", "supergroup"})


def chat_is_private(chat: Chat | None) -> bool:
    return bool(chat and chat.type == "private")


def is_owner_user(user_id: int | None) -> bool:
    return bool(user_id is not None and int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET)


def is_operator_user(user_id: int | None) -> bool:
    if user_id is None:
        return False
    return int(user_id) in settings.TR4_EQUALIZADOR_MAESTRO_IDS_SET or int(user_id) in settings.TR4_EQUALIZADOR_OPERADOR_IDS_SET


def x9_group_capture_allowed(*, chat_id: int, db_engine: Engine = default_engine) -> bool:
    """Return whether passive X9 may retain context for a group.

    Default is conservative: unknown groups are not retained just because the bot
    saw a message. Context is retained when the group is explicitly allowed by
    TR4_EQUALIZADOR_PALCO_IDS, already enabled in eq_palcos, or the operator opted
    into automatic learning with TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS=true.
    """
    if int(chat_id) in settings.TR4_EQUALIZADOR_PALCO_IDS_SET:
        return True
    if bool(getattr(settings, "TR4_FSM_X9_CAPTURE_UNKNOWN_GROUPS", False)):
        return True
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text("SELECT 1 FROM eq_palcos WHERE telegram_chat_id=:chat_id AND habilitado=1 LIMIT 1"),
            {"chat_id": int(chat_id)},
        ).first()
    return bool(row)


def upsert_context_palco(*, chat: Chat, db_engine: Engine = default_engine, habilitado: int = 1) -> dict[str, object]:
    """Persist a group selected by private FSM or authorized X9 trigger."""
    ensure_equalizador_tables(db_engine)
    chat_id = int(chat.id)
    title = safe_label(getattr(chat, "title", None), fallback=f"Grupo {chat_id}")
    username = str(getattr(chat, "username", None) or "").strip() or None
    remember_group(chat_id=chat_id, title=title, username=username)
    ui_ref = make_ui_ref("grp", chat_id, settings.equalizador_alias_secret())
    enabled = 1 if int(habilitado) == 1 else 0
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_palcos (
                    telegram_chat_id, username, titulo, ui_label, ui_ref, habilitado, updated_at
                ) VALUES (
                    :chat_id, :username, :titulo, :ui_label, :ui_ref, :habilitado, :updated_at
                )
                ON CONFLICT(telegram_chat_id) DO UPDATE SET
                    username=excluded.username,
                    titulo=excluded.titulo,
                    ui_label=excluded.ui_label,
                    ui_ref=excluded.ui_ref,
                    habilitado=CASE WHEN excluded.habilitado=1 THEN 1 ELSE eq_palcos.habilitado END,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "chat_id": chat_id,
                "username": username,
                "titulo": title,
                "ui_label": title,
                "ui_ref": ui_ref,
                "habilitado": enabled,
                "updated_at": now_iso(),
            },
        )
    return {"telegram_chat_id": chat_id, "titulo": title, "ui_label": title, "ui_ref": ui_ref, "habilitado": enabled}


def upsert_context_operator(*, user: User, perfil: str = "Moderador") -> dict[str, object]:
    payload = {
        "id": int(user.id),
        "first_name": getattr(user, "first_name", None),
        "last_name": getattr(user, "last_name", None),
        "username": getattr(user, "username", None),
    }
    return upsert_operador(
        user_id=int(user.id),
        user=payload,
        perfil=perfil,
        alias_secret=settings.equalizador_alias_secret(),
    )


def message_summary(message: Message | None) -> str:
    if not message:
        return "Mensagem"
    raw = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
    if raw:
        return raw.replace("\n", " ")[: x9_summary_max_chars()]
    content_type = str(getattr(message, "content_type", "") or "").strip()
    return f"Mensagem {content_type}" if content_type else "Mensagem observada"


def prune_x9_context(*, chat_id: int, db_engine: Engine = default_engine) -> None:
    """Bound X9 storage by age and per-group count.

    Old rows are disabled instead of physically deleted so historical audit tables
    keep referential meaning while the private FSM stops surfacing stale context.
    """
    ensure_phase5_tables(db_engine)
    cutoff = x9_message_cutoff_unix()
    limit = x9_max_messages_per_group()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_mensagens
                SET habilitado=0, updated_at=:updated_at
                WHERE telegram_chat_id=:chat_id
                  AND habilitado=1
                  AND telegram_message_date IS NOT NULL
                  AND telegram_message_date < :cutoff
                """
            ),
            {"chat_id": int(chat_id), "cutoff": int(cutoff), "updated_at": now_iso()},
        )
        conn.execute(
            text(
                """
                UPDATE eq_mensagens
                SET habilitado=0, updated_at=:updated_at
                WHERE telegram_chat_id=:chat_id
                  AND habilitado=1
                  AND id NOT IN (
                      SELECT id FROM eq_mensagens
                      WHERE telegram_chat_id=:chat_id AND habilitado=1
                      ORDER BY COALESCE(telegram_message_date, 0) DESC, id DESC
                      LIMIT :limit
                  )
                """
            ),
            {"chat_id": int(chat_id), "limit": int(limit), "updated_at": now_iso()},
        )


def register_message_and_author(message: Message) -> tuple[str, str | None]:
    """Register a group message observed by X9 and return safe refs."""
    alias_secret = settings.equalizador_alias_secret()
    author_ref = None
    author = getattr(message, "from_user", None)
    if author and not getattr(author, "is_bot", False):
        author_ref = register_alvo_ref(
            chat_id=int(message.chat.id),
            user_id=int(author.id),
            nome_publico=display_name_from_telegram_user(
                {
                    "first_name": getattr(author, "first_name", None),
                    "last_name": getattr(author, "last_name", None),
                    "username": getattr(author, "username", None),
                }
            ),
            username=getattr(author, "username", None),
            alias_secret=alias_secret,
        )
    msg_ref = register_mensagem_ref(
        chat_id=int(message.chat.id),
        message_id=int(message.message_id),
        resumo_publico=message_summary(message),
        alias_secret=alias_secret,
        message_unix_time=int(message.date.timestamp()) if getattr(message, "date", None) else None,
        autor_user_id=int(author.id) if author and not getattr(author, "is_bot", False) else None,
        autor_nome_publico=display_name_from_telegram_user(
            {
                "first_name": getattr(author, "first_name", None),
                "last_name": getattr(author, "last_name", None),
                "username": getattr(author, "username", None),
            }
        ) if author and not getattr(author, "is_bot", False) else None,
        autor_username=getattr(author, "username", None) if author and not getattr(author, "is_bot", False) else None,
    )
    prune_x9_context(chat_id=int(message.chat.id))
    return msg_ref, author_ref


def record_group_message_context(message: Message | None, *, allow_unknown_group: bool = False) -> tuple[str | None, str | None]:
    """X9 contextual capture for private FSM; automatic DDX/X9 is separate.

    This function must never send anything to the group and must not be used as the policy engine for automatic DDX. It only stores bounded context so
    private /tmod can operate without exposing menus in the group.
    """
    if not message or not chat_is_group(getattr(message, "chat", None)):
        return None, None
    chat_id = int(message.chat.id)
    if not allow_unknown_group and not x9_group_capture_allowed(chat_id=chat_id):
        return None, None
    upsert_context_palco(chat=message.chat, habilitado=1)
    if getattr(getattr(message, "from_user", None), "is_bot", False):
        prune_x9_context(chat_id=chat_id)
        return None, None
    return register_message_and_author(message)


def list_known_groups(*, limit: int = 20, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT telegram_chat_id, titulo, ui_label, username, ui_ref, updated_at
                FROM eq_palcos
                WHERE habilitado=1
                ORDER BY updated_at DESC
                LIMIT :limit
                """
            ),
            {"limit": int(limit)},
        ).mappings().all()
    return [dict(row) for row in rows]


def get_group_by_ref(*, grp_ref: str, db_engine: Engine = default_engine) -> dict[str, object] | None:
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_chat_id, titulo, ui_label, username, ui_ref, habilitado
                FROM eq_palcos
                WHERE ui_ref=:ui_ref AND habilitado=1
                LIMIT 1
                """
            ),
            {"ui_ref": str(grp_ref)},
        ).mappings().first()
    return dict(row) if row else None


def list_recent_messages(*, chat_id: int, limit: int = 10, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_phase5_tables(db_engine)
    prune_x9_context(chat_id=int(chat_id), db_engine=db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    m.ui_ref AS msg_ref,
                    m.resumo_publico AS resumo,
                    m.autor_ref AS autor_ref,
                    m.telegram_message_date AS message_date,
                    m.updated_at AS updated_at,
                    a.nome_publico AS autor_nome,
                    a.username AS autor_username
                FROM eq_mensagens m
                LEFT JOIN eq_alvos a ON a.ui_ref = m.autor_ref
                WHERE m.telegram_chat_id=:chat_id
                  AND m.habilitado=1
                  AND m.telegram_message_date IS NOT NULL
                  AND m.telegram_message_date >= :cutoff
                ORDER BY m.telegram_message_date DESC, m.updated_at DESC
                LIMIT :limit
                """
            ),
            {"chat_id": int(chat_id), "limit": int(limit), "cutoff": int(x9_message_cutoff_unix())},
        ).mappings().all()
    return [dict(row) for row in rows]


async def user_can_operate_group(bot: Any, *, chat_id: int, user_id: int | None) -> bool:
    """Owner, configured operator or Telegram group admin can operate private FSM actions."""
    if user_id is None:
        return False
    if is_operator_user(int(user_id)):
        return True
    try:
        member = await bot.get_chat_member(chat_id=int(chat_id), user_id=int(user_id))
        status = str(getattr(member, "status", "") or "").lower()
        return status in {"creator", "administrator"}
    except Exception:
        return False


def get_message_by_ref(*, msg_ref: str, db_engine: Engine = default_engine) -> dict[str, object] | None:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    m.telegram_chat_id AS telegram_chat_id,
                    m.ui_ref AS msg_ref,
                    m.resumo_publico AS resumo,
                    m.autor_ref AS autor_ref,
                    m.telegram_message_date AS message_date,
                    a.nome_publico AS autor_nome,
                    a.username AS autor_username
                FROM eq_mensagens m
                LEFT JOIN eq_alvos a ON a.ui_ref = m.autor_ref
                WHERE m.ui_ref=:msg_ref
                  AND m.habilitado=1
                  AND m.telegram_message_date IS NOT NULL
                  AND m.telegram_message_date >= :cutoff
                LIMIT 1
                """
            ),
            {"msg_ref": str(msg_ref), "cutoff": int(x9_message_cutoff_unix())},
        ).mappings().first()
    return dict(row) if row else None
