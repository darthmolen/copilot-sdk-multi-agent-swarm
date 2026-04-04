"""TDD tests for TaskBoard — one test per specification step."""

from __future__ import annotations

import asyncio

from backend.swarm.models import Task, TaskStatus
from backend.swarm.task_board import TaskBoard

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_board() -> TaskBoard:
    return TaskBoard()


async def _add_simple(
    board: TaskBoard,
    id: str = "task-1",
    blocked_by: list[str] | None = None,
    **kw: str,
) -> Task:
    """Shortcut that fills in boilerplate fields."""
    return await board.add_task(
        id=id,
        subject=kw.get("subject", "do something"),
        description=kw.get("description", "details"),
        worker_role=kw.get("worker_role", "coder"),
        worker_name=kw.get("worker_name", "alice"),
        blocked_by=blocked_by,
    )


# ---------------------------------------------------------------------------
# 1. add_task returns task with PENDING status (no dependencies)
# ---------------------------------------------------------------------------


async def test_add_task_pending() -> None:
    board = _make_board()
    task = await _add_simple(board, id="t1")

    assert task.id == "t1"
    assert task.status is TaskStatus.PENDING
    assert task.blocked_by == []


# ---------------------------------------------------------------------------
# 2. add_task with blocked_by returns task with BLOCKED status
# ---------------------------------------------------------------------------


async def test_add_task_blocked() -> None:
    board = _make_board()
    await _add_simple(board, id="task-1")
    task = await _add_simple(board, id="task-2", blocked_by=["task-1"])

    assert task.status is TaskStatus.BLOCKED
    assert task.blocked_by == ["task-1"]


# ---------------------------------------------------------------------------
# 3. update_status transitions PENDING -> IN_PROGRESS -> COMPLETED
# ---------------------------------------------------------------------------


async def test_update_status_lifecycle() -> None:
    board = _make_board()
    await _add_simple(board, id="t1")

    t = await board.update_status("t1", "in_progress")
    assert t.status is TaskStatus.IN_PROGRESS

    t = await board.update_status("t1", "completed", result="done!")
    assert t.status is TaskStatus.COMPLETED
    assert t.result == "done!"


# ---------------------------------------------------------------------------
# 4. Dependency resolution — blocked task becomes PENDING when blocker completes
# ---------------------------------------------------------------------------


async def test_resolve_dependencies() -> None:
    board = _make_board()
    await _add_simple(board, id="task-a")
    await _add_simple(board, id="task-b", blocked_by=["task-a"])

    # task-b is blocked
    tasks = await board.get_tasks()
    blocked = next(t for t in tasks if t.id == "task-b")
    assert blocked.status is TaskStatus.BLOCKED

    # Complete task-a -> task-b should become PENDING
    await board.update_status("task-a", "in_progress")
    await board.update_status("task-a", "completed")

    tasks = await board.get_tasks()
    formerly_blocked = next(t for t in tasks if t.id == "task-b")
    assert formerly_blocked.status is TaskStatus.PENDING
    assert formerly_blocked.blocked_by == []


async def test_resolve_dependencies_multiple_blockers() -> None:
    board = _make_board()
    await _add_simple(board, id="a")
    await _add_simple(board, id="b")
    await _add_simple(board, id="c", blocked_by=["a", "b"])

    # Complete only a — c should stay BLOCKED (still waiting on b)
    await board.update_status("a", "completed")
    tasks = await board.get_tasks()
    c = next(t for t in tasks if t.id == "c")
    assert c.status is TaskStatus.BLOCKED
    assert c.blocked_by == ["b"]

    # Complete b — now c becomes PENDING
    await board.update_status("b", "completed")
    tasks = await board.get_tasks()
    c = next(t for t in tasks if t.id == "c")
    assert c.status is TaskStatus.PENDING
    assert c.blocked_by == []


# ---------------------------------------------------------------------------
# 5. get_runnable_tasks returns only PENDING tasks
# ---------------------------------------------------------------------------


async def test_get_runnable_tasks() -> None:
    board = _make_board()
    await _add_simple(board, id="pending-1")
    await _add_simple(board, id="pending-2")
    await _add_simple(board, id="blocked-1", blocked_by=["pending-1"])
    await board.update_status("pending-2", "in_progress")

    runnable = await board.get_runnable_tasks()
    ids = [t.id for t in runnable]

    assert "pending-1" in ids
    assert "blocked-1" not in ids
    assert "pending-2" not in ids


# ---------------------------------------------------------------------------
# 6. get_runnable_tasks(owner=...) filters by worker_name
# ---------------------------------------------------------------------------


async def test_get_runnable_tasks_by_owner() -> None:
    board = _make_board()
    await _add_simple(board, id="t1", worker_name="alice")
    await _add_simple(board, id="t2", worker_name="bob")
    await _add_simple(board, id="t3", worker_name="alice")

    runnable = await board.get_runnable_tasks(owner="alice")
    ids = [t.id for t in runnable]

    assert ids == ["t1", "t3"]


# ---------------------------------------------------------------------------
# 7. Concurrent access — two async updates don't corrupt state
# ---------------------------------------------------------------------------


async def test_concurrent_updates() -> None:
    board = _make_board()
    # Create many tasks
    for i in range(20):
        await _add_simple(board, id=f"t{i}")

    async def complete(task_id: str) -> None:
        await board.update_status(task_id, "in_progress")
        await board.update_status(task_id, "completed", result=f"{task_id}-done")

    # Run all completions concurrently
    await asyncio.gather(*(complete(f"t{i}") for i in range(20)))

    tasks = await board.get_tasks()
    assert all(t.status is TaskStatus.COMPLETED for t in tasks)
    assert all(t.result == f"{t.id}-done" for t in tasks)


async def test_concurrent_add_and_resolve() -> None:
    board = _make_board()
    await _add_simple(board, id="blocker")

    # Add blocked tasks concurrently
    async def add_blocked(i: int) -> None:
        await _add_simple(board, id=f"dep-{i}", blocked_by=["blocker"])

    await asyncio.gather(*(add_blocked(i) for i in range(10)))

    # All should be BLOCKED
    tasks = await board.get_tasks()
    blocked = [t for t in tasks if t.id.startswith("dep-")]
    assert all(t.status is TaskStatus.BLOCKED for t in blocked)

    # Complete blocker -> all deps should become PENDING
    await board.update_status("blocker", "completed")

    tasks = await board.get_tasks()
    deps = [t for t in tasks if t.id.startswith("dep-")]
    assert all(t.status is TaskStatus.PENDING for t in deps)


# ---------------------------------------------------------------------------
# 8. get_tasks returns all tasks / filters by owner
# ---------------------------------------------------------------------------


async def test_get_tasks_all() -> None:
    board = _make_board()
    await _add_simple(board, id="t1", worker_name="alice")
    await _add_simple(board, id="t2", worker_name="bob")
    await _add_simple(board, id="t3", worker_name="alice")

    all_tasks = await board.get_tasks()
    assert len(all_tasks) == 3


async def test_get_tasks_filtered() -> None:
    board = _make_board()
    await _add_simple(board, id="t1", worker_name="alice")
    await _add_simple(board, id="t2", worker_name="bob")
    await _add_simple(board, id="t3", worker_name="alice")

    alice_tasks = await board.get_tasks(owner="alice")
    assert len(alice_tasks) == 2
    assert all(t.worker_name == "alice" for t in alice_tasks)

    bob_tasks = await board.get_tasks(owner="bob")
    assert len(bob_tasks) == 1
    assert bob_tasks[0].id == "t2"


async def test_get_tasks_no_match() -> None:
    board = _make_board()
    await _add_simple(board, id="t1", worker_name="alice")

    result = await board.get_tasks(owner="nobody")
    assert result == []
