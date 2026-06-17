"""Runtime seguro para chat_join_request do Tigrão FSM."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from app.plugins.tigrao_fsm.models import TigraoJoinRequest
from app.plugins.tigrao_fsm.services import approve_pending_join_request
from app.plugins.tigrao_fsm.storage import active_auto_accept, log_event, mark_auto_accept_approved, save_join_request, update_join_request_status

async def bot_can_invite_users(bot: Any, chat_id: int) -> bool:
    member = await bot.get_chat_member(chat_id=chat_id, user_id=(await bot.me()).id if hasattr(bot, "me") else bot.id)
    return bool(getattr(member, "can_invite_users", False))

async def handle_chat_join_request(bot: Any, event: Any) -> bool:
    chat = event.chat; user = event.from_user
    full_name = getattr(user, "full_name", None) or " ".join(p for p in [getattr(user,"first_name",None), getattr(user,"last_name",None)] if p) or str(user.id)
    invite = getattr(getattr(event, "invite_link", None), "invite_link", None)
    req = TigraoJoinRequest.create(chat_id=int(chat.id), chat_title=getattr(chat,"title",None) or "", user_id=int(user.id), username=getattr(user,"username",None), full_name=full_name, user_chat_id=getattr(event,"user_chat_id",None), bio=getattr(event,"bio",None), invite_link=invite, request_date=getattr(event,"date",None) or datetime.now(timezone.utc))
    save_join_request(req)
    log_event(chat_id=req.chat_id, chat_title=req.chat_title, target_user_id=req.user_id, target_username=req.username, target_full_name=req.full_name, action="join_request_received", result="pendente", detection="direta", surface="chat_join_request", details="solicitação recebida")
    auto = active_auto_accept(chat_id=req.chat_id, user_id=req.user_id)
    if not auto:
        return False
    if not await bot_can_invite_users(bot, req.chat_id):
        log_event(chat_id=req.chat_id, chat_title=req.chat_title, target_user_id=req.user_id, action="join_auto_accept", result="falhou", detection="direta", surface="chat_join_request", details="bot sem can_invite_users")
        return False
    detail = await approve_pending_join_request(bot, req, processed_by=auto.get("created_by_owner_id"), autoaccept=True, origin="autorização automática ativa")
    update_join_request_status(chat_id=req.chat_id, user_id=req.user_id, status=req.status, processed_by=req.processed_by, result_detail=req.result_detail, processed_at=req.processed_at)
    if req.status == "aprovado":
        mark_auto_accept_approved(row_id=auto["id"], result_detail=detail, approved_at=req.processed_at)
    log_event(chat_id=req.chat_id, chat_title=req.chat_title, actor_user_id=auto.get("created_by_owner_id"), target_user_id=req.user_id, target_username=req.username, target_full_name=req.full_name, action="join_auto_accept", result=req.status, detection="direta", surface="chat_join_request", details=detail)
    try:
        await bot.send_message(auto.get("created_by_owner_id"), detail)
    except Exception:
        pass
    return req.status == "aprovado"
