from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine


@pytest.fixture()
def isolated_storage(monkeypatch, tmp_path):
    from app.plugins.tigrao_fsm import storage

    engine = create_engine(f"sqlite:///{tmp_path / 'tigrao_ddx_test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(storage, "engine", engine)
    storage.ensure_tables()
    return storage


class FakeBot:
    def __init__(self):
        self.deleted = []

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))


def update(text="palavra proibida"):
    user = SimpleNamespace(id=123, username="u", full_name="User", first_name="User")
    chat = SimpleNamespace(id=-1001, title="Grupo", type="supergroup")
    msg = SimpleNamespace(chat=chat, from_user=user, message_id=99, text=text, caption=None)
    return SimpleNamespace(message=msg)


@pytest.mark.asyncio
async def test_ddx_without_flag_or_config_is_noop(isolated_storage, monkeypatch) -> None:
    from app.plugins.tigrao_fsm.runtime import ddx_runtime
    from app.plugins.tigrao_fsm.permissions import TigraoBotPermissions

    monkeypatch.setattr(ddx_runtime, "TIGRAO_FSM_DDX_HARD_ENABLED", False)
    bot = FakeBot()
    assert await ddx_runtime.handle(bot, update(), permissions=TigraoBotPermissions(is_admin=True, can_delete_messages=True)) is False
    assert bot.deleted == []


@pytest.mark.asyncio
async def test_ddx_without_filter_is_noop(isolated_storage, monkeypatch) -> None:
    from app.plugins.tigrao_fsm.runtime import ddx_runtime
    from app.plugins.tigrao_fsm.permissions import TigraoBotPermissions

    monkeypatch.setattr(ddx_runtime, "TIGRAO_FSM_DDX_HARD_ENABLED", True)
    bot = FakeBot()
    assert await ddx_runtime.handle(bot, update(), permissions=TigraoBotPermissions(is_admin=True, can_delete_messages=True)) is False
    assert bot.deleted == []


@pytest.mark.asyncio
async def test_ddx_without_permission_is_noop(isolated_storage, monkeypatch) -> None:
    from app.plugins.tigrao_fsm.runtime import ddx_runtime
    from app.plugins.tigrao_fsm.permissions import TigraoBotPermissions

    monkeypatch.setattr(ddx_runtime, "TIGRAO_FSM_DDX_HARD_ENABLED", True)
    isolated_storage.create_ddx_filter(chat_id=-1001, filter_text="proibida", created_by=999, enabled=True)
    bot = FakeBot()
    assert await ddx_runtime.handle(bot, update(), permissions=TigraoBotPermissions(is_admin=True, can_delete_messages=False)) is False
    assert bot.deleted == []


@pytest.mark.asyncio
async def test_ddx_with_filter_and_permission_deletes_and_consumes(isolated_storage, monkeypatch) -> None:
    from app.plugins.tigrao_fsm.runtime import ddx_runtime
    from app.plugins.tigrao_fsm.permissions import TigraoBotPermissions

    monkeypatch.setattr(ddx_runtime, "TIGRAO_FSM_DDX_HARD_ENABLED", True)
    isolated_storage.create_ddx_filter(chat_id=-1001, filter_text="proibida", created_by=999, enabled=True)
    bot = FakeBot()
    assert await ddx_runtime.handle(bot, update(), permissions=TigraoBotPermissions(is_admin=True, can_delete_messages=True)) is True
    assert bot.deleted == [(-1001, 99)]
    assert isolated_storage.list_logs(chat_id=-1001)[0]["action"] == "ddx_delete"
