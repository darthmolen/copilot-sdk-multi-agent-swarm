"""TaskBoard: manages tasks with dependency resolution and async-safe mutations."""

from __future__ import annotations

import asyncio

from backend.swarm.models import Task, TaskStatus


class TaskBoard:
    """Async-safe task board with dependency tracking."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def add_task(
        self,
        id: str,
        subject: str,
        description: str,
        worker_role: str,
        worker_name: str,
        blocked_by: list[str] | None = None,
    ) -> Task:
        """Create a task. If *blocked_by* is non-empty the task starts BLOCKED."""
        async with self._lock:
            deps = list(blocked_by) if blocked_by else []
            status = TaskStatus.BLOCKED if deps else TaskStatus.PENDING
            task = Task(
                id=id,
                subject=subject,
                description=description,
                worker_role=worker_role,
                worker_name=worker_name,
                status=status,
                blocked_by=deps,
            )
            self._tasks[id] = task
            return task

    async def update_status(
        self, task_id: str, status: str, result: str = ""
    ) -> Task:
        """Transition a task to a new status.

        When transitioning to COMPLETED, dependency resolution is triggered
        automatically so that blocked downstream tasks may become PENDING.
        """
        async with self._lock:
            task = self._tasks[task_id]
            task.status = TaskStatus(status)
            if result:
                task.result = result
            if task.status is TaskStatus.COMPLETED:
                self._resolve_dependencies(task_id)
            return task

    async def get_runnable_tasks(
        self, owner: str | None = None
    ) -> list[Task]:
        """Return tasks in PENDING status, optionally filtered by *owner*."""
        async with self._lock:
            tasks = [
                t for t in self._tasks.values() if t.status is TaskStatus.PENDING
            ]
            if owner is not None:
                tasks = [t for t in tasks if t.worker_name == owner]
            return tasks

    async def get_tasks(self, owner: str | None = None) -> list[Task]:
        """Return all tasks, optionally filtered by *owner* (worker_name)."""
        async with self._lock:
            tasks = list(self._tasks.values())
            if owner is not None:
                tasks = [t for t in tasks if t.worker_name == owner]
            return tasks

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_dependencies(self, completed_task_id: str) -> None:
        """Remove *completed_task_id* from every task's blocked_by list.

        Tasks whose blocked_by becomes empty transition BLOCKED -> PENDING.

        **Must be called while holding self._lock.**
        """
        for task in self._tasks.values():
            if completed_task_id in task.blocked_by:
                task.blocked_by.remove(completed_task_id)
                if not task.blocked_by and task.status is TaskStatus.BLOCKED:
                    task.status = TaskStatus.PENDING
