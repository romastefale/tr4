"""Serviços internos isolados do Tigrão FSM."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .models import JOIN_REQUEST_TTL, TigraoJoinRequest


def build_group_unavailable_text(name: str, chat_id: int) -> str:
    return (
        f"Grupo selecionado: {name}\n"
        f"ID do grupo: {chat_id}\n"
        "Status do bot: não administrador\n"
        "Painel indisponível para este grupo.\n"
        "Promova o bot a administrador para usar o Tigrão aqui."
    )


async def create_join_request_link(bot: Any, chat_id: int, **kwargs: Any) -> Any:
    kwargs["creates_join_request"] = True
    kwargs.pop("member_limit", None)
    return await bot.create_chat_invite_link(chat_id=chat_id, **kwargs)


def find_pending_join_request(requests: list[TigraoJoinRequest], *, chat_id: int, user_id: int, now: datetime | None = None) -> TigraoJoinRequest | None:
    now = now or datetime.now(timezone.utc)
    cutoff = now - JOIN_REQUEST_TTL
    for request in requests:
        if request.chat_id == chat_id and request.user_id == user_id and request.status == "pendente" and request.received_at >= cutoff:
            return request
    return None


def format_join_approval_detail(request: TigraoJoinRequest, *, approved_at: datetime, autoaccept: bool, origin: str) -> str:
    username = f"@{request.username}" if request.username else "não informado"
    return (
        "Entrada aprovada\n"
        f"Usuário: {request.full_name}\n"
        f"Username: {username}\n"
        f"ID: {request.user_id}\n"
        f"Grupo: {request.chat_title}\n"
        f"ID do grupo: {request.chat_id}\n"
        "Resultado: solicitação aprovada\n"
        "Método: approveChatJoinRequest\n"
        "Detecção: direta\n"
        "Onde: chat_join_request\n"
        f"Data/hora do pedido: {request.request_date.isoformat()}\n"
        f"Data/hora da aprovação: {approved_at.isoformat()}\n"
        f"Autoaceite: {'sim' if autoaccept else 'não'}\n"
        f"Origem: {origin}"
    )


async def approve_pending_join_request(bot: Any, request: TigraoJoinRequest, *, processed_by: int | None, autoaccept: bool, origin: str) -> str:
    approved_at = datetime.now(timezone.utc)
    try:
        await bot.approve_chat_join_request(chat_id=request.chat_id, user_id=request.user_id)
    except Exception as exc:  # serviço isolado registra falha real sem afirmar aprovação
        request.status = "falhou"
        request.processed_at = approved_at
        request.processed_by = processed_by
        request.result_detail = f"falha ao aprovar: {exc}"
        return request.result_detail
    request.status = "aprovado"
    request.processed_at = approved_at
    request.processed_by = processed_by
    detail = format_join_approval_detail(request, approved_at=approved_at, autoaccept=autoaccept, origin=origin)
    request.result_detail = detail
    return detail


async def decline_pending_join_request(bot: Any, request: TigraoJoinRequest, *, processed_by: int | None, origin: str) -> str:
    processed_at = datetime.now(timezone.utc)
    try:
        await bot.decline_chat_join_request(chat_id=request.chat_id, user_id=request.user_id)
    except Exception as exc:
        request.status = "falhou"
        request.processed_at = processed_at
        request.processed_by = processed_by
        request.result_detail = f"falha ao recusar: {exc}"
        return request.result_detail
    request.status = "recusado"
    request.processed_at = processed_at
    request.processed_by = processed_by
    username = f"@{request.username}" if request.username else "não informado"
    request.result_detail = (
        "Entrada recusada\n"
        f"Usuário: {request.full_name}\n"
        f"Username: {username}\n"
        f"ID: {request.user_id}\n"
        f"Grupo: {request.chat_title}\n"
        f"ID do grupo: {request.chat_id}\n"
        "Resultado: solicitação recusada\n"
        "Método: declineChatJoinRequest\n"
        "Detecção: indireta\n"
        "Onde: banco_pendente\n"
        f"Data/hora da recusa: {processed_at.isoformat()}\n"
        f"Origem: {origin}"
    )
    return request.result_detail


def format_logs(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Nenhum registro encontrado."
    parts: list[str] = []
    for row in rows[:10]:
        actor = row.get("actor_username") or row.get("actor_full_name") or row.get("actor_user_id") or "não informado"
        target = row.get("target_username") or row.get("target_full_name") or row.get("target_user_id") or "não informado"
        parts.append(
            f"{row.get('created_at')}\n"
            f"Ato: {row.get('action')}\n"
            f"Resultado: {row.get('result')}\n"
            f"Autor: {actor}\n"
            f"Alvo: {target}\n"
            f"Onde: {row.get('surface')}\n"
            f"Detalhe: {row.get('details') or 'sem detalhe'}"
        )
    return "\n\n".join(parts)
