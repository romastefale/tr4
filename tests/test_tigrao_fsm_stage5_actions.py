from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine


@pytest.fixture()
def isolated_storage(monkeypatch, tmp_path):
    from app.plugins.tigrao_fsm import storage

    engine = create_engine(f"sqlite:///{tmp_path / 'tigrao_action_test.db'}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(storage, "engine", engine)
    storage.ensure_tables()
    return storage


class FakeBot:
    def __init__(self):
        self.banned = []
        self.unbanned = []
        self.restricted = []
        self.deleted = []

    async def ban_chat_member(self, **kwargs):
        self.banned.append(kwargs)

    async def unban_chat_member(self, **kwargs):
        self.unbanned.append(kwargs)

    async def restrict_chat_member(self, **kwargs):
        self.restricted.append(kwargs)

    async def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


@pytest.fixture()
def permissions():
    from app.plugins.tigrao_fsm.permissions import TigraoBotPermissions

    return TigraoBotPermissions(is_admin=True, can_restrict_members=True, can_delete_messages=True)


def request(action: str, **kwargs):
    from app.plugins.tigrao_fsm.destructive_actions import DestructiveActionRequest

    return DestructiveActionRequest(
        action=action,
        chat_id=-1001,
        chat_title="Grupo",
        actor_user_id=999,
        target_user_id=kwargs.get("target_user_id", 123),
        message_id=kwargs.get("message_id"),
        confirmed=kwargs.get("confirmed", True),
        target_is_admin=kwargs.get("target_is_admin", False),
    )


@pytest.mark.asyncio
async def test_action_without_confirmation_does_not_execute(isolated_storage, permissions) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action

    bot = FakeBot()
    result = await execute_destructive_action(bot, request("ban", confirmed=False), permissions=permissions, bot_user_id=777)
    assert result.ok is False
    assert bot.banned == []
    assert isolated_storage.list_logs(chat_id=-1001)[0]["result"] == "bloqueado_sem_confirmacao"


@pytest.mark.asyncio
async def test_ban_requires_can_restrict_members(isolated_storage) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action
    from app.plugins.tigrao_fsm.permissions import TigraoBotPermissions

    bot = FakeBot()
    perms = TigraoBotPermissions(is_admin=True, can_restrict_members=False, can_delete_messages=True)
    result = await execute_destructive_action(bot, request("ban"), permissions=perms, bot_user_id=777)
    assert result.ok is False
    assert bot.banned == []
    assert isolated_storage.list_logs(chat_id=-1001)[0]["result"] == "bloqueado_sem_permissao"


@pytest.mark.asyncio
async def test_protected_target_is_blocked(isolated_storage, permissions) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action

    bot = FakeBot()
    result = await execute_destructive_action(bot, request("ban", target_user_id=777), permissions=permissions, bot_user_id=777)
    assert result.ok is False
    assert bot.banned == []
    assert isolated_storage.list_logs(chat_id=-1001)[0]["result"] == "bloqueado_alvo_protegido"


@pytest.mark.asyncio
async def test_ban_executes_once_and_logs(isolated_storage, permissions) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action

    bot = FakeBot()
    result = await execute_destructive_action(bot, request("ban"), permissions=permissions, bot_user_id=777)
    assert result.ok is True
    assert len(bot.banned) == 1
    assert isolated_storage.list_logs(chat_id=-1001)[0]["result"] == "concluido"


@pytest.mark.asyncio
async def test_mute_and_unmute_use_restrict_chat_member(isolated_storage, permissions) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action

    bot = FakeBot()
    assert (await execute_destructive_action(bot, request("mute1h"), permissions=permissions, bot_user_id=777)).ok is True
    assert (await execute_destructive_action(bot, request("unmute"), permissions=permissions, bot_user_id=777)).ok is True
    assert len(bot.restricted) == 2


@pytest.mark.asyncio
async def test_delete_requires_can_delete_messages(isolated_storage) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action
    from app.plugins.tigrao_fsm.permissions import TigraoBotPermissions

    bot = FakeBot()
    perms = TigraoBotPermissions(is_admin=True, can_restrict_members=True, can_delete_messages=False)
    result = await execute_destructive_action(bot, request("delmsg", message_id=55), permissions=perms, bot_user_id=777)
    assert result.ok is False
    assert bot.deleted == []


@pytest.mark.asyncio
async def test_delete_executes_and_logs(isolated_storage, permissions) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action

    bot = FakeBot()
    result = await execute_destructive_action(bot, request("delmsg", message_id=55), permissions=permissions, bot_user_id=777)
    assert result.ok is True
    assert bot.deleted == [{"chat_id": -1001, "message_id": 55}]


@pytest.mark.asyncio
async def test_target_admin_is_blocked(isolated_storage, permissions) -> None:
    from app.plugins.tigrao_fsm.destructive_actions import execute_destructive_action

    bot = FakeBot()
    result = await execute_destructive_action(bot, request("ban", target_user_id=123, target_is_admin=True), permissions=permissions, bot_user_id=777)
    assert result.ok is False
    assert bot.banned == []
    assert isolated_storage.list_logs(chat_id=-1001)[0]["result"] == "bloqueado_alvo_protegido"


def test_unmute_permissions_do_not_grant_group_management_rights() -> None:
    from app.plugins.tigrao_fsm import destructive_actions

    perms = destructive_actions._unmute_permissions()
    for attr in ["can_change_info", "can_invite_users", "can_pin_messages", "can_manage_topics"]:
        if isinstance(perms, dict):
            assert perms.get(attr) in (None, False)
        else:
            assert getattr(perms, attr, False) is False
