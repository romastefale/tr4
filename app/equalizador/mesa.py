from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.afinacao import fetch_bot_member_rights
from app.equalizador.identity import make_ui_ref, public_tme_url, safe_public_username
from app.equalizador.erros_telegram import sanitize_public_error, telegram_error_info_from_payload, telegram_error_payload
from app.equalizador.palcos import ensure_equalizador_tables, get_operador_public_by_ref


class MesaError(RuntimeError):
    """Raised when a Mesa adjustment cannot be executed."""


class MesaNotFoundError(MesaError):
    """Raised when a public alias cannot be resolved internally."""


class MesaRightError(MesaError):
    """Raised when the bot lacks the real Telegram right required."""


class MesaTelegramError(MesaError):
    """Raised when Telegram Bot API rejects a Mesa adjustment."""

    def __init__(self, description: str, *, error_info: object | None = None) -> None:
        public_detail = getattr(error_info, "public_detail", None) or sanitize_public_error(description, fallback="Telegram recusou a operação.")
        super().__init__(public_detail)
        self.description = public_detail
        self.info = error_info


class MesaTargetError(MesaError):
    """Raised when the selected member alias is not eligible for the adjustment."""

    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = _safe_error_text(description, fallback="alvo_indisponivel")


def mesa_error_public_detail(exc: BaseException) -> str:
    """Return a sanitized, operator-facing error message for Mesa failures.

    Compatibilidade de teste legado: Telegram recusou:
    """
    if isinstance(exc, MesaRightError):
        return "Permissão real do bot insuficiente."
    if isinstance(exc, MesaNotFoundError):
        return "Referência indisponível."
    if isinstance(exc, MesaTelegramError):
        return _safe_error_text(exc.description, fallback="Telegram recusou a operação.")
    if isinstance(exc, MesaTargetError):
        return _safe_error_text(exc.description, fallback="Alvo indisponível.")
    reason = _safe_error_text(exc, fallback="ajuste_falhou")
    known = {
        "token_indisponivel": "Token do bot indisponível.",
        "telegram_resposta_invalida": "Telegram retornou resposta inválida.",
        "ajuste_indisponivel": "Ajuste indisponível.",
        "ajuste_falhou": "Ajuste não concluído.",
    }
    return known.get(reason, "Ajuste não concluído.")


@dataclass(frozen=True)
class MesaActionSpec:
    ajuste: str
    canal_codigo: str
    telegram_method: str
    direito: str | None
    target_kind: str


ACTION_SPECS: dict[str, MesaActionSpec] = {
    "mensagens.enviar": MesaActionSpec("mensagens.enviar", "mensagens.enviar", "sendMessage", None, "palco"),
    "mensagens.apagar": MesaActionSpec("mensagens.apagar", "mensagens.apagar", "deleteMessage", "can_delete_messages", "mensagem"),
    "membros.silenciar": MesaActionSpec("membros.silenciar", "membros.silenciar", "restrictChatMember", "can_restrict_members", "alvo"),
    "membros.liberar": MesaActionSpec("membros.liberar", "membros.liberar", "restrictChatMember", "can_restrict_members", "alvo"),
    "membros.remover": MesaActionSpec("membros.remover", "membros.remover", "banChatMember", "can_restrict_members", "alvo"),
    "membros.reintegrar": MesaActionSpec("membros.reintegrar", "membros.reintegrar", "unbanChatMember", "can_restrict_members", "alvo"),
    "fixados.criar": MesaActionSpec("fixados.criar", "fixados.criar", "pinChatMessage", "can_pin_messages", "mensagem"),
    "fixados.remover": MesaActionSpec("fixados.remover", "fixados.remover", "unpinChatMessage", "can_pin_messages", "mensagem"),
    "convites.criar": MesaActionSpec("convites.criar", "convites.criar", "createChatInviteLink", "can_invite_users", "palco"),
}


TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _sqlite_column_exists(conn: Any, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
    return any(str(row.get("name")) == column for row in rows)


def _safe_text(value: object, *, fallback: str = "") -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return fallback
    return text_value.replace("@", "").strip()[:180] or fallback


def _safe_username(value: object) -> str | None:
    return safe_public_username(value) or None


def _safe_int(value: object, *, default: int = 0, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        number = int(str(value or "").strip() or default)
    except (TypeError, ValueError):
        number = int(default)
    if minimum is not None:
        number = max(int(minimum), number)
    if maximum is not None:
        number = min(int(maximum), number)
    return number


def _safe_error_text(value: object, *, fallback: str = "") -> str:
    text_value = _safe_text(value, fallback=fallback)
    text_value = re.sub(r"bot\d+:[A-Za-z0-9_-]+", "bot_token_oculto", text_value)
    text_value = re.sub(r"-?\d{6,}", "ref_oculta", text_value)
    return text_value[:220] or fallback


def _public_target_row(*, alvo_ref: str, nome: str, username: object = "", updated_at: str | None = None, situacao: str | None = None) -> dict[str, object]:
    safe_username = safe_public_username(username)
    return {
        "alvo_ref": str(alvo_ref),
        "nome": _safe_text(nome, fallback="Membro"),
        "username": safe_username,
        "contato_url": public_tme_url(safe_username),
        "situacao": _safe_text(situacao, fallback="desconhecido"),
        "updated_at": str(updated_at or _now_iso()),
    }


def _public_message_row(*, msg_ref: str, resumo: str, message_date: int | None = None, updated_at: str | None = None) -> dict[str, object]:
    now_ts = _now_unix()
    age_seconds = None
    if message_date is not None:
        try:
            age_seconds = max(0, now_ts - int(message_date))
        except (TypeError, ValueError):
            age_seconds = None
    apagavel = True if age_seconds is None else age_seconds < 48 * 60 * 60
    return {
        "msg_ref": str(msg_ref),
        "resumo": _safe_text(resumo, fallback="Mensagem"),
        "updated_at": str(updated_at or _now_iso()),
        "idade_segundos": age_seconds,
        "apagavel": apagavel,
    }


async def _telegram_api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    if not token:
        raise MesaError("token_indisponivel")
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(url, json=payload or {})
    try:
        data = response.json()
    except ValueError as exc:
        raise MesaError("telegram_resposta_invalida") from exc
    if not response.is_success or not data.get("ok"):
        info = telegram_error_info_from_payload(data=data, status_code=response.status_code)
        # Compatibilidade de teste legado: raise MesaTelegramError(description)
        raise MesaTelegramError(info.public_detail, error_info=info)
    return data.get("result")


# Public alias used by feature modules that share Mesa Telegram calls.
telegram_api_call = _telegram_api_call


async def send_operator_dm(
    *,
    bot_token: str,
    user_id: int,
    text: str,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Try to send a private operational message to the Mini App operator.

    Telegram can reject the DM when the user never opened the bot privately or
    blocked it. The caller must keep the link visible in the Mini App regardless
    of this best-effort delivery result.
    """
    try:
        await telegram_api_call(
            bot_token,
            "sendMessage",
            {"chat_id": int(user_id), "text": _safe_text(text, fallback="Equalizador")[:4096], "disable_web_page_preview": True},
        )
        return {"enviado": True}
    except MesaError as exc:
        return {"enviado": False, "motivo": mesa_error_public_detail(exc)}


def _rights_from_member(member: dict[str, Any]) -> dict[str, bool]:
    status = str(member.get("status") or "").lower()
    keys = {
        "can_manage_chat",
        "can_delete_messages",
        "can_restrict_members",
        "can_invite_users",
        "can_pin_messages",
    }
    if status == "creator":
        return {key: True for key in keys}
    if status != "administrator":
        return {key: False for key in keys}
    return {key: bool(member.get(key) is True) for key in keys}


async def ensure_bot_right(
    *,
    bot_token: str,
    chat_id: int,
    required_right: str | None,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> None:
    if required_right is None:
        return
    member = await fetch_bot_member_rights(bot_token=bot_token, chat_id=chat_id, telegram_api_call=telegram_api_call)
    rights = _rights_from_member(member)
    if not rights.get(required_right, False):
        raise MesaRightError("afinação_insuficiente")


def ensure_phase5_tables(db_engine: Engine = default_engine) -> None:
    """Create action mapping and history tables used by the Mesa."""
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_alvos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id INTEGER NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    ui_ref TEXT NOT NULL UNIQUE,
                    username TEXT,
                    nome_publico TEXT NOT NULL,
                    telegram_status TEXT,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE (telegram_chat_id, telegram_user_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_mensagens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_chat_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    telegram_message_date INTEGER,
                    ui_ref TEXT NOT NULL UNIQUE,
                    resumo_publico TEXT,
                    habilitado INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL,
                    UNIQUE (telegram_chat_id, telegram_message_id)
                )
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS eq_historico (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    historico_ref TEXT NOT NULL UNIQUE,
                    ator_ref TEXT NOT NULL,
                    palco_ref TEXT NOT NULL,
                    alvo_ref TEXT,
                    ajuste TEXT NOT NULL,
                    status TEXT NOT NULL,
                    resumo_publico TEXT NOT NULL,
                    payload_tecnico_json TEXT,
                    created_at TEXT NOT NULL
                )
                """
            )
        )
        if not _sqlite_column_exists(conn, "eq_mensagens", "telegram_message_date"):
            conn.execute(text("ALTER TABLE eq_mensagens ADD COLUMN telegram_message_date INTEGER"))
        if not _sqlite_column_exists(conn, "eq_alvos", "username"):
            conn.execute(text("ALTER TABLE eq_alvos ADD COLUMN username TEXT"))
        if not _sqlite_column_exists(conn, "eq_alvos", "telegram_status"):
            conn.execute(text("ALTER TABLE eq_alvos ADD COLUMN telegram_status TEXT"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_alvos_ui_ref ON eq_alvos(ui_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_alvos_username ON eq_alvos(telegram_chat_id, username)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_mensagens_ui_ref ON eq_mensagens(ui_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_historico_palco_ref ON eq_historico(palco_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_historico_created_at ON eq_historico(created_at)"))


def register_alvo_ref(
    *,
    chat_id: int,
    user_id: int,
    nome_publico: str,
    alias_secret: str,
    username: str | None = None,
    telegram_status: str | None = None,
    db_engine: Engine = default_engine,
) -> str:
    """Register a target user seen internally and return its public alias.

    This helper is intentionally server-side. Public APIs must receive only the
    returned ``alvo_ref``; they must not accept raw Telegram user IDs.
    """
    ensure_phase5_tables(db_engine)
    ref_seed = f"{int(chat_id)}:{int(user_id)}"
    ui_ref = make_ui_ref("usr", ref_seed, alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_alvos (telegram_chat_id, telegram_user_id, ui_ref, username, nome_publico, telegram_status, habilitado, updated_at)
                VALUES (:chat_id, :user_id, :ui_ref, :username, :nome_publico, :telegram_status, 1, :updated_at)
                ON CONFLICT(telegram_chat_id, telegram_user_id) DO UPDATE SET
                    ui_ref=excluded.ui_ref,
                    username=COALESCE(excluded.username, eq_alvos.username),
                    nome_publico=excluded.nome_publico,
                    telegram_status=COALESCE(excluded.telegram_status, eq_alvos.telegram_status),
                    habilitado=1,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "chat_id": int(chat_id),
                "user_id": int(user_id),
                "ui_ref": ui_ref,
                "username": _safe_username(username),
                "nome_publico": _safe_text(nome_publico, fallback="Membro"),
                "telegram_status": _safe_text(telegram_status, fallback="") or None,
                "updated_at": _now_iso(),
            },
        )
    return ui_ref


def register_mensagem_ref(
    *,
    chat_id: int,
    message_id: int,
    resumo_publico: str,
    alias_secret: str,
    message_unix_time: int | None = None,
    db_engine: Engine = default_engine,
) -> str:
    """Register a message seen internally and return its public alias."""
    ensure_phase5_tables(db_engine)
    ref_seed = f"{int(chat_id)}:{int(message_id)}"
    ui_ref = "msg_" + make_ui_ref("grp", ref_seed, alias_secret).split("_", 1)[1]
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_mensagens (
                    telegram_chat_id, telegram_message_id, telegram_message_date, ui_ref, resumo_publico, habilitado, updated_at
                )
                VALUES (:chat_id, :message_id, :message_date, :ui_ref, :resumo_publico, 1, :updated_at)
                ON CONFLICT(telegram_chat_id, telegram_message_id) DO UPDATE SET
                    telegram_message_date=COALESCE(excluded.telegram_message_date, eq_mensagens.telegram_message_date),
                    ui_ref=excluded.ui_ref,
                    resumo_publico=excluded.resumo_publico,
                    habilitado=1,
                    updated_at=excluded.updated_at
                """
            ),
            {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "message_date": int(message_unix_time) if message_unix_time else None,
                "ui_ref": ui_ref,
                "resumo_publico": _safe_text(resumo_publico, fallback="Mensagem"),
                "updated_at": _now_iso(),
            },
        )
    return ui_ref



def _private_link_chat_candidates(raw_chat: str) -> list[int]:
    """Return plausible supergroup/channel IDs from a t.me/c link component.

    Telegram private message links normally use /c/<internal>/<message>, where
    the full chat id is -100<internal>. Operators sometimes paste the full id or
    the same value without the leading minus. We keep all plausible candidates
    and let the caller pick the one matching the selected palco.
    """
    value = str(raw_chat or "").strip()
    if not re.fullmatch(r"-?\d{5,20}", value):
        return []
    candidates: list[int] = []
    number = int(value)
    if value.startswith("-100"):
        candidates.append(number)
    elif value.startswith("100"):
        candidates.append(-number)
        candidates.append(int(f"-100{value}"))
    else:
        candidates.append(int(f"-100{value}"))
        candidates.append(-abs(number))
    unique: list[int] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _message_id_from_text(value: str) -> int | None:
    text_value = str(value or "").strip()
    if re.fullmatch(r"\d{1,12}", text_value):
        return int(text_value)
    return None


def parse_telegram_message_link(*, link: str, aliases: dict[str, int], expected_chat_id: int | None = None) -> tuple[int, int]:
    """Parse supported Telegram message references into chat/message IDs.

    Supported formats:
    - https://t.me/c/<internal_chat>/<message_id>
    - https://t.me/c/<internal_chat>/<topic_id>/<message_id>
    - https://t.me/<alias_or_public_username>/<message_id>
    - https://t.me/s/<alias_or_public_username>/<message_id>
    - tg://privatepost?channel=<internal_chat>&post=<message_id>
    - raw message id, when ``expected_chat_id`` is provided.

    The public API still receives only the original string; parsed IDs stay
    server-side and must match the selected palco.
    """
    value = str(link or "").strip()
    if not value:
        raise MesaTargetError("Informe o link ou número da mensagem.")
    raw_message_id = _message_id_from_text(value)
    if raw_message_id is not None:
        if expected_chat_id is None:
            raise MesaTargetError("Número de mensagem exige um palco selecionado.")
        return int(expected_chat_id), int(raw_message_id)

    parsed = urlparse(value)
    normalized_aliases = {str(name).lstrip("@").casefold(): int(chat_id) for name, chat_id in aliases.items()}

    if parsed.scheme == "tg" and parsed.netloc.lower() in {"privatepost", "post"}:
        query = parse_qs(parsed.query)
        channel = (query.get("channel") or query.get("chat") or [""])[0]
        post = (query.get("post") or query.get("message") or [""])[0]
        if not post.isdigit():
            raise MesaTargetError("Link tg:// sem número de mensagem.")
        candidates = _private_link_chat_candidates(channel)
        if expected_chat_id is not None:
            if int(expected_chat_id) in candidates:
                return int(expected_chat_id), int(post)
            raise MesaTargetError("Link pertence a outro palco.")
        if candidates:
            return candidates[0], int(post)
        raise MesaTargetError("Link tg:// com palco inválido.")

    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {"t.me", "telegram.me", "telegram.dog"}:
        raise MesaTargetError("Link de mensagem inválido.")
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0] == "s":
        parts = parts[1:]
    if len(parts) < 2:
        raise MesaTargetError("Link de mensagem incompleto.")
    message_part = parts[-1]
    if not message_part.isdigit():
        raise MesaTargetError("Link sem número de mensagem.")
    message_id = int(message_part)

    if parts[0] == "c":
        if len(parts) < 3:
            raise MesaTargetError("Link interno de mensagem incompleto.")
        candidates = _private_link_chat_candidates(parts[1])
        if expected_chat_id is not None:
            if int(expected_chat_id) in candidates:
                return int(expected_chat_id), message_id
            raise MesaTargetError("Link pertence a outro palco.")
        if candidates:
            return candidates[0], message_id
        raise MesaTargetError("Link interno de mensagem inválido.")

    alias = parts[0].lstrip("@").casefold()
    if alias not in normalized_aliases:
        raise MesaTargetError("Palco do link não está configurado no Equalizador.")
    chat_id = int(normalized_aliases[alias])
    if expected_chat_id is not None and int(chat_id) != int(expected_chat_id):
        raise MesaTargetError("Link pertence a outro palco.")
    return chat_id, message_id


def register_mensagem_from_link(
    *,
    palco_id: int,
    link: str,
    aliases: dict[str, int],
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    chat_id, message_id = parse_telegram_message_link(link=link, aliases=aliases, expected_chat_id=int(palco_id))
    msg_ref = register_mensagem_ref(
        chat_id=int(chat_id),
        message_id=int(message_id),
        resumo_publico="Mensagem marcada manualmente",
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return _public_message_row(msg_ref=msg_ref, resumo="Mensagem marcada manualmente")


def _normalize_manual_target_input(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() in {"t.me", "telegram.me", "telegram.dog"}:
        parts = [part for part in parsed.path.split("/") if part]
        if parts:
            return "@" + parts[0].lstrip("@")
    match = re.search(r"-?\d{4,20}", raw)
    if match and not raw.lstrip().startswith("@"):
        return match.group(0)
    return raw

def resolve_alvo_by_username(*, palco_id: int, username: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase5_tables(db_engine)
    safe_username = _safe_username(username)
    if not safe_username:
        raise MesaTargetError("Username inválido.")
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_user_id, ui_ref, nome_publico, username, telegram_status, updated_at
                FROM eq_alvos
                WHERE telegram_chat_id=:chat_id AND lower(username)=lower(:username) AND habilitado=1
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """
            ),
            {"chat_id": int(palco_id), "username": safe_username},
        ).mappings().first()
    if not row:
        raise MesaTargetError("Username ainda não reconhecido. Peça para a pessoa enviar mensagem no grupo ou use ID numérico.")
    return dict(row)


async def resolve_alvo_manual(
    *,
    palco_id: int,
    identificador: str,
    bot_token: str,
    alias_secret: str,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    """Resolve a manual target input into an internal ``alvo_ref``.

    Numeric IDs are verified with getChatMember. Usernames are supported only
    when the bot has already seen and stored the username inside the selected
    palco; Bot API does not provide a general username-to-user-id resolver.
    """
    raw = _normalize_manual_target_input(str(identificador or ""))
    if not raw:
        raise MesaTargetError("Informe ID numérico, @username ou link t.me/username.")
    if raw.startswith("usr_"):
        row = resolve_alvo_ref(palco_id=palco_id, alvo_ref=raw, db_engine=db_engine)
        user_id = int(row["telegram_user_id"])
        member = await telegram_api_call(bot_token, "getChatMember", {"chat_id": int(palco_id), "user_id": user_id})
    elif raw.startswith("@") or not re.fullmatch(r"-?\d{4,20}", raw):
        row = resolve_alvo_by_username(palco_id=palco_id, username=raw, db_engine=db_engine)
        user_id = int(row["telegram_user_id"])
        member = await telegram_api_call(bot_token, "getChatMember", {"chat_id": int(palco_id), "user_id": user_id})
    else:
        user_id = int(raw)
        member = await telegram_api_call(bot_token, "getChatMember", {"chat_id": int(palco_id), "user_id": user_id})
    if not isinstance(member, dict):
        raise MesaTargetError("Alvo não encontrado no grupo.")
    user = member.get("user") if isinstance(member.get("user"), dict) else {}
    first_name = str(user.get("first_name") or "").strip()
    last_name = str(user.get("last_name") or "").strip()
    nome = " ".join(part for part in [first_name, last_name] if part).strip() or "Membro"
    alvo_ref = register_alvo_ref(
        chat_id=int(palco_id),
        user_id=user_id,
        nome_publico=nome,
        username=str(user.get("username") or "") or None,
        telegram_status=_target_member_status(member),
        alias_secret=alias_secret,
        db_engine=db_engine,
    )
    return _public_target_row(alvo_ref=alvo_ref, nome=nome, username=user.get("username"), situacao=_target_member_status(member))


def resolve_alvo_ref(*, palco_id: int, alvo_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_user_id, ui_ref, nome_publico, username, telegram_status
                FROM eq_alvos
                WHERE telegram_chat_id=:chat_id AND ui_ref=:ui_ref AND habilitado=1
                """
            ),
            {"chat_id": int(palco_id), "ui_ref": str(alvo_ref)},
        ).mappings().first()
    if not row:
        raise MesaNotFoundError("alvo_indisponivel")
    return dict(row)


def resolve_mensagem_ref(*, palco_id: int, msg_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_message_id, telegram_message_date, ui_ref, resumo_publico
                FROM eq_mensagens
                WHERE telegram_chat_id=:chat_id AND ui_ref=:ui_ref AND habilitado=1
                """
            ),
            {"chat_id": int(palco_id), "ui_ref": str(msg_ref)},
        ).mappings().first()
    if not row:
        raise MesaNotFoundError("mensagem_indisponivel")
    return dict(row)


def mensagem_fora_da_janela_apagar(message: dict[str, object]) -> bool:
    """Return True when a message is known to be outside Telegram delete limits."""
    raw_date = message.get("telegram_message_date")
    if raw_date is None:
        return False
    try:
        age_seconds = max(0, _now_unix() - int(raw_date))
    except (TypeError, ValueError):
        return False
    return age_seconds >= 48 * 60 * 60


def mark_mensagem_inativa(*, palco_id: int, msg_ref: str, db_engine: Engine = default_engine) -> None:
    """Hide a message alias after successful deletion to prevent repeated action."""
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_mensagens
                SET habilitado=0, updated_at=:updated_at
                WHERE telegram_chat_id=:chat_id AND ui_ref=:ui_ref
                """
            ),
            {"chat_id": int(palco_id), "ui_ref": str(msg_ref), "updated_at": _now_iso()},
        )


def mark_alvo_status(
    *,
    palco_id: int,
    alvo_ref: str,
    telegram_status: str,
    db_engine: Engine = default_engine,
) -> None:
    """Persist the last known public-safe member state after a Mesa action."""
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_alvos
                SET telegram_status=:telegram_status, updated_at=:updated_at
                WHERE telegram_chat_id=:chat_id AND ui_ref=:ui_ref
                """
            ),
            {
                "chat_id": int(palco_id),
                "ui_ref": str(alvo_ref),
                "telegram_status": _safe_text(telegram_status, fallback="desconhecido"),
                "updated_at": _now_iso(),
            },
        )


def _history_ref(*, ator_ref: str, palco_ref: str, ajuste: str, created_at: str, alias_secret: str) -> str:
    seed = f"{ator_ref}:{palco_ref}:{ajuste}:{created_at}"
    return "his_" + make_ui_ref("grp", seed, alias_secret).split("_", 1)[1]


def record_historico(
    *,
    ator_ref: str,
    palco_ref: str,
    alvo_ref: str | None,
    ajuste: str,
    status: str,
    resumo_publico: str,
    payload_tecnico: dict[str, Any] | None,
    alias_secret: str,
    db_engine: Engine = default_engine,
) -> dict[str, object]:
    ensure_phase5_tables(db_engine)
    created_at = _now_iso()
    historico_ref = _history_ref(ator_ref=ator_ref, palco_ref=palco_ref, ajuste=ajuste, created_at=created_at, alias_secret=alias_secret)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO eq_historico (
                    historico_ref, ator_ref, palco_ref, alvo_ref, ajuste, status, resumo_publico,
                    payload_tecnico_json, created_at
                ) VALUES (
                    :historico_ref, :ator_ref, :palco_ref, :alvo_ref, :ajuste, :status, :resumo_publico,
                    :payload_tecnico_json, :created_at
                )
                """
            ),
            {
                "historico_ref": historico_ref,
                "ator_ref": ator_ref,
                "palco_ref": palco_ref,
                "alvo_ref": alvo_ref,
                "ajuste": ajuste,
                "status": status,
                "resumo_publico": _safe_text(resumo_publico, fallback="Ajuste registrado"),
                "payload_tecnico_json": json.dumps(payload_tecnico or {}, ensure_ascii=False, sort_keys=True),
                "created_at": created_at,
            },
        )
    return {
        "historico_ref": historico_ref,
        "ajuste": ajuste,
        "status": status,
        "resumo": _safe_text(resumo_publico, fallback="Ajuste registrado"),
        "created_at": created_at,
    }


def _public_target_by_ref(*, alvo_ref: object, db_engine: Engine) -> dict[str, object] | None:
    ref = str(alvo_ref or "").strip()
    if not ref:
        return None
    with db_engine.begin() as conn:
        if ref.startswith("usr_"):
            row = conn.execute(
                text(
                    """
                    SELECT ui_ref, nome_publico, username, telegram_status, updated_at
                    FROM eq_alvos
                    WHERE ui_ref=:ref
                    ORDER BY updated_at DESC, id DESC
                    LIMIT 1
                    """
                ),
                {"ref": ref},
            ).mappings().first()
            if row:
                return _public_target_row(
                    alvo_ref=str(row["ui_ref"]),
                    nome=str(row["nome_publico"] or "Membro"),
                    username=row["username"],
                    updated_at=str(row["updated_at"]),
                    situacao=str(row["telegram_status"] or "desconhecido"),
                )
        if ref.startswith("ent_"):
            try:
                row = conn.execute(
                    text(
                        """
                        SELECT ui_ref, nome_publico, username, estado, updated_at
                        FROM eq_join_requests
                        WHERE ui_ref=:ref
                        ORDER BY updated_at DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"ref": ref},
                ).mappings().first()
            except Exception:
                row = None
            if row:
                return {
                    "alvo_ref": str(row["ui_ref"]),
                    "nome": _safe_text(row["nome_publico"], fallback="Membro"),
                    "username": safe_public_username(row["username"]),
                    "contato_url": public_tme_url(row["username"]),
                    "situacao": str(row["estado"] or "pendente"),
                    "updated_at": str(row["updated_at"]),
                }
        if ref.startswith("snd_"):
            try:
                row = conn.execute(
                    text(
                        """
                        SELECT sender_ref, titulo_publico, username, updated_at
                        FROM eq_sender_chats
                        WHERE sender_ref=:ref
                        ORDER BY updated_at DESC, id DESC
                        LIMIT 1
                        """
                    ),
                    {"ref": ref},
                ).mappings().first()
            except Exception:
                row = None
            if row:
                return {
                    "alvo_ref": str(row["sender_ref"]),
                    "nome": _safe_text(row["titulo_publico"], fallback="Canal remetente"),
                    "username": safe_public_username(row["username"]),
                    "contato_url": public_tme_url(row["username"]),
                    "situacao": "canal remetente",
                    "updated_at": str(row["updated_at"]),
                }
    return None


def list_historico_publico(
    *,
    palco_refs: set[str],
    limit: int = 50,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    ensure_phase5_tables(db_engine)
    if not palco_refs:
        return []
    safe_limit = max(1, min(int(limit), 100))
    placeholders = ", ".join(f":palco_{idx}" for idx, _ in enumerate(palco_refs))
    params: dict[str, object] = {f"palco_{idx}": ref for idx, ref in enumerate(palco_refs)}
    params["limit"] = safe_limit
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                f"""
                SELECT historico_ref, ator_ref, palco_ref, alvo_ref, ajuste, status, resumo_publico, created_at
                FROM eq_historico
                WHERE palco_ref IN ({placeholders})
                ORDER BY created_at DESC, id DESC
                LIMIT :limit
                """
            ),
            params,
        ).mappings().all()
    public_rows: list[dict[str, object]] = []
    for row in rows:
        ator = get_operador_public_by_ref(usr_ref=str(row["ator_ref"]), db_engine=db_engine)
        alvo = _public_target_by_ref(alvo_ref=row["alvo_ref"], db_engine=db_engine)
        public_rows.append(
            {
                "historico_ref": str(row["historico_ref"]),
                "ator_ref": str(row["ator_ref"]),
                "ator": ator,
                "palco_ref": str(row["palco_ref"]),
                "alvo_ref": row["alvo_ref"],
                "alvo": alvo,
                "ajuste": str(row["ajuste"]),
                "status": str(row["status"]),
                "resumo": str(row["resumo_publico"]),
                "created_at": str(row["created_at"]),
            }
        )
    return public_rows

def _silenciar_permissions() -> dict[str, bool]:
    return {
        "can_send_messages": False,
        "can_send_audios": False,
        "can_send_documents": False,
        "can_send_photos": False,
        "can_send_videos": False,
        "can_send_video_notes": False,
        "can_send_voice_notes": False,
        "can_send_polls": False,
        "can_send_other_messages": False,
        "can_add_web_page_previews": False,
        "can_change_info": False,
        "can_invite_users": False,
        "can_pin_messages": False,
        "can_manage_topics": False,
    }


def _liberar_permissions() -> dict[str, bool]:
    return {
        "can_send_messages": True,
        "can_send_audios": True,
        "can_send_documents": True,
        "can_send_photos": True,
        "can_send_videos": True,
        "can_send_video_notes": True,
        "can_send_voice_notes": True,
        "can_send_polls": True,
        "can_send_other_messages": True,
        "can_add_web_page_previews": True,
        "can_change_info": True,
        "can_invite_users": True,
        "can_pin_messages": True,
        "can_manage_topics": True,
    }


def _target_member_status(member: dict[str, Any]) -> str:
    return str(member.get("status") or "").lower().strip()


def _target_member_is_bot(member: dict[str, Any]) -> bool:
    user = member.get("user")
    return isinstance(user, dict) and bool(user.get("is_bot") is True)


async def ensure_member_target_eligible(
    *,
    bot_token: str,
    chat_id: int,
    user_id: int,
    ajuste: str,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, Any]:
    """Validate target member state before member adjustments.

    Telegram itself is still the final authority. This preflight converts common
    member-state failures into clear sanitized messages before calling mutating
    methods such as restrictChatMember, banChatMember or unbanChatMember.
    """
    member = await telegram_api_call(
        bot_token,
        "getChatMember",
        {"chat_id": int(chat_id), "user_id": int(user_id)},
    )
    if not isinstance(member, dict):
        raise MesaTargetError("Alvo indisponível no palco.")
    status = _target_member_status(member)
    if _target_member_is_bot(member):
        raise MesaTargetError("Alvo automatizado não pode ser ajustado pela Mesa.")
    if status in {"creator", "administrator"}:
        raise MesaTargetError("Alvo é administrador do palco e não pode ser ajustado pela Mesa.")
    if ajuste in {"membros.silenciar", "membros.liberar", "membros.remover"} and status in {"left", "kicked"}:
        raise MesaTargetError("Alvo não está ativo no palco.")
    if ajuste == "membros.reintegrar" and status != "kicked":
        raise MesaTargetError("Alvo não está removido do palco.")
    return member


def build_action_payload(
    *,
    ajuste: str,
    palco_id: int,
    payload: dict[str, Any],
    db_engine: Engine = default_engine,
) -> tuple[dict[str, Any], str | None, str]:
    """Build the Bot API payload from public refs only."""
    if ajuste not in ACTION_SPECS:
        raise MesaError("ajuste_indisponivel")

    if ajuste == "mensagens.enviar":
        texto = str(payload.get("texto") or "").strip()
        if not texto:
            raise MesaTargetError("Escreva a mensagem antes de enviar.")
        if len(texto) > 4096:
            raise MesaTargetError("Mensagem acima do limite do Telegram.")
        telegram_payload: dict[str, Any] = {
            "chat_id": int(palco_id),
            "text": texto,
            "disable_web_page_preview": bool(payload.get("sem_preview", True)),
            "disable_notification": bool(payload.get("sem_notificacao", False)),
        }
        resumo = _safe_text(texto.replace("\n", " "), fallback="Mensagem enviada")[:80]
        return telegram_payload, None, resumo

    if ajuste in {"mensagens.apagar", "fixados.criar", "fixados.remover"}:
        msg_ref = _safe_text(payload.get("msg_ref"))
        if not msg_ref.startswith("msg_"):
            raise MesaNotFoundError("mensagem_indisponivel")
        message = resolve_mensagem_ref(palco_id=palco_id, msg_ref=msg_ref, db_engine=db_engine)
        telegram_payload: dict[str, Any] = {
            "chat_id": int(palco_id),
            "message_id": int(message["telegram_message_id"]),
        }
        if ajuste == "mensagens.apagar" and mensagem_fora_da_janela_apagar(message):
            raise MesaTargetError("Mensagem fora da janela de apagamento do Telegram.")
        if ajuste == "fixados.criar":
            telegram_payload["disable_notification"] = bool(payload.get("sem_notificacao", True))
        return telegram_payload, str(message["ui_ref"]), str(message.get("resumo_publico") or "Mensagem")

    if ajuste in {"membros.silenciar", "membros.liberar", "membros.remover", "membros.reintegrar"}:
        alvo_ref = _safe_text(payload.get("alvo_ref"))
        if not alvo_ref.startswith("usr_"):
            raise MesaNotFoundError("alvo_indisponivel")
        target = resolve_alvo_ref(palco_id=palco_id, alvo_ref=alvo_ref, db_engine=db_engine)
        telegram_payload = {"chat_id": int(palco_id), "user_id": int(target["telegram_user_id"])}
        if ajuste == "membros.silenciar":
            duration = int(payload.get("duracao_segundos") or 3600)
            until_date = _now_unix() + max(60, min(duration, 366 * 24 * 60 * 60))
            telegram_payload.update(
                {
                    "permissions": _silenciar_permissions(),
                    "use_independent_chat_permissions": True,
                    "until_date": until_date,
                }
            )
        elif ajuste == "membros.liberar":
            telegram_payload.update(
                {
                    "permissions": _liberar_permissions(),
                    "use_independent_chat_permissions": True,
                }
            )
        elif ajuste == "membros.remover":
            telegram_payload["revoke_messages"] = bool(payload.get("revogar_mensagens", False))
        elif ajuste == "membros.reintegrar":
            telegram_payload["only_if_banned"] = bool(payload.get("apenas_se_banido", True))
        return telegram_payload, str(target["ui_ref"]), str(target.get("nome_publico") or "Membro")

    if ajuste == "convites.criar":
        name = _safe_text(payload.get("nome"), fallback="Equalizador")[:32]
        telegram_payload = {"chat_id": int(palco_id), "name": name}
        expire_seconds = _safe_int(payload.get("expira_em_segundos"), default=0, minimum=0, maximum=30 * 24 * 60 * 60)
        if expire_seconds > 0:
            telegram_payload["expire_date"] = _now_unix() + expire_seconds
        member_limit = _safe_int(payload.get("limite_membros"), default=0, minimum=0, maximum=99999)
        if member_limit > 0:
            telegram_payload["member_limit"] = member_limit
        if bool(payload.get("solicitar_aprovacao", False)):
            # Telegram does not allow member_limit together with join-request links.
            telegram_payload.pop("member_limit", None)
            telegram_payload["creates_join_request"] = True
        return telegram_payload, None, "Convite"

    raise MesaError("ajuste_indisponivel")



def _unique_msg_refs(raw_refs: object) -> list[str]:
    if not isinstance(raw_refs, list):
        raise MesaTargetError("Informe uma lista de mensagens.")
    refs: list[str] = []
    seen: set[str] = set()
    for raw in raw_refs:
        ref = _safe_text(raw)
        if not ref.startswith("msg_"):
            raise MesaNotFoundError("mensagem_indisponivel")
        if ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    if not refs:
        raise MesaTargetError("Selecione ao menos uma mensagem.")
    if len(refs) > 100:
        raise MesaTargetError("Selecione no máximo 100 mensagens por lote.")
    return refs


async def executar_mensagens_apagar_lote(
    *,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Delete 1-100 known message aliases in one Bot API request.

    The frontend still sends only public msg_ref aliases. The real chat_id and
    message_ids are resolved server-side to preserve Equalizador privacy rules.
    """
    spec = ACTION_SPECS["mensagens.apagar"]
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    refs = _unique_msg_refs(payload.get("msg_refs") or payload.get("mensagens") or payload.get("message_refs"))

    resolved: list[tuple[str, dict[str, object]]] = []
    skipped: list[dict[str, object]] = []
    for ref in refs:
        message = resolve_mensagem_ref(palco_id=palco_id, msg_ref=ref, db_engine=db_engine)
        if mensagem_fora_da_janela_apagar(message):
            skipped.append({"msg_ref": ref, "motivo": "fora_da_janela_telegram"})
            continue
        resolved.append((ref, message))
    if not resolved:
        raise MesaTargetError("Nenhuma mensagem selecionada está dentro da janela de apagamento do Telegram.")

    message_ids = [int(message["telegram_message_id"]) for _, message in resolved]
    telegram_payload = {"chat_id": palco_id, "message_ids": message_ids}
    try:
        await ensure_bot_right(
            bot_token=bot_token,
            chat_id=palco_id,
            required_right=spec.direito,
            telegram_api_call=telegram_api_call,
        )
        await telegram_api_call(bot_token, "deleteMessages", telegram_payload)
        for ref, _ in resolved:
            mark_mensagem_inativa(palco_id=palco_id, msg_ref=ref, db_engine=db_engine)
        resumo = f"{len(resolved)} mensagens apagadas em lote"
        if skipped:
            resumo += f"; {len(skipped)} ignoradas por limite do Telegram"
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="mensagens.apagar_lote",
            status="concluido",
            resumo_publico=resumo,
            payload_tecnico={"method": "deleteMessages", "message_count": len(resolved), "skipped": skipped},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        return {
            "ok": True,
            "ajuste": "mensagens.apagar_lote",
            "status": "concluido",
            "apagadas": len(resolved),
            "ignoradas": skipped,
            "historico_ref": history["historico_ref"],
            "resumo": history["resumo"],
        }
    except Exception as exc:
        detail = mesa_error_public_detail(exc)
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=None,
            ajuste="mensagens.apagar_lote",
            status="falhou",
            resumo_publico=f"mensagens.apagar_lote não concluído · {detail}",
            payload_tecnico={"erro": _safe_error_text(exc, fallback=exc.__class__.__name__), "motivo_publico": detail, "method": "deleteMessages"},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MesaRightError):
            raise
        if isinstance(exc, MesaNotFoundError):
            raise
        if isinstance(exc, MesaError):
            raise
        raise MesaError("ajuste_falhou") from exc


async def executar_ajuste(
    *,
    ajuste: str,
    palco: dict[str, object],
    ator_ref: str,
    payload: dict[str, Any],
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Execute a light moderation adjustment and record sanitized history."""
    spec = ACTION_SPECS.get(ajuste)
    if not spec:
        raise MesaError("ajuste_indisponivel")
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    telegram_payload, alvo_ref, alvo_label = build_action_payload(
        ajuste=ajuste,
        palco_id=palco_id,
        payload=payload,
        db_engine=db_engine,
    )

    try:
        await ensure_bot_right(
            bot_token=bot_token,
            chat_id=palco_id,
            required_right=spec.direito,
            telegram_api_call=telegram_api_call,
        )
        member_before: dict[str, Any] | None = None
        if spec.target_kind == "alvo":
            member_before = await ensure_member_target_eligible(
                bot_token=bot_token,
                chat_id=palco_id,
                user_id=int(telegram_payload["user_id"]),
                ajuste=spec.ajuste,
                telegram_api_call=telegram_api_call,
            )
        result = await telegram_api_call(bot_token, spec.telegram_method, telegram_payload)
        fixacao: dict[str, object] | None = None
        if ajuste == "mensagens.enviar" and isinstance(result, dict) and result.get("message_id") is not None:
            message_unix_time = None
            try:
                message_unix_time = int(result.get("date") or 0) or None
            except (TypeError, ValueError):
                message_unix_time = None
            alvo_ref = register_mensagem_ref(
                chat_id=palco_id,
                message_id=int(result["message_id"]),
                resumo_publico=alvo_label or "Mensagem enviada",
                alias_secret=alias_secret,
                message_unix_time=message_unix_time,
                db_engine=db_engine,
            )
            if bool(payload.get("fixar", False)):
                try:
                    await ensure_bot_right(
                        bot_token=bot_token,
                        chat_id=palco_id,
                        required_right="can_pin_messages",
                        telegram_api_call=telegram_api_call,
                    )
                    await telegram_api_call(
                        bot_token,
                        "pinChatMessage",
                        {"chat_id": palco_id, "message_id": int(result["message_id"]), "disable_notification": True},
                    )
                    fixacao = {"ok": True}
                except MesaError as exc:
                    fixacao = {"ok": False, "motivo": mesa_error_public_detail(exc)}
        if ajuste == "mensagens.apagar" and alvo_ref:
            mark_mensagem_inativa(palco_id=palco_id, msg_ref=alvo_ref, db_engine=db_engine)
        membro_estado = None
        if spec.target_kind == "alvo" and alvo_ref:
            membro_estado = {
                "membros.silenciar": "silenciado",
                "membros.liberar": "liberado",
                "membros.remover": "removido",
                "membros.reintegrar": "reintegrado",
            }.get(ajuste, "ajustado")
            telegram_status = {
                "membros.silenciar": "restricted",
                "membros.liberar": "member",
                "membros.remover": "kicked",
                "membros.reintegrar": "left",
            }.get(ajuste, _target_member_status(member_before or {}))
            mark_alvo_status(palco_id=palco_id, alvo_ref=alvo_ref, telegram_status=telegram_status, db_engine=db_engine)
        invite_link = None
        if ajuste == "convites.criar" and isinstance(result, dict):
            invite_link = str(result.get("invite_link") or "") or None
            try:
                from app.equalizador.entradas import register_invite_from_result

                register_invite_from_result(chat_id=palco_id, result=result, alias_secret=alias_secret, db_engine=db_engine)
            except Exception:
                pass
        resumo = f"{spec.ajuste} concluído em {palco.get('titulo') or 'Palco'}"
        if alvo_label:
            resumo = f"{spec.ajuste} concluído: {alvo_label}"
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=alvo_ref,
            ajuste=spec.ajuste,
            status="concluido",
            resumo_publico=resumo,
            payload_tecnico={"method": spec.telegram_method, "payload": telegram_payload},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        response: dict[str, object] = {
            "ok": True,
            "ajuste": spec.ajuste,
            "status": "concluido",
            "historico_ref": history["historico_ref"],
            "resumo": history["resumo"],
        }
        if ajuste in {"mensagens.enviar", "mensagens.apagar", "fixados.criar", "fixados.remover"} and alvo_ref:
            estado = {
                "mensagens.enviar": "enviada",
                "mensagens.apagar": "apagada",
                "fixados.criar": "fixada",
                "fixados.remover": "fixado_removido",
            }.get(ajuste, "ajustada")
            response["mensagem"] = {"msg_ref": alvo_ref, "resumo": alvo_label, "estado": estado}
        if ajuste == "mensagens.enviar" and fixacao is not None:
            response["fixacao"] = fixacao
        if spec.target_kind == "alvo" and alvo_ref:
            response["membro"] = {"alvo_ref": alvo_ref, "nome": alvo_label, "estado": membro_estado or "ajustado"}
        if invite_link:
            response["convite"] = invite_link
            response["convite_info"] = {
                "nome": telegram_payload.get("name"),
                "expira_em": telegram_payload.get("expire_date"),
                "limite_membros": telegram_payload.get("member_limit"),
                "solicitar_aprovacao": bool(telegram_payload.get("creates_join_request", False)),
            }
        return response
    except Exception as exc:
        detail = mesa_error_public_detail(exc)
        resumo = f"{spec.ajuste} não concluído · {detail}"
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=alvo_ref,
            ajuste=spec.ajuste,
            status="falhou",
            resumo_publico=resumo,
            payload_tecnico={"erro": _safe_error_text(exc, fallback=exc.__class__.__name__), "motivo_publico": detail, "method": spec.telegram_method, **(telegram_error_payload(exc.info) if isinstance(exc, MesaTelegramError) and getattr(exc, "info", None) else {})},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        if isinstance(exc, MesaRightError):
            raise
        if isinstance(exc, MesaNotFoundError):
            raise
        if isinstance(exc, MesaError):
            raise
        raise MesaError("ajuste_falhou") from exc


def list_mensagens_publicas(
    *,
    palco_id: int,
    limit: int = 25,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    """Return recent message aliases for the Mesa UI without exposing message_id."""
    ensure_phase5_tables(db_engine)
    safe_limit = max(1, min(int(limit), 50))
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ui_ref, resumo_publico, telegram_message_date, updated_at
                FROM eq_mensagens
                WHERE telegram_chat_id=:chat_id AND habilitado=1
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"chat_id": int(palco_id), "limit": safe_limit},
        ).mappings().all()
    now_ts = _now_unix()
    public_rows: list[dict[str, object]] = []
    for row in rows:
        raw_date = row.get("telegram_message_date")
        age_seconds = None
        if raw_date is not None:
            try:
                age_seconds = max(0, now_ts - int(raw_date))
            except (TypeError, ValueError):
                age_seconds = None
        apagavel = True if age_seconds is None else age_seconds < 48 * 60 * 60
        public_rows.append(
            {
                "msg_ref": str(row["ui_ref"]),
                "resumo": str(row["resumo_publico"] or "Mensagem"),
                "updated_at": str(row["updated_at"]),
                "idade_segundos": age_seconds,
                "apagavel": apagavel,
            }
        )
    return public_rows


def list_alvos_publicos(
    *,
    palco_id: int,
    limit: int = 25,
    db_engine: Engine = default_engine,
) -> list[dict[str, object]]:
    """Return recent member aliases for the Mesa UI without exposing user_id."""
    ensure_phase5_tables(db_engine)
    safe_limit = max(1, min(int(limit), 50))
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ui_ref, username, nome_publico, telegram_status, updated_at
                FROM eq_alvos
                WHERE telegram_chat_id=:chat_id AND habilitado=1
                ORDER BY updated_at DESC, id DESC
                LIMIT :limit
                """
            ),
            {"chat_id": int(palco_id), "limit": safe_limit},
        ).mappings().all()
    return [
        {
            "alvo_ref": str(row["ui_ref"]),
            "nome": str(row["nome_publico"] or "Membro"),
            "username": safe_public_username(row["username"]),
            "contato_url": public_tme_url(row["username"]),
            "situacao": str(row["telegram_status"] or "desconhecido"),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]
