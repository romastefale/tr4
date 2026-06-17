from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text


@pytest.fixture()
def isolated_storage(monkeypatch, tmp_path):
    from app.plugins.tigrao_fsm import storage

    engine = create_engine(f"sqlite:///{tmp_path / 'tigrao_test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(storage, "engine", engine)
    storage.ensure_tables()
    return storage


def test_storage_tables_exist(isolated_storage) -> None:
    with isolated_storage.engine.begin() as conn:
        names = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))}
    assert {"tigrao_logs", "tigrao_join_requests", "tigrao_join_auto_accept"}.issubset(names)


def test_autoaccept_saves_one_record_per_id_and_logs(isolated_storage) -> None:
    records = isolated_storage.create_auto_accept_records(
        chat_id=-1001,
        chat_title="Grupo",
        invite_link="https://t.me/+abc",
        user_ids=[111, 222, 333],
        created_by_owner_id=999,
    )
    assert [r.allowed_user_id for r in records] == [111, 222, 333]
    assert isolated_storage.get_active_auto_accept(chat_id=-1001, user_id=222) is not None
    log_id = isolated_storage.log_event(action="join_auto_ids_saved", result="salvo", detection="direta", surface="dm", chat_id=-1001)
    assert log_id >= 1
    assert isolated_storage.list_logs(chat_id=-1001)[0]["action"] == "join_auto_ids_saved"


def test_find_pending_join_request_uses_chat_id_and_user_id(isolated_storage) -> None:
    from app.plugins.tigrao_fsm.models import TigraoJoinRequest

    now = datetime(2026, 6, 17, tzinfo=timezone.utc)
    request = TigraoJoinRequest.create(
        chat_id=-1001,
        chat_title="Grupo",
        user_id=123,
        username=None,
        full_name="Nome",
        user_chat_id=9999999999,
        bio=None,
        invite_link="https://t.me/+abc",
        request_date=now,
        received_at=now,
    )
    isolated_storage.save_join_request(request)
    assert isolated_storage.find_pending_join_request(chat_id=-1001, user_id=123, now=now) is not None
    assert isolated_storage.find_pending_join_request(chat_id=-1002, user_id=123, now=now) is None


class FakeBot:
    def __init__(self, *, can_invite_users: bool = True):
        self.can_invite_users = can_invite_users
        self.approved: list[tuple[int, int]] = []
        self.messages: list[tuple[int, str]] = []

    async def get_me(self):
        return SimpleNamespace(id=777000)

    async def get_chat_member(self, chat_id: int, user_id: int):
        return SimpleNamespace(status="administrator", can_invite_users=self.can_invite_users)

    async def approve_chat_join_request(self, *, chat_id: int, user_id: int):
        self.approved.append((chat_id, user_id))

    async def send_message(self, user_id: int, text: str):
        self.messages.append((user_id, text))


def make_join_update(chat_id: int = -1001, user_id: int = 123):
    user = SimpleNamespace(id=user_id, username="usuario", first_name="Nome", last_name="Teste")
    chat = SimpleNamespace(id=chat_id, title="Grupo")
    request = SimpleNamespace(
        chat=chat,
        from_user=user,
        user_chat_id=999999999999,
        bio="bio",
        invite_link=SimpleNamespace(invite_link="https://t.me/+abc"),
        date=1_786_000_000,
    )
    return SimpleNamespace(chat_join_request=request)


@pytest.mark.asyncio
async def test_chat_join_request_without_authorization_saves_but_does_not_approve(isolated_storage) -> None:
    from app.plugins.tigrao_fsm.runtime.join_request_runtime import handle

    bot = FakeBot()
    consumed = await handle(bot, make_join_update())
    assert consumed is True
    assert bot.approved == []
    assert isolated_storage.find_pending_join_request(chat_id=-1001, user_id=123) is not None
    assert isolated_storage.list_logs(chat_id=-1001)[0]["action"] == "join_request_received"


@pytest.mark.asyncio
async def test_chat_join_request_with_authorization_approves_and_updates_status(isolated_storage) -> None:
    from app.plugins.tigrao_fsm.runtime.join_request_runtime import handle

    isolated_storage.create_auto_accept_records(
        chat_id=-1001,
        chat_title="Grupo",
        invite_link="https://t.me/+abc",
        user_ids=[123],
        created_by_owner_id=555,
    )
    bot = FakeBot(can_invite_users=True)
    consumed = await handle(bot, make_join_update())
    assert consumed is True
    assert bot.approved == [(-1001, 123)]
    auto = isolated_storage.get_active_auto_accept(chat_id=-1001, user_id=123)
    assert auto is None  # aprovado deixa de ser autorização ativa pendente
    logs = isolated_storage.list_logs(chat_id=-1001, action_prefix="join_auto_accept")
    assert logs and logs[0]["result"] == "aprovado"


@pytest.mark.asyncio
async def test_chat_join_request_with_authorization_requires_can_invite_users(isolated_storage) -> None:
    from app.plugins.tigrao_fsm.runtime.join_request_runtime import handle

    isolated_storage.create_auto_accept_records(
        chat_id=-1001,
        chat_title="Grupo",
        invite_link="https://t.me/+abc",
        user_ids=[123],
        created_by_owner_id=555,
    )
    bot = FakeBot(can_invite_users=False)
    assert await handle(bot, make_join_update()) is True
    assert bot.approved == []
    logs = isolated_storage.list_logs(chat_id=-1001, action_prefix="join_auto_accept")
    assert logs and logs[0]["result"] == "falhou_sem_permissao"


@pytest.mark.asyncio
async def test_create_join_request_link_forces_request_and_removes_member_limit() -> None:
    from app.plugins.tigrao_fsm.services import create_join_request_link

    class Bot:
        def __init__(self) -> None:
            self.kwargs = None

        async def create_chat_invite_link(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(invite_link="https://t.me/+abc")

    bot = Bot()
    await create_join_request_link(bot, -1001, member_limit=5, name="teste")
    assert bot.kwargs["creates_join_request"] is True
    assert "member_limit" not in bot.kwargs
