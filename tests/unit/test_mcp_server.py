"""Unit tests for the Swarm State MCP server tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from backend.mcp.deps import MCPDeps
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_orchestrator(
    task_board: TaskBoard,
    registry: TeamRegistry,
    agents: dict | None = None,
) -> MagicMock:
    orch = MagicMock()
    orch.service = MagicMock()
    orch.service.task_board = task_board
    orch.service.registry = registry
    orch.agents = agents or {}
    return orch


async def _make_deps(
    tmp_path: Path,
    swarm_id: str = "swarm-1",
    phase: str = "executing",
    round_number: int = 2,
    tasks: list[dict] | None = None,
    agents: list[dict] | None = None,
    orch_agents: dict | None = None,
    repository: Any = None,
) -> MCPDeps:
    """Build MCPDeps with a populated swarm_store."""
    task_board = TaskBoard()
    registry = TeamRegistry()

    for t in tasks or []:
        await task_board.add_task(
            id=t["id"],
            subject=t["subject"],
            description=t["description"],
            worker_role=t["worker_role"],
            worker_name=t["worker_name"],
        )
        if t.get("status") and t["status"] != "pending":
            await task_board.update_status(t["id"], t["status"], t.get("result", ""))

    for a in agents or []:
        await registry.register(a["name"], a["role"], a.get("display_name", ""))
        if a.get("status"):
            await registry.update_status(a["name"], a["status"])
        for _ in range(a.get("tasks_completed", 0)):
            await registry.increment_tasks_completed(a["name"])

    orch = _make_orchestrator(task_board, registry, orch_agents)

    work_dir = str(tmp_path / "workdir")
    swarm_dir = Path(work_dir) / swarm_id
    swarm_dir.mkdir(parents=True, exist_ok=True)

    deps = MCPDeps(
        swarm_store={
            swarm_id: {
                "swarm_id": swarm_id,
                "goal": "Test goal",
                "template": None,
                "phase": phase,
                "round_number": round_number,
                "orchestrator": orch,
            }
        },
        work_dir=work_dir,
        repository=repository,
    )
    return deps


# ---------------------------------------------------------------------------
# get_active_swarms
# ---------------------------------------------------------------------------


class TestGetActiveSwarms:
    async def test_returns_all_swarms(self, tmp_path: Path):
        deps = await _make_deps(tmp_path, swarm_id="swarm-1", phase="executing")
        deps.swarm_store["swarm-2"] = {
            "swarm_id": "swarm-2",
            "phase": "complete",
            "round_number": 3,
            "goal": "Build a report",
            "template": "azure-solutions-agent",
            "orchestrator": _make_orchestrator(TaskBoard(), TeamRegistry()),
        }
        deps.swarm_store["swarm-1"]["goal"] = "Analyze data"
        deps.swarm_store["swarm-1"]["template"] = "warehouse-optimizer"

        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_active_swarms

            result = await get_active_swarms()
        assert len(result) == 2
        ids = {s["swarm_id"] for s in result}
        assert ids == {"swarm-1", "swarm-2"}

    async def test_empty_store(self, tmp_path: Path):
        deps = MCPDeps(swarm_store={}, work_dir=str(tmp_path))
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_active_swarms

            result = await get_active_swarms()
        assert result == []


# ---------------------------------------------------------------------------
# get_swarm_status
# ---------------------------------------------------------------------------


class TestGetSwarmStatus:
    async def test_returns_phase_round_and_counts(self, tmp_path: Path):
        deps = await _make_deps(
            tmp_path,
            tasks=[
                {
                    "id": "t1",
                    "subject": "A",
                    "description": "a",
                    "worker_role": "r",
                    "worker_name": "w1",
                    "status": "completed",
                },
                {
                    "id": "t2",
                    "subject": "B",
                    "description": "b",
                    "worker_role": "r",
                    "worker_name": "w1",
                    "status": "in_progress",
                },
                {"id": "t3", "subject": "C", "description": "c", "worker_role": "r", "worker_name": "w2"},
            ],
            agents=[
                {"name": "w1", "role": "Worker", "status": "working"},
                {"name": "w2", "role": "Writer", "status": "idle"},
            ],
        )
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_swarm_status

            result = await get_swarm_status(swarm_id="swarm-1")

        assert result["phase"] == "executing"
        assert result["round_number"] == 2
        assert result["agent_count"] == 2
        assert result["task_counts"]["completed"] == 1
        assert result["task_counts"]["in_progress"] == 1
        assert result["task_counts"]["pending"] == 1

    async def test_unknown_swarm_id_raises(self, tmp_path: Path):
        deps = await _make_deps(tmp_path, swarm_id="swarm-1")
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_swarm_status

            with pytest.raises(ToolError, match="not found"):
                await get_swarm_status(swarm_id="nonexistent")


# ---------------------------------------------------------------------------
# list_tasks
# ---------------------------------------------------------------------------


class TestListTasks:
    async def test_returns_all_tasks(self, tmp_path: Path):
        deps = await _make_deps(
            tmp_path,
            tasks=[
                {"id": "t1", "subject": "A", "description": "a", "worker_role": "r", "worker_name": "w1"},
                {"id": "t2", "subject": "B", "description": "b", "worker_role": "r", "worker_name": "w2"},
            ],
        )
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import list_tasks

            result = await list_tasks(swarm_id="swarm-1")
        assert len(result) == 2

    async def test_filter_by_status(self, tmp_path: Path):
        deps = await _make_deps(
            tmp_path,
            tasks=[
                {
                    "id": "t1",
                    "subject": "A",
                    "description": "a",
                    "worker_role": "r",
                    "worker_name": "w1",
                    "status": "completed",
                    "result": "done",
                },
                {"id": "t2", "subject": "B", "description": "b", "worker_role": "r", "worker_name": "w1"},
            ],
        )
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import list_tasks

            result = await list_tasks(swarm_id="swarm-1", status="completed")
        assert len(result) == 1
        assert result[0]["id"] == "t1"

    async def test_filter_by_worker(self, tmp_path: Path):
        deps = await _make_deps(
            tmp_path,
            tasks=[
                {"id": "t1", "subject": "A", "description": "a", "worker_role": "r", "worker_name": "w1"},
                {"id": "t2", "subject": "B", "description": "b", "worker_role": "r", "worker_name": "w2"},
            ],
        )
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import list_tasks

            result = await list_tasks(swarm_id="swarm-1", worker="w2")
        assert len(result) == 1
        assert result[0]["worker_name"] == "w2"


# ---------------------------------------------------------------------------
# get_task_detail
# ---------------------------------------------------------------------------


class TestGetTaskDetail:
    async def test_found(self, tmp_path: Path):
        deps = await _make_deps(
            tmp_path,
            tasks=[
                {
                    "id": "t1",
                    "subject": "Analyze",
                    "description": "deep dive",
                    "worker_role": "analyst",
                    "worker_name": "analyst",
                    "status": "completed",
                    "result": "Found 3 issues.",
                },
            ],
        )
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_task_detail

            result = await get_task_detail(swarm_id="swarm-1", task_id="t1")
        assert result["id"] == "t1"
        assert result["result"] == "Found 3 issues."

    async def test_not_found_raises(self, tmp_path: Path):
        deps = await _make_deps(tmp_path, tasks=[])
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_task_detail

            with pytest.raises(ToolError, match="not found"):
                await get_task_detail(swarm_id="swarm-1", task_id="nonexistent")


# ---------------------------------------------------------------------------
# get_recent_events
# ---------------------------------------------------------------------------


class TestGetRecentEvents:
    async def test_with_repository(self, tmp_path: Path):
        mock_repo = AsyncMock()
        mock_repo.get_events.return_value = [
            {"event_type": "task.completed", "data": {"task_id": "t1"}},
            {"event_type": "agent.started", "data": {"agent": "w1"}},
        ]
        deps = await _make_deps(tmp_path, repository=mock_repo)
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_recent_events

            result = await get_recent_events(swarm_id="swarm-1", count=10)
        assert len(result) == 2
        mock_repo.get_events.assert_awaited_once()

    async def test_returns_limited_events(self, tmp_path: Path):
        """get_recent_events respects the count parameter."""
        mock_repo = AsyncMock()
        mock_repo.get_events.return_value = [
            {"event_type": f"event.{i}", "data": {}} for i in range(30)
        ]
        deps = await _make_deps(tmp_path, repository=mock_repo)
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_recent_events

            result = await get_recent_events(swarm_id="swarm-1", count=5)
        assert len(result) == 5


# ---------------------------------------------------------------------------
# list_agents
# ---------------------------------------------------------------------------


class TestListAgents:
    async def test_returns_all_agents(self, tmp_path: Path):
        deps = await _make_deps(
            tmp_path,
            agents=[
                {
                    "name": "analyst",
                    "role": "Data Analyst",
                    "display_name": "Analyst",
                    "status": "working",
                    "tasks_completed": 3,
                },
                {"name": "writer", "role": "Writer", "display_name": "Writer", "status": "idle", "tasks_completed": 0},
            ],
        )
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import list_agents

            result = await list_agents(swarm_id="swarm-1")
        assert len(result) == 2
        analyst = next(a for a in result if a["name"] == "analyst")
        assert analyst["role"] == "Data Analyst"
        assert analyst["status"] == "working"
        assert analyst["tasks_completed"] == 3


# ---------------------------------------------------------------------------
# list_artifacts / read_artifact
# ---------------------------------------------------------------------------


class TestArtifacts:
    async def test_list_artifacts(self, tmp_path: Path):
        deps = await _make_deps(tmp_path)
        swarm_dir = Path(deps.work_dir) / "swarm-1"
        (swarm_dir / "report.md").write_text("# Report")
        (swarm_dir / "data.json").write_text('{"key": "value"}')

        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import list_artifacts

            result = await list_artifacts(swarm_id="swarm-1")
        assert len(result) == 2
        names = {a["name"] for a in result}
        assert "report.md" in names
        assert "data.json" in names

    async def test_read_artifact_success(self, tmp_path: Path):
        deps = await _make_deps(tmp_path)
        swarm_dir = Path(deps.work_dir) / "swarm-1"
        (swarm_dir / "report.md").write_text("# Hello World")

        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import read_artifact

            result = await read_artifact(swarm_id="swarm-1", path="report.md")
        assert result["content"] == "# Hello World"

    async def test_read_artifact_not_found_raises(self, tmp_path: Path):
        deps = await _make_deps(tmp_path)
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import read_artifact

            with pytest.raises(ToolError, match="File not found"):
                await read_artifact(swarm_id="swarm-1", path="nonexistent.txt")

    async def test_read_artifact_path_traversal_raises(self, tmp_path: Path):
        deps = await _make_deps(tmp_path)
        (tmp_path / "secret.txt").write_text("SECRET")

        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import read_artifact

            with pytest.raises(ToolError, match="Path traversal"):
                await read_artifact(swarm_id="swarm-1", path="../../secret.txt")


# ---------------------------------------------------------------------------
# resume_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestResumeAgent:
    async def test_success(self, tmp_path: Path) -> None:
        """resume_agent MCP tool calls orchestrator.resume_agent."""
        mock_orch = _make_orchestrator(TaskBoard(), TeamRegistry())
        mock_orch.resume_agent = AsyncMock(return_value=None)
        deps = await _make_deps(tmp_path, orch_agents={"analyst": MagicMock()})
        deps.swarm_store["swarm-1"]["orchestrator"] = mock_orch

        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import resume_agent

            result = await resume_agent(swarm_id="swarm-1", agent_name="analyst")
        assert result["ok"] is True
        assert result["resumed"] is True
        mock_orch.resume_agent.assert_awaited_once_with("analyst", "")

    async def test_unknown_agent_raises_tool_error(self, tmp_path: Path) -> None:
        """resume_agent MCP tool raises ToolError for unknown agent."""
        mock_orch = _make_orchestrator(TaskBoard(), TeamRegistry())
        mock_orch.resume_agent = AsyncMock(side_effect=KeyError("Agent 'ghost' not found"))
        deps = await _make_deps(tmp_path)
        deps.swarm_store["swarm-1"]["orchestrator"] = mock_orch

        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import resume_agent

            with pytest.raises(ToolError, match="ghost"):
                await resume_agent(swarm_id="swarm-1", agent_name="ghost")


# ---------------------------------------------------------------------------
# _resolve_swarm_id
# ---------------------------------------------------------------------------


class TestResolveSwarmId:
    async def test_valid_swarm_id(self, tmp_path: Path):
        deps = await _make_deps(tmp_path, swarm_id="my-swarm")
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_swarm_status

            result = await get_swarm_status(swarm_id="my-swarm")
        assert result["phase"] == "executing"

    async def test_unknown_swarm_id_raises(self, tmp_path: Path):
        deps = await _make_deps(tmp_path, swarm_id="swarm-1")
        with patch("backend.mcp.server.get_deps", return_value=deps):
            from backend.mcp.server import get_swarm_status

            with pytest.raises(ToolError, match="not found"):
                await get_swarm_status(swarm_id="wrong-id")
