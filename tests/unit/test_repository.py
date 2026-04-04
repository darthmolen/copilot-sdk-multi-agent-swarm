"""SwarmRepository unit tests — round tracking and suspend, no live DB."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from backend.db.repository import SwarmRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_engine() -> tuple[MagicMock, AsyncMock, AsyncMock]:
    """Build a mock AsyncEngine whose begin()/connect() return async CMs.

    engine.begin() and engine.connect() must be regular (non-async) methods
    that return async context managers, matching the real AsyncEngine API.
    """
    engine = MagicMock()

    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    # engine.begin() -> async CM yielding mock_conn (not a coroutine)
    cm = AsyncMock()
    cm.__aenter__ = AsyncMock(return_value=mock_conn)
    cm.__aexit__ = AsyncMock(return_value=False)
    engine.begin.return_value = cm

    # engine.connect() -> async CM yielding a read-only mock_conn
    read_conn = AsyncMock()
    read_cm = AsyncMock()
    read_cm.__aenter__ = AsyncMock(return_value=read_conn)
    read_cm.__aexit__ = AsyncMock(return_value=False)
    engine.connect.return_value = read_cm

    return engine, mock_conn, read_conn


# ---------------------------------------------------------------------------
# TestRoundTracking
# ---------------------------------------------------------------------------


class TestRoundTracking:
    async def test_update_round(self) -> None:
        """update_round() persists current_round to DB."""
        engine, mock_conn, _ = _make_engine()
        repo = SwarmRepository(engine)
        swarm_id = uuid4()

        await repo.update_round(swarm_id, round_number=3)

        mock_conn.execute.assert_awaited_once()
        stmt = mock_conn.execute.call_args[0][0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        sql_text = str(compiled)
        assert "current_round" in sql_text
        assert "swarms" in sql_text

    async def test_update_round_passes_correct_values(self) -> None:
        """update_round() passes the swarm_id and round_number correctly."""
        engine, mock_conn, _ = _make_engine()
        repo = SwarmRepository(engine)
        swarm_id = uuid4()

        await repo.update_round(swarm_id, round_number=5)

        mock_conn.execute.assert_awaited_once()
        stmt = mock_conn.execute.call_args[0][0]
        # Check the statement has correct parameters bound
        params = stmt.compile().params
        assert params["current_round"] == 5

    async def test_suspend_swarm(self) -> None:
        """suspend_swarm() sets phase='suspended' and suspended_at."""
        engine, mock_conn, _ = _make_engine()
        repo = SwarmRepository(engine)
        swarm_id = uuid4()

        await repo.suspend_swarm(swarm_id)

        mock_conn.execute.assert_awaited_once()
        stmt = mock_conn.execute.call_args[0][0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        sql_text = str(compiled)
        assert "suspended" in sql_text
        assert "suspended_at" in sql_text
        assert "phase" in sql_text

    async def test_suspend_swarm_sets_phase_value(self) -> None:
        """suspend_swarm() sets phase to exactly 'suspended'."""
        engine, mock_conn, _ = _make_engine()
        repo = SwarmRepository(engine)
        swarm_id = uuid4()

        await repo.suspend_swarm(swarm_id)

        stmt = mock_conn.execute.call_args[0][0]
        params = stmt.compile().params
        assert params["phase"] == "suspended"

    async def test_load_swarm_state_includes_round_info(self) -> None:
        """load_swarm_state() returns current_round and max_rounds from the swarm row."""
        engine, _mock_conn, _read_conn = _make_engine()
        repo = SwarmRepository(engine)
        swarm_id = uuid4()

        # Mock get_swarm to return a row with round info
        fake_swarm = {
            "id": swarm_id,
            "goal": "Test",
            "phase": "executing",
            "current_round": 3,
            "max_rounds": 8,
            "suspended_at": None,
            "template_key": None,
            "qa_refined_goal": None,
            "synthesis_session_id": None,
            "report": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "completed_at": None,
        }

        with (
            patch.object(repo, "get_swarm", return_value=fake_swarm),
            patch.object(repo, "get_tasks", return_value=[]),
            patch.object(repo, "_get_all_agents", return_value=[]),
            patch.object(repo, "get_messages", return_value=[]),
            patch.object(repo, "get_files", return_value=[]),
        ):
            state = await repo.load_swarm_state(swarm_id)

        assert state["swarm"]["current_round"] == 3
        assert state["swarm"]["max_rounds"] == 8
        assert state["swarm"]["suspended_at"] is None


# ---------------------------------------------------------------------------
# Table schema tests — verify columns exist
# ---------------------------------------------------------------------------


class TestSwarmTableSchema:
    def test_swarms_table_has_current_round_column(self) -> None:
        """swarms table must have a current_round column."""
        from backend.db.tables import swarms

        col_names = {c.name for c in swarms.columns}
        assert "current_round" in col_names

    def test_swarms_table_has_max_rounds_column(self) -> None:
        """swarms table must have a max_rounds column."""
        from backend.db.tables import swarms

        col_names = {c.name for c in swarms.columns}
        assert "max_rounds" in col_names

    def test_swarms_table_has_suspended_at_column(self) -> None:
        """swarms table must have a suspended_at column."""
        from backend.db.tables import swarms

        col_names = {c.name for c in swarms.columns}
        assert "suspended_at" in col_names

    def test_current_round_defaults_to_zero(self) -> None:
        """current_round column should default to 0."""
        from backend.db.tables import swarms

        col = swarms.c.current_round
        assert col.server_default is not None
        assert col.server_default.arg == "0"  # type: ignore[union-attr]

    def test_max_rounds_defaults_to_eight(self) -> None:
        """max_rounds column should default to 8."""
        from backend.db.tables import swarms

        col = swarms.c.max_rounds
        assert col.server_default is not None
        assert col.server_default.arg == "8"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# TestListSwarmsByPhase
# ---------------------------------------------------------------------------


class TestListSwarmsByPhase:
    async def test_filters_by_single_phase(self) -> None:
        """list_swarms_by_phase('executing') returns only executing swarms."""
        engine, _mock_conn, read_conn = _make_engine()

        # Simulate rows returned from DB
        fake_rows = [
            {"id": uuid4(), "goal": "A", "phase": "executing"},
        ]
        read_conn.execute = AsyncMock(
            return_value=MagicMock(mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=fake_rows))))
        )

        repo = SwarmRepository(engine)
        result = await repo.list_swarms_by_phase("executing")

        assert len(result) == 1
        assert result[0]["phase"] == "executing"

        # Verify the SQL statement contains WHERE ... IN clause
        stmt = read_conn.execute.call_args[0][0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        sql_text = str(compiled)
        assert "IN" in sql_text.upper()
        assert "phase" in sql_text

    async def test_filters_by_multiple_phases(self) -> None:
        """list_swarms_by_phase('executing', 'planning') returns both."""
        engine, _mock_conn, read_conn = _make_engine()

        fake_rows = [
            {"id": uuid4(), "goal": "A", "phase": "executing"},
            {"id": uuid4(), "goal": "B", "phase": "planning"},
        ]
        read_conn.execute = AsyncMock(
            return_value=MagicMock(mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=fake_rows))))
        )

        repo = SwarmRepository(engine)
        result = await repo.list_swarms_by_phase("executing", "planning")

        assert len(result) == 2

        # Verify the SQL statement includes both phases in IN clause
        stmt = read_conn.execute.call_args[0][0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": True})
        sql_text = str(compiled)
        assert "IN" in sql_text.upper()

    async def test_returns_empty_for_no_matches(self) -> None:
        """Returns empty list when no swarms match."""
        engine, _mock_conn, read_conn = _make_engine()

        read_conn.execute = AsyncMock(
            return_value=MagicMock(mappings=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
        )

        repo = SwarmRepository(engine)
        result = await repo.list_swarms_by_phase("nonexistent_phase")

        assert result == []
