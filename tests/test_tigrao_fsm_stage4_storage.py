from __future__ import annotations
from datetime import datetime, timezone
from types import SimpleNamespace
from sqlalchemy import text


def test_storage_tables_exist_and_logs_written():
    from app.db.database import engine
    from app.plugins.tigrao_fsm.storage import ensure_storage, log_event
    ensure_storage(); log_event(action="teste", result="ok", surface="unit")
    with engine.begin() as conn:
        for table in ["tigrao_logs","tigrao_join_requests","tigrao_join_auto_accept"]:
            assert conn.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).all() is not None
        assert conn.execute(text("SELECT COUNT(*) FROM tigrao_logs WHERE action='teste'")).scalar() >= 1


def test_autoaccept_saves_one_row_per_id():
    from app.db.database import engine
    from app.plugins.tigrao_fsm.storage import save_auto_accepts
    chat_id = -100404123
    ids=[10101123,20202123,30303123]
    assert save_auto_accepts(chat_id=chat_id, chat_title="G", invite_link="https://t.me/+x", user_ids=ids, created_by_owner_id=1) == 3
    with engine.begin() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM tigrao_join_auto_accept WHERE chat_id=:chat_id AND allowed_user_id IN (10101123,20202123,30303123)"), {"chat_id": chat_id}).scalar()
    assert count == 3


class Bot:
    def __init__(self, can=True):
        self.approved=[]; self.sent=[]; self.id=999; self.can=can
    async def get_chat_member(self, *, chat_id, user_id):
        return SimpleNamespace(can_invite_users=self.can)
    async def approve_chat_join_request(self, *, chat_id, user_id):
        self.approved.append((chat_id,user_id))
    async def send_message(self, chat_id, text):
        self.sent.append((chat_id,text))


def event(uid=777, chat=-100777):
    return SimpleNamespace(chat=SimpleNamespace(id=chat,title="Grupo"), from_user=SimpleNamespace(id=uid, username="u", full_name="User"), user_chat_id=123, bio=None, invite_link=SimpleNamespace(invite_link="https://t.me/+x"), date=datetime.now(timezone.utc))


import pytest

@pytest.mark.asyncio
async def test_chat_join_request_without_active_authorization_does_not_approve():
    from app.plugins.tigrao_fsm.runtime.join_request_runtime import handle_chat_join_request
    bot=Bot()
    assert await handle_chat_join_request(bot, event(uid=888, chat=-100888)) is False
    assert bot.approved == []

@pytest.mark.asyncio
async def test_chat_join_request_with_authorization_approves_and_updates_status():
    from app.db.database import engine
    from app.plugins.tigrao_fsm.runtime.join_request_runtime import handle_chat_join_request
    from app.plugins.tigrao_fsm.storage import save_auto_accepts
    save_auto_accepts(chat_id=-100999, chat_title="Grupo", invite_link="https://t.me/+x", user_ids=[99901], created_by_owner_id=42)
    bot=Bot(can=True)
    assert await handle_chat_join_request(bot, event(uid=99901, chat=-100999)) is True
    assert bot.approved == [(-100999,99901)]
    with engine.begin() as conn:
        jr=conn.execute(text("SELECT status FROM tigrao_join_requests WHERE chat_id=-100999 AND user_id=99901 ORDER BY id DESC LIMIT 1")).scalar()
        aa=conn.execute(text("SELECT status FROM tigrao_join_auto_accept WHERE chat_id=-100999 AND allowed_user_id=99901 ORDER BY id DESC LIMIT 1")).scalar()
    assert jr == "aprovado" and aa == "aprovado"

@pytest.mark.asyncio
async def test_approve_only_runs_with_can_invite_users():
    from app.plugins.tigrao_fsm.runtime.join_request_runtime import handle_chat_join_request
    from app.plugins.tigrao_fsm.storage import save_auto_accepts
    save_auto_accepts(chat_id=-100555, chat_title="Grupo", invite_link="https://t.me/+x", user_ids=[55501], created_by_owner_id=42)
    bot=Bot(can=False)
    assert await handle_chat_join_request(bot, event(uid=55501, chat=-100555)) is False
    assert bot.approved == []


def test_accept_pending_lookup_uses_chat_id_and_user_id():
    from app.plugins.tigrao_fsm.models import TigraoJoinRequest
    from app.plugins.tigrao_fsm.storage import save_join_request, find_persistent_pending_join_request
    now=datetime.now(timezone.utc)
    save_join_request(TigraoJoinRequest.create(chat_id=-1001, chat_title="A", user_id=123321, username=None, full_name="U", user_chat_id=1, bio=None, invite_link=None, request_date=now, received_at=now))
    save_join_request(TigraoJoinRequest.create(chat_id=-1002, chat_title="B", user_id=123321, username=None, full_name="U", user_chat_id=1, bio=None, invite_link=None, request_date=now, received_at=now))
    assert find_persistent_pending_join_request(chat_id=-1001, user_id=123321).chat_id == -1001
