from __future__ import annotations

import asyncio

import pytest

from app.security import panic
from app.security.task_registry import spawn_task, task_count


@pytest.fixture(autouse=True)
def _reset_security_mode():
    panic.reset_security_signals()
    panic.set_security_mode("normal", reason="test reset")
    yield
    panic.reset_security_signals()
    panic.set_security_mode("normal", reason="test reset")


def test_security_signal_can_escalate_to_alert():
    assert panic.get_security_mode() == "normal"
    count = panic.record_security_signal("unit.test", threshold=1, reason="threshold")
    assert count == 1
    assert panic.get_security_mode() == "alert"


def test_restricted_blocks_delegate_but_not_root_semantics():
    panic.set_security_mode("restricted", reason="unit")
    assert panic.should_block_delegate_actions(actor_is_root=False) is True
    assert panic.should_block_delegate_actions(actor_is_root=True) is False
    assert panic.should_block_automations() is True


@pytest.mark.asyncio
async def test_task_registry_retains_and_releases_task():
    async def _work():
        await asyncio.sleep(0)
        return "ok"

    before = task_count()
    task = spawn_task(_work(), name="unit.task")
    assert task_count() >= before + 1
    await task
    await asyncio.sleep(0)
    assert task_count() <= before
