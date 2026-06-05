
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.identity import make_ui_ref
from app.equalizador.mesa import (
    MesaTargetError,
    MesaTelegramError,
    record_historico,
    _safe_text,
    _safe_error_text,
    ensure_phase5_tables,
)

TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[Any]]


class EntradasError(RuntimeError):
    pass


class EntradasTelegramError(EntradasError):
    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.description = _safe_error_text(description, fallback="telegram_erro")


def entradas_error_public_detail(exc: BaseException) -> str:
    if isinstance(exc, EntradasTelegramError):
        return f"Telegram recusou: {_safe_error_text(exc.description, fallback='operação recusada')}"
    if isinstance(exc, MesaTargetError):
        return _safe_error_text(exc.description, fallback="Referência indisponível.")
    return _safe_error_text(exc, fallback="Operação de entrada indisponível.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_unix() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _sqlite_column_exists(conn: Any, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).mappings().all()
    return any(str(row.get("name")) == column for row in rows)


def ensure_phase43_tables(db_engine: Engine = default_engine) -> None:
    ensure_phase5_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_join_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_chat_id INTEGER NOT NULL,
                telegram_user_id INTEGER NOT NULL,
                ui_ref TEXT NOT NULL UNIQUE,
                username TEXT,
                nome_publico TEXT NOT NULL,
                bio_publica TEXT,
                invite_link TEXT,
                estado TEXT NOT NULL DEFAULT 'pendente',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (telegram_chat_id, telegram_user_id)
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS eq_convites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_chat_id INTEGER NOT NULL,
                invite_ref TEXT NOT NULL UNIQUE,
                invite_link TEXT NOT NULL UNIQUE,
                nome_publico TEXT,
                expire_date INTEGER,
                member_limit INTEGER,
                creates_join_request INTEGER NOT NULL DEFAULT 0,
                revoked INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """))
        if not _sqlite_column_exists(conn, "eq_join_requests", "bio_publica"):
            conn.execute(text("ALTER TABLE eq_join_requests ADD COLUMN bio_publica TEXT"))
        if not _sqlite_column_exists(conn, "eq_join_requests", "invite_link"):
            conn.execute(text("ALTER TABLE eq_join_requests ADD COLUMN invite_link TEXT"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_join_requests_ui_ref ON eq_join_requests(ui_ref)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_join_requests_chat_estado ON eq_join_requests(telegram_chat_id, estado)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_eq_convites_chat ON eq_convites(telegram_chat_id, revoked)"))


async def telegram_api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> Any:
    if not token:
        raise EntradasError("Token do bot indisponível.")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload or {})
    try:
        data = response.json()
    except ValueError as exc:
        raise EntradasError("Telegram retornou resposta inválida.") from exc
    if not response.is_success or data.get("ok") is not True:
        raise EntradasTelegramError(str(data.get("description") or "telegram_erro"))
    return data.get("result")


def _user_name(user: dict[str, Any]) -> str:
    first = _safe_text(user.get("first_name"), fallback="")
    last = _safe_text(user.get("last_name"), fallback="")
    return (first + " " + last).strip() or _safe_text(user.get("username"), fallback="Membro")


def register_join_request(
    *,
    chat_id: int,
    user_id: int,
    nome_publico: str,
    alias_secret: str,
    username: str | None = None,
    bio: str | None = None,
    invite_link: str | None = None,
    db_engine: Engine = default_engine,
) -> str:
    ensure_phase43_tables(db_engine)
    ui_ref = make_ui_ref("ent", f"{int(chat_id)}:{int(user_id)}", alias_secret)
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO eq_join_requests (
                telegram_chat_id, telegram_user_id, ui_ref, username, nome_publico, bio_publica,
                invite_link, estado, created_at, updated_at
            ) VALUES (
                :chat_id, :user_id, :ui_ref, :username, :nome_publico, :bio_publica,
                :invite_link, 'pendente', :created_at, :updated_at
            )
            ON CONFLICT(telegram_chat_id, telegram_user_id) DO UPDATE SET
                ui_ref=excluded.ui_ref,
                username=excluded.username,
                nome_publico=excluded.nome_publico,
                bio_publica=excluded.bio_publica,
                invite_link=excluded.invite_link,
                estado='pendente',
                updated_at=excluded.updated_at
        """), {
            "chat_id": int(chat_id),
            "user_id": int(user_id),
            "ui_ref": ui_ref,
            "username": _safe_text(username, fallback="") or None,
            "nome_publico": _safe_text(nome_publico, fallback="Membro"),
            "bio_publica": _safe_text(bio, fallback="") or None,
            "invite_link": _safe_text(invite_link, fallback="") or None,
            "created_at": now,
            "updated_at": now,
        })
    return ui_ref


def register_join_request_from_update(*, chat_id: int, user: dict[str, Any], alias_secret: str, bio: str | None = None, invite_link: str | None = None, db_engine: Engine = default_engine) -> str:
    user_id = int(user.get("id") or 0)
    if user_id <= 0:
        raise MesaTargetError("Pedido de entrada sem usuário válido.")
    return register_join_request(
        chat_id=chat_id,
        user_id=user_id,
        nome_publico=_user_name(user),
        alias_secret=alias_secret,
        username=str(user.get("username") or "") or None,
        bio=bio,
        invite_link=invite_link,
        db_engine=db_engine,
    )


def _public_join_row(row: Any) -> dict[str, object]:
    return {
        "entrada_ref": str(row["ui_ref"]),
        "nome": str(row["nome_publico"] or "Membro"),
        "situacao": str(row["estado"] or "pendente"),
        "bio": str(row["bio_publica"] or ""),
        "tem_convite": bool(row["invite_link"]),
        "updated_at": str(row["updated_at"]),
    }


def list_join_requests_publicos(*, palco_id: int, limit: int = 30, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_phase43_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT ui_ref, nome_publico, bio_publica, invite_link, estado, updated_at
            FROM eq_join_requests
            WHERE telegram_chat_id=:chat_id
            ORDER BY CASE estado WHEN 'pendente' THEN 0 ELSE 1 END, updated_at DESC, id DESC
            LIMIT :limit
        """), {"chat_id": int(palco_id), "limit": max(1, min(int(limit), 80))}).mappings().all()
    return [_public_join_row(row) for row in rows]


def resolve_join_request(*, palco_id: int, entrada_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase43_tables(db_engine)
    ref = str(entrada_ref or "").strip()
    if not ref:
        raise MesaTargetError("Escolha um pedido de entrada.")
    with db_engine.begin() as conn:
        row = conn.execute(text("""
            SELECT * FROM eq_join_requests
            WHERE telegram_chat_id=:chat_id AND ui_ref=:ui_ref
        """), {"chat_id": int(palco_id), "ui_ref": ref}).mappings().first()
    if not row:
        raise MesaTargetError("Pedido de entrada indisponível.")
    if str(row["estado"] or "") != "pendente":
        raise MesaTargetError("Pedido de entrada já foi tratado.")
    return dict(row)


async def executar_pedido_entrada(
    *,
    acao: str,
    palco: dict[str, object],
    ator_ref: str,
    entrada_ref: str,
    bot_token: str,
    alias_secret: str,
    db_engine: Engine = default_engine,
    api_call: TelegramApiCallable = telegram_api_call,
) -> dict[str, object]:
    if acao not in {"aprovar", "recusar"}:
        raise EntradasError("Ação de entrada indisponível.")
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    row = resolve_join_request(palco_id=palco_id, entrada_ref=entrada_ref, db_engine=db_engine)
    method = "approveChatJoinRequest" if acao == "aprovar" else "declineChatJoinRequest"
    try:
        await api_call(bot_token, method, {"chat_id": palco_id, "user_id": int(row["telegram_user_id"])})
        estado = "aprovado" if acao == "aprovar" else "recusado"
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE eq_join_requests SET estado=:estado, updated_at=:updated_at WHERE id=:id"), {"estado": estado, "updated_at": _now_iso(), "id": int(row["id"])})
        history = record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=str(row["ui_ref"]),
            ajuste=f"entradas.{acao}",
            status="concluido",
            resumo_publico=f"Pedido de entrada {estado}: {row['nome_publico']}",
            payload_tecnico={"method": method},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        return {"ok": True, "entrada": {"entrada_ref": row["ui_ref"], "nome": row["nome_publico"], "situacao": estado}, "historico_ref": history["historico_ref"], "resumo": history["resumo"]}
    except Exception as exc:
        detail = entradas_error_public_detail(exc)
        record_historico(
            ator_ref=ator_ref,
            palco_ref=palco_ref,
            alvo_ref=str(row.get("ui_ref") or entrada_ref),
            ajuste=f"entradas.{acao}",
            status="falhou",
            resumo_publico=f"Pedido de entrada não concluído · {detail}",
            payload_tecnico={"method": method, "motivo_publico": detail},
            alias_secret=alias_secret,
            db_engine=db_engine,
        )
        raise


def register_invite_from_result(*, chat_id: int, result: dict[str, Any], alias_secret: str, db_engine: Engine = default_engine) -> str | None:
    if not isinstance(result, dict):
        return None
    link = str(result.get("invite_link") or "").strip()
    if not link:
        return None
    ensure_phase43_tables(db_engine)
    invite_ref = make_ui_ref("inv", f"{int(chat_id)}:{link}", alias_secret)
    now = _now_iso()
    with db_engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO eq_convites (telegram_chat_id, invite_ref, invite_link, nome_publico, expire_date, member_limit, creates_join_request, revoked, created_at, updated_at)
            VALUES (:chat_id, :invite_ref, :invite_link, :nome, :expire_date, :member_limit, :creates_join_request, 0, :created_at, :updated_at)
            ON CONFLICT(invite_link) DO UPDATE SET
                invite_ref=excluded.invite_ref,
                nome_publico=excluded.nome_publico,
                expire_date=excluded.expire_date,
                member_limit=excluded.member_limit,
                creates_join_request=excluded.creates_join_request,
                revoked=0,
                updated_at=excluded.updated_at
        """), {
            "chat_id": int(chat_id),
            "invite_ref": invite_ref,
            "invite_link": link,
            "nome": _safe_text(result.get("name"), fallback="Convite"),
            "expire_date": result.get("expire_date"),
            "member_limit": result.get("member_limit"),
            "creates_join_request": 1 if result.get("creates_join_request") is True else 0,
            "created_at": now,
            "updated_at": now,
        })
    return invite_ref


def list_invites_publicos(*, palco_id: int, limit: int = 30, db_engine: Engine = default_engine) -> list[dict[str, object]]:
    ensure_phase43_tables(db_engine)
    with db_engine.begin() as conn:
        rows = conn.execute(text("""
            SELECT invite_ref, invite_link, nome_publico, expire_date, member_limit, creates_join_request, revoked, updated_at
            FROM eq_convites
            WHERE telegram_chat_id=:chat_id
            ORDER BY revoked ASC, updated_at DESC, id DESC
            LIMIT :limit
        """), {"chat_id": int(palco_id), "limit": max(1, min(int(limit), 80))}).mappings().all()
    return [
        {
            "invite_ref": str(row["invite_ref"]),
            "nome": str(row["nome_publico"] or "Convite"),
            "link": str(row["invite_link"] or ""),
            "expira_em": row["expire_date"],
            "limite_membros": row["member_limit"],
            "solicitar_aprovacao": bool(row["creates_join_request"]),
            "revogado": bool(row["revoked"]),
            "updated_at": str(row["updated_at"]),
        }
        for row in rows
    ]


def resolve_invite(*, palco_id: int, invite_ref: str, db_engine: Engine = default_engine) -> dict[str, object]:
    ensure_phase43_tables(db_engine)
    ref = str(invite_ref or "").strip()
    if not ref:
        raise MesaTargetError("Escolha um convite.")
    with db_engine.begin() as conn:
        row = conn.execute(text("SELECT * FROM eq_convites WHERE telegram_chat_id=:chat_id AND invite_ref=:invite_ref"), {"chat_id": int(palco_id), "invite_ref": ref}).mappings().first()
    if not row:
        raise MesaTargetError("Convite indisponível.")
    return dict(row)


def _invite_edit_payload(*, palco_id: int, payload: dict[str, Any], invite_link: str) -> dict[str, Any]:
    name = _safe_text(payload.get("nome"), fallback="Convite")[:32]
    data: dict[str, Any] = {"chat_id": int(palco_id), "invite_link": invite_link, "name": name}
    exp = int(payload.get("expira_em_segundos") or 0)
    if exp > 0:
        data["expire_date"] = _now_unix() + max(60, min(exp, 30 * 24 * 60 * 60))
    limit = int(payload.get("limite_membros") or 0)
    if limit > 0:
        data["member_limit"] = max(1, min(limit, 99999))
    if bool(payload.get("solicitar_aprovacao", False)):
        data.pop("member_limit", None)
        data["creates_join_request"] = True
    return data


async def editar_convite(*, palco: dict[str, object], ator_ref: str, invite_ref: str, payload: dict[str, Any], bot_token: str, alias_secret: str, db_engine: Engine = default_engine, api_call: TelegramApiCallable = telegram_api_call) -> dict[str, object]:
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    row = resolve_invite(palco_id=palco_id, invite_ref=invite_ref, db_engine=db_engine)
    if bool(row.get("revoked")):
        raise MesaTargetError("Convite revogado não pode ser editado.")
    telegram_payload = _invite_edit_payload(palco_id=palco_id, payload=payload, invite_link=str(row["invite_link"]))
    try:
        result = await api_call(bot_token, "editChatInviteLink", telegram_payload)
        if isinstance(result, dict):
            register_invite_from_result(chat_id=palco_id, result=result, alias_secret=alias_secret, db_engine=db_engine)
        history = record_historico(ator_ref=ator_ref, palco_ref=palco_ref, alvo_ref=str(row["invite_ref"]), ajuste="convites.editar", status="concluido", resumo_publico="Convite editado", payload_tecnico={"method": "editChatInviteLink"}, alias_secret=alias_secret, db_engine=db_engine)
        return {"ok": True, "convite": str((result or {}).get("invite_link") or row["invite_link"]), "historico_ref": history["historico_ref"], "resumo": history["resumo"]}
    except Exception as exc:
        detail = entradas_error_public_detail(exc)
        record_historico(ator_ref=ator_ref, palco_ref=palco_ref, alvo_ref=str(row["invite_ref"]), ajuste="convites.editar", status="falhou", resumo_publico=f"Convite não editado · {detail}", payload_tecnico={"method": "editChatInviteLink", "motivo_publico": detail}, alias_secret=alias_secret, db_engine=db_engine)
        raise


async def revogar_convite(*, palco: dict[str, object], ator_ref: str, invite_ref: str, bot_token: str, alias_secret: str, db_engine: Engine = default_engine, api_call: TelegramApiCallable = telegram_api_call) -> dict[str, object]:
    palco_id = int(palco["telegram_chat_id"])
    palco_ref = str(palco["ui_ref"])
    row = resolve_invite(palco_id=palco_id, invite_ref=invite_ref, db_engine=db_engine)
    try:
        result = await api_call(bot_token, "revokeChatInviteLink", {"chat_id": palco_id, "invite_link": str(row["invite_link"])})
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE eq_convites SET revoked=1, updated_at=:updated_at WHERE invite_ref=:invite_ref"), {"invite_ref": str(row["invite_ref"]), "updated_at": _now_iso()})
        history = record_historico(ator_ref=ator_ref, palco_ref=palco_ref, alvo_ref=str(row["invite_ref"]), ajuste="convites.revogar", status="concluido", resumo_publico="Convite revogado", payload_tecnico={"method": "revokeChatInviteLink"}, alias_secret=alias_secret, db_engine=db_engine)
        return {"ok": True, "convite": {"invite_ref": str(row["invite_ref"]), "revogado": True}, "historico_ref": history["historico_ref"], "resumo": history["resumo"]}
    except Exception as exc:
        detail = entradas_error_public_detail(exc)
        record_historico(ator_ref=ator_ref, palco_ref=palco_ref, alvo_ref=str(row["invite_ref"]), ajuste="convites.revogar", status="falhou", resumo_publico=f"Convite não revogado · {detail}", payload_tecnico={"method": "revokeChatInviteLink", "motivo_publico": detail}, alias_secret=alias_secret, db_engine=db_engine)
        raise


async def exportar_link_primario(*, palco: dict[str, object], ator_ref: str, bot_token: str, alias_secret: str, db_engine: Engine = default_engine, api_call: TelegramApiCallable = telegram_api_call) -> dict[str, object]:
    palco_id = int(palco["telegram_chat_id"])
    result = await api_call(bot_token, "exportChatInviteLink", {"chat_id": palco_id})
    link = str(result or "")
    history = record_historico(ator_ref=ator_ref, palco_ref=str(palco["ui_ref"]), alvo_ref=None, ajuste="convites.exportar_primario", status="concluido", resumo_publico="Link primário exportado", payload_tecnico={"method": "exportChatInviteLink"}, alias_secret=alias_secret, db_engine=db_engine)
    return {"ok": True, "convite": link, "historico_ref": history["historico_ref"], "resumo": history["resumo"]}
