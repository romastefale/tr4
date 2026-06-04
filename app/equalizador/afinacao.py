from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Iterable

import httpx
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.db.database import engine as default_engine
from app.equalizador.palcos import ensure_equalizador_tables


class AfinacaoError(RuntimeError):
    """Raised when a palco afinação cannot be resolved or synchronized."""


class PalcoNotFoundError(AfinacaoError):
    """Raised when the UI alias does not map to an enabled Equalizador palco."""


RIGHT_FIELDS = (
    "can_manage_chat",
    "can_delete_messages",
    "can_restrict_members",
    "can_invite_users",
    "can_pin_messages",
    "can_change_info",
    "can_manage_topics",
    "can_manage_video_chats",
)

_CANAL_RULES: tuple[dict[str, object], ...] = (
    {
        "codigo": "mensagens.apagar",
        "nome": "Apagar mensagens",
        "direitos": ("can_delete_messages",),
    },
    {
        "codigo": "reacoes.limpar",
        "nome": "Limpar reações",
        "direitos": ("can_delete_messages",),
    },
    {
        "codigo": "membros.silenciar",
        "nome": "Silenciar membros",
        "direitos": ("can_restrict_members",),
    },
    {
        "codigo": "membros.liberar",
        "nome": "Liberar membros",
        "direitos": ("can_restrict_members",),
    },
    {
        "codigo": "membros.remover",
        "nome": "Remover membros",
        "direitos": ("can_restrict_members",),
    },
    {
        "codigo": "membros.reintegrar",
        "nome": "Reintegrar membros",
        "direitos": ("can_restrict_members",),
    },
    {
        "codigo": "fixados.criar",
        "nome": "Fixar mensagens",
        "direitos": ("can_pin_messages",),
    },
    {
        "codigo": "fixados.remover",
        "nome": "Remover fixados",
        "direitos": ("can_pin_messages",),
    },
    {
        "codigo": "convites.criar",
        "nome": "Criar convites",
        "direitos": ("can_invite_users",),
    },
    {
        "codigo": "palco.afinar",
        "nome": "Afinar palco",
        "direitos": ("can_manage_chat",),
        "critico": True,
    },
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _truthy(value: Any) -> bool:
    return bool(value is True)


def canais_from_bot_rights(member: dict[str, Any]) -> list[dict[str, object]]:
    """Map Telegram administrator rights into public Equalizador channels.

    This is read-only diagnostic data. It does not grant an operator permission;
    operational routes still validate operator/palco channel distribution.
    """
    status = str(member.get("status") or "").lower()
    is_admin = status in {"administrator", "creator"}
    channels: list[dict[str, object]] = []
    for rule in _CANAL_RULES:
        required = tuple(str(item) for item in rule.get("direitos", ()))
        available = is_admin and all(_truthy(member.get(right)) for right in required)
        if status == "creator":
            available = True
        missing = [right for right in required if not _truthy(member.get(right))]
        channels.append(
            {
                "codigo": str(rule["codigo"]),
                "nome": str(rule["nome"]),
                "disponivel": available,
                "critico": bool(rule.get("critico", False)),
                "requer": list(required),
                "faltando": [] if available else missing,
            }
        )
    return channels


def public_rights_from_member(member: dict[str, Any]) -> dict[str, object]:
    """Return only permission flags useful for UI diagnosis."""
    status = str(member.get("status") or "desconhecido")
    direitos = {field: bool(member.get(field) is True) for field in RIGHT_FIELDS}
    if status == "creator":
        direitos = {field: True for field in RIGHT_FIELDS}
    return {"status": status, "direitos": direitos}


def _safe_error_message(exc: Exception) -> str:
    text_value = str(exc).strip()
    if not text_value:
        text_value = exc.__class__.__name__
    # Never echo bot token, chat id, or raw upstream JSON into the UI.
    return text_value[:120]


async def _telegram_api_call(token: str, method: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if not token:
        raise AfinacaoError("token_indisponivel")
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=8.0) as client:
        response = await client.post(url, json=payload or {})
    try:
        data = response.json()
    except ValueError as exc:
        raise AfinacaoError("telegram_resposta_invalida") from exc
    if not response.is_success or not data.get("ok"):
        description = str(data.get("description") or "telegram_erro")
        raise AfinacaoError(description)
    result = data.get("result")
    if not isinstance(result, dict):
        raise AfinacaoError("telegram_resultado_invalido")
    return result


TelegramApiCallable = Callable[[str, str, dict[str, Any] | None], Awaitable[dict[str, Any]]]


async def fetch_bot_member_rights(
    *,
    bot_token: str,
    chat_id: int,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, Any]:
    """Fetch the bot's real status and rights in a Telegram palco."""
    me = await telegram_api_call(bot_token, "getMe", None)
    bot_id = int(me.get("id") or 0)
    if bot_id <= 0:
        raise AfinacaoError("bot_id_indisponivel")
    member = await telegram_api_call(bot_token, "getChatMember", {"chat_id": int(chat_id), "user_id": bot_id})
    if not isinstance(member, dict):
        raise AfinacaoError("membro_indisponivel")
    return member


def get_palco_internal_by_ref(
    *,
    grp_ref: str,
    db_engine: Engine = default_engine,
) -> dict[str, object] | None:
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT telegram_chat_id, titulo, ui_ref, habilitado, bot_rights_json, last_synced_at
                FROM eq_palcos
                WHERE ui_ref=:ui_ref AND habilitado=1
                """
            ),
            {"ui_ref": grp_ref},
        ).mappings().first()
    return dict(row) if row else None


def persist_afinacao_snapshot(
    *,
    grp_ref: str,
    snapshot: dict[str, object],
    db_engine: Engine = default_engine,
) -> None:
    ensure_equalizador_tables(db_engine)
    with db_engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE eq_palcos
                SET bot_rights_json=:bot_rights_json,
                    last_synced_at=:last_synced_at,
                    updated_at=:updated_at
                WHERE ui_ref=:ui_ref
                """
            ),
            {
                "ui_ref": grp_ref,
                "bot_rights_json": json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                "last_synced_at": str(snapshot.get("sincronizado_em") or _now_iso()),
                "updated_at": _now_iso(),
            },
        )


async def sincronizar_afinacao_palco(
    *,
    grp_ref: str,
    bot_token: str,
    db_engine: Engine = default_engine,
    telegram_api_call: TelegramApiCallable = _telegram_api_call,
) -> dict[str, object]:
    """Synchronize a palco rights snapshot and return sanitized UI data."""
    palco = get_palco_internal_by_ref(grp_ref=grp_ref, db_engine=db_engine)
    if not palco:
        raise PalcoNotFoundError("palco_indisponivel")

    synced_at = _now_iso()
    try:
        member = await fetch_bot_member_rights(
            bot_token=bot_token,
            chat_id=int(palco["telegram_chat_id"]),
            telegram_api_call=telegram_api_call,
        )
        public_rights = public_rights_from_member(member)
        canais = canais_from_bot_rights(member)
        ok = str(public_rights["status"]).lower() in {"administrator", "creator"}
        estado = "afinado" if ok else "sem afinação"
        snapshot: dict[str, object] = {
            "grp_ref": str(palco["ui_ref"]),
            "titulo": str(palco.get("titulo") or "Palco sem título"),
            "estado": estado,
            "sincronizado_em": synced_at,
            "bot": public_rights,
            "canais": canais,
        }
    except Exception as exc:
        snapshot = {
            "grp_ref": str(palco["ui_ref"]),
            "titulo": str(palco.get("titulo") or "Palco sem título"),
            "estado": "indisponível",
            "sincronizado_em": synced_at,
            "erro": _safe_error_message(exc),
            "bot": {"status": "desconhecido", "direitos": {field: False for field in RIGHT_FIELDS}},
            "canais": canais_from_bot_rights({"status": "desconhecido"}),
        }
    persist_afinacao_snapshot(grp_ref=grp_ref, snapshot=snapshot, db_engine=db_engine)
    return snapshot


def summarize_afinacao_for_palcos(palcos: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    """Return compact UI rows; useful for tests and future listing optimizations."""
    rows: list[dict[str, object]] = []
    for palco in palcos:
        row = dict(palco)
        row.setdefault("afinacao", "pendente")
        rows.append(row)
    return rows
