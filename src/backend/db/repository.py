"""SwarmRepository — pure data access layer for Postgres persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.db.tables import agents, events, files, messages, swarms, tasks


class SwarmRepository:
    """Pure data access — no business logic, no cache awareness."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------------
    # Swarms
    # ------------------------------------------------------------------

    async def create_swarm(
        self,
        swarm_id: UUID,
        goal: str,
        template_key: str | None = None,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(swarms.insert().values(id=swarm_id, goal=goal, template_key=template_key))

    async def get_swarm(self, swarm_id: UUID) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (await conn.execute(swarms.select().where(swarms.c.id == swarm_id))).mappings().first()
        return dict(row) if row else None

    async def update_phase(self, swarm_id: UUID, phase: str) -> None:
        values: dict[str, Any] = {"phase": phase, "updated_at": _now()}
        if phase == "complete":
            values["completed_at"] = _now()
        async with self._engine.begin() as conn:
            await conn.execute(swarms.update().where(swarms.c.id == swarm_id).values(**values))

    async def update_swarm(self, swarm_id: UUID, **kwargs: Any) -> None:
        kwargs["updated_at"] = _now()
        if kwargs.get("phase") == "complete":
            kwargs.setdefault("completed_at", _now())
        async with self._engine.begin() as conn:
            await conn.execute(swarms.update().where(swarms.c.id == swarm_id).values(**kwargs))

    async def update_round(self, swarm_id: UUID, round_number: int) -> None:
        """Update the current round number for a swarm."""
        async with self._engine.begin() as conn:
            await conn.execute(
                swarms.update().where(swarms.c.id == swarm_id).values(current_round=round_number, updated_at=_now())
            )

    async def suspend_swarm(self, swarm_id: UUID) -> None:
        """Mark a swarm as suspended."""
        async with self._engine.begin() as conn:
            await conn.execute(
                swarms.update()
                .where(swarms.c.id == swarm_id)
                .values(
                    phase="suspended",
                    suspended_at=sa.func.now(),
                    updated_at=_now(),
                )
            )

    async def list_swarms(self) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(swarms.select().order_by(swarms.c.created_at.desc()))).mappings().all()
        return [dict(r) for r in rows]

    async def list_swarms_by_phase(self, *phases: str) -> list[dict[str, Any]]:
        """Find swarms in specific phases (for orphan detection)."""
        stmt = swarms.select().where(
            swarms.c.phase.in_(phases)
        ).order_by(swarms.c.created_at.desc())
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def create_task(
        self,
        swarm_id: UUID,
        task_id: str,
        subject: str,
        description: str,
        worker_role: str,
        worker_name: str,
        blocked_by: list[str] | None = None,
        status: str = "pending",
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                tasks.insert().values(
                    swarm_id=swarm_id,
                    id=task_id,
                    subject=subject,
                    description=description,
                    worker_role=worker_role,
                    worker_name=worker_name,
                    blocked_by=blocked_by or [],
                    status=status,
                )
            )

    async def get_tasks(self, swarm_id: UUID) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = (
                (await conn.execute(tasks.select().where(tasks.c.swarm_id == swarm_id).order_by(tasks.c.id)))
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    async def update_task_status(
        self,
        swarm_id: UUID,
        task_id: str,
        status: str,
        result: str = "",
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                tasks.update()
                .where(tasks.c.swarm_id == swarm_id, tasks.c.id == task_id)
                .values(status=status, result=result, updated_at=_now())
            )

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    async def register_agent(
        self,
        swarm_id: UUID,
        name: str,
        role: str,
        display_name: str = "",
        session_id: str | None = None,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                agents.insert().values(
                    swarm_id=swarm_id,
                    name=name,
                    role=role,
                    display_name=display_name,
                    session_id=session_id,
                )
            )

    async def get_agent(self, swarm_id: UUID, name: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                (await conn.execute(agents.select().where(agents.c.swarm_id == swarm_id, agents.c.name == name)))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def update_agent(
        self,
        swarm_id: UUID,
        name: str,
        **kwargs: Any,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                agents.update().where(agents.c.swarm_id == swarm_id, agents.c.name == name).values(**kwargs)
            )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def save_message(
        self,
        swarm_id: UUID,
        sender: str,
        recipient: str,
        content: str,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                messages.insert().values(
                    swarm_id=swarm_id,
                    sender=sender,
                    recipient=recipient,
                    content=content,
                )
            )

    async def get_messages(self, swarm_id: UUID) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = (
                (
                    await conn.execute(
                        messages.select().where(messages.c.swarm_id == swarm_id).order_by(messages.c.created_at)
                    )
                )
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Files
    # ------------------------------------------------------------------

    async def save_file(
        self,
        swarm_id: UUID,
        path: str,
        size_bytes: int = 0,
    ) -> None:
        async with self._engine.begin() as conn:
            stmt = pg_insert(files).values(
                swarm_id=swarm_id,
                path=path,
                size_bytes=size_bytes,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_files_swarm_path",
                set_={"size_bytes": stmt.excluded.size_bytes},
            )
            await conn.execute(stmt)

    async def get_files(self, swarm_id: UUID) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = (
                (await conn.execute(files.select().where(files.c.swarm_id == swarm_id).order_by(files.c.path)))
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    async def save_event(
        self,
        swarm_id: UUID | None,
        event_type: str,
        data: dict[str, Any],
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                events.insert().values(
                    swarm_id=swarm_id,
                    event_type=event_type,
                    data_json=data,
                )
            )

    async def get_task_events(
        self,
        swarm_id: UUID,
        task_id: str,
    ) -> list[dict[str, Any]]:
        """Get events related to a specific task."""
        stmt = (
            events.select()
            .where(
                sa.and_(
                    events.c.swarm_id == swarm_id,
                    events.c.data_json["task_id"].as_string() == task_id,
                )
            )
            .order_by(events.c.created_at)
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    async def get_events(
        self,
        swarm_id: UUID,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        stmt = events.select().where(events.c.swarm_id == swarm_id)
        if since is not None:
            stmt = stmt.where(events.c.created_at > since)
        stmt = stmt.order_by(events.c.created_at)
        async with self._engine.connect() as conn:
            rows = (await conn.execute(stmt)).mappings().all()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Full state load (for recovery)
    # ------------------------------------------------------------------

    async def load_swarm_state(self, swarm_id: UUID) -> dict[str, Any]:
        """Load complete swarm state for recovery/hydration."""
        swarm = await self.get_swarm(swarm_id)
        if swarm is None:
            raise ValueError(f"Swarm {swarm_id} not found")
        return {
            "swarm": swarm,
            "tasks": await self.get_tasks(swarm_id),
            "agents": await self._get_all_agents(swarm_id),
            "messages": await self.get_messages(swarm_id),
            "files": await self.get_files(swarm_id),
        }

    async def _get_all_agents(self, swarm_id: UUID) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = (
                (await conn.execute(agents.select().where(agents.c.swarm_id == swarm_id).order_by(agents.c.name)))
                .mappings()
                .all()
            )
        return [dict(r) for r in rows]


def _now() -> datetime:
    return datetime.now(timezone.utc)
