from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TaskInfo:
    name: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = field(default_factory=dict)


_TASKS: dict[asyncio.Task, TaskInfo] = {}


def spawn_task(coro: Coroutine[Any, Any, Any], *, name: str, context: dict[str, Any] | None = None) -> asyncio.Task:
    """Create and retain a background task until it finishes.

    Python's asyncio documentation recommends keeping a strong reference to
    tasks created with create_task(). This helper centralizes that pattern and
    logs unexpected exceptions so fire-and-forget work is not silent.
    """
    task = asyncio.create_task(coro, name=name)
    info = TaskInfo(name=name, context=dict(context or {}))
    _TASKS[task] = info

    def _done(done_task: asyncio.Task) -> None:
        task_info = _TASKS.pop(done_task, info)
        try:
            done_task.result()
        except asyncio.CancelledError:
            logger.info("TASK_CANCELLED | name=%s | context=%s", task_info.name, task_info.context)
        except Exception:
            logger.exception("TASK_FAILED | name=%s | context=%s", task_info.name, task_info.context)

    task.add_done_callback(_done)
    return task


def task_count() -> int:
    return len(_TASKS)


def list_tasks() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    for task, info in list(_TASKS.items()):
        rows.append(
            {
                "name": info.name,
                "done": task.done(),
                "age_seconds": (now - info.created_at).total_seconds(),
                "context": dict(info.context),
            }
        )
    return rows


async def shutdown_tasks(*, timeout: float = 5.0) -> None:
    tasks = list(_TASKS)
    if not tasks:
        return
    for task in tasks:
        task.cancel()
    try:
        await asyncio.wait(tasks, timeout=timeout)
    finally:
        _TASKS.clear()
