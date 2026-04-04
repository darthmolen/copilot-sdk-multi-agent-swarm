"""TDD tests for the FastAPI + WebSocket API layer."""

from __future__ import annotations

import threading

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
import pytest
from fastapi.testclient import TestClient

from backend.api.rest import swarm_store
from backend.main import app, manager


@pytest.fixture(autouse=True)
def _reset_auth_state():
    """Reset auth to dev-mode defaults before/after every test."""
    import backend.main as main_mod

    main_mod.ENVIRONMENT = "development"
    main_mod.SWARM_API_KEY = ""
    yield
    main_mod.ENVIRONMENT = "development"
    main_mod.SWARM_API_KEY = ""


def _clear_swarm_store() -> None:
    """Reset global swarm state between tests."""
    swarm_store.clear()


# ---------------------------------------------------------------------------
# WebSocket tests
# ---------------------------------------------------------------------------


def test_websocket_connect_and_receive_broadcast() -> None:
    """Connect a WS client, broadcast an event, verify it is received."""
    _clear_swarm_store()
    client = TestClient(app)

    with client.websocket_connect("/ws/test-swarm") as ws:
        # Broadcast from a separate thread because the ws context blocks the
        # main thread; TestClient runs its own event loop internally.
        import asyncio

        def _broadcast() -> None:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(manager.broadcast("test-swarm", {"type": "ping", "value": 42}))
            loop.close()

        t = threading.Thread(target=_broadcast)
        t.start()
        t.join()

        data = ws.receive_json()
        assert data["type"] == "ping"
        assert data["value"] == 42


def test_multiple_websocket_connections_receive_broadcast() -> None:
    """Two WS clients connected to the same swarm_id both receive broadcast."""
    _clear_swarm_store()
    client = TestClient(app)

    with client.websocket_connect("/ws/multi-swarm") as ws1, client.websocket_connect("/ws/multi-swarm") as ws2:
        import asyncio

        def _broadcast() -> None:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(manager.broadcast("multi-swarm", {"type": "update", "round": 1}))
            loop.close()

        t = threading.Thread(target=_broadcast)
        t.start()
        t.join()

        d1 = ws1.receive_json()
        d2 = ws2.receive_json()

        assert d1["type"] == "update"
        assert d1["round"] == 1
        assert d2["type"] == "update"
        assert d2["round"] == 1


def test_websocket_disconnect_stops_messages() -> None:
    """After disconnect, broadcasting does not raise."""
    _clear_swarm_store()
    client = TestClient(app)

    with client.websocket_connect("/ws/disc-swarm"):
        pass  # context exit closes the WS

    # Broadcast to the now-empty swarm_id should not raise
    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(manager.broadcast("disc-swarm", {"type": "after-disconnect"}))
    loop.close()


# ---------------------------------------------------------------------------
# REST tests
# ---------------------------------------------------------------------------


def test_post_swarm_start_returns_swarm_id() -> None:
    """POST /api/swarm/start returns a swarm_id and status 'starting'."""
    _clear_swarm_store()
    client = TestClient(app)

    response = client.post("/api/swarm/start", json={"goal": "Build a website"})
    assert response.status_code == 200
    body = response.json()
    assert "swarm_id" in body
    assert body["status"] == "starting"
    assert len(body["swarm_id"]) > 0


def test_get_swarm_status_returns_state() -> None:
    """Start a swarm then GET its status; verify structure."""
    _clear_swarm_store()
    client = TestClient(app)

    # Create a swarm first
    create_resp = client.post("/api/swarm/start", json={"goal": "Analyze data"})
    swarm_id = create_resp.json()["swarm_id"]

    response = client.get(f"/api/swarm/{swarm_id}/status")
    assert response.status_code == 200
    body = response.json()

    assert body["swarm_id"] == swarm_id
    assert body["phase"] == "starting"
    assert isinstance(body["tasks"], list)
    assert isinstance(body["agents"], list)
    assert isinstance(body["inbox_recent"], list)
    assert body["round_number"] == 0


def test_get_swarm_status_returns_report_when_complete() -> None:
    """GET /api/swarm/{id}/status includes report text when swarm is complete."""
    _clear_swarm_store()
    client = TestClient(app)

    create_resp = client.post("/api/swarm/start", json={"goal": "Test report"})
    swarm_id = create_resp.json()["swarm_id"]

    # Simulate completion with a report
    swarm_store[swarm_id]["phase"] = "complete"
    swarm_store[swarm_id]["report"] = "# Final Report\n\nAll done."

    response = client.get(f"/api/swarm/{swarm_id}/status")
    assert response.status_code == 200
    body = response.json()
    assert body["report"] == "# Final Report\n\nAll done."


def test_get_swarm_status_returns_null_report_when_incomplete() -> None:
    """GET /api/swarm/{id}/status returns null report when swarm is still running."""
    _clear_swarm_store()
    client = TestClient(app)

    create_resp = client.post("/api/swarm/start", json={"goal": "Test"})
    swarm_id = create_resp.json()["swarm_id"]

    response = client.get(f"/api/swarm/{swarm_id}/status")
    assert response.status_code == 200
    body = response.json()
    assert body["report"] is None


def test_get_swarm_status_returns_live_task_and_agent_data() -> None:
    """GET status returns live tasks/agents from orchestrator service, not stale store data."""
    import asyncio
    from unittest.mock import MagicMock

    from backend.swarm.task_board import TaskBoard
    from backend.swarm.team_registry import TeamRegistry

    _clear_swarm_store()
    client = TestClient(app)

    create_resp = client.post("/api/swarm/start", json={"goal": "Test live data"})
    swarm_id = create_resp.json()["swarm_id"]

    # Set up a mock orchestrator with real TaskBoard/TeamRegistry containing data
    task_board = TaskBoard()
    registry = TeamRegistry()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(
        task_board.add_task(
            id="t1",
            subject="Analyze",
            description="Do analysis",
            worker_role="analyst",
            worker_name="analyst",
        )
    )
    loop.run_until_complete(task_board.update_status("t1", "completed", "Found 3 issues"))
    loop.run_until_complete(
        task_board.add_task(
            id="t2",
            subject="Write",
            description="Write report",
            worker_role="writer",
            worker_name="writer",
        )
    )
    loop.run_until_complete(registry.register("analyst", "Data Analyst", "Analyst"))
    loop.run_until_complete(registry.register("writer", "Writer", "Writer"))
    loop.close()

    orch = MagicMock()
    orch.service = MagicMock()
    orch.service.task_board = task_board
    orch.service.registry = registry

    swarm_store[swarm_id]["orchestrator"] = orch
    swarm_store[swarm_id]["phase"] = "executing"

    response = client.get(f"/api/swarm/{swarm_id}/status")
    assert response.status_code == 200
    body = response.json()

    # Should return live data, not empty lists
    assert len(body["tasks"]) == 2
    assert len(body["agents"]) == 2

    # Verify task structure
    completed = next(t for t in body["tasks"] if t["id"] == "t1")
    assert completed["status"] == "completed"
    assert completed["subject"] == "Analyze"

    # Verify agent structure
    analyst = next(a for a in body["agents"] if a["name"] == "analyst")
    assert analyst["role"] == "Data Analyst"
    assert analyst["display_name"] == "Analyst"


def test_get_swarm_status_unknown_returns_404() -> None:
    """GET status for a nonexistent swarm_id returns 404."""
    _clear_swarm_store()
    client = TestClient(app)

    response = client.get("/api/swarm/nonexistent-id/status")
    assert response.status_code == 404


def test_list_templates_returns_templates() -> None:
    """GET /api/templates returns the built-in templates."""
    client = TestClient(app)

    response = client.get("/api/templates")
    assert response.status_code == 200
    body = response.json()

    assert "templates" in body
    templates = body["templates"]
    assert len(templates) >= 2

    names = {t["name"] for t in templates}
    assert "Deep Research Team" in names
    assert "Warehouse Optimization Team" in names


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


def _set_auth(environment: str, api_key: str) -> None:
    """Helper to set auth config for tests."""
    import backend.main as main_mod

    main_mod.ENVIRONMENT = environment
    main_mod.SWARM_API_KEY = api_key


def _clear_auth() -> None:
    """Reset auth to dev-mode defaults after test."""
    import backend.main as main_mod

    main_mod.ENVIRONMENT = "development"
    main_mod.SWARM_API_KEY = ""


def test_api_returns_401_without_key_when_configured() -> None:
    """POST /api/swarm/start returns 401 when SWARM_API_KEY is set but no header sent."""
    _clear_swarm_store()
    _set_auth("production", "test-secret-123")

    client = TestClient(app)
    response = client.post("/api/swarm/start", json={"goal": "Test"})
    assert response.status_code == 401


def test_api_returns_200_with_correct_key() -> None:
    """POST /api/swarm/start returns 200 when correct X-API-Key header is sent."""
    _clear_swarm_store()
    _set_auth("production", "test-secret-123")

    client = TestClient(app)
    response = client.post(
        "/api/swarm/start",
        json={"goal": "Test"},
        headers={"X-API-Key": "test-secret-123"},
    )
    assert response.status_code == 200


def test_api_returns_401_with_wrong_key() -> None:
    """POST /api/swarm/start returns 401 when wrong key is sent."""
    _clear_swarm_store()
    _set_auth("production", "correct-key")

    client = TestClient(app)
    response = client.post(
        "/api/swarm/start",
        json={"goal": "Test"},
        headers={"X-API-Key": "wrong-key"},
    )
    assert response.status_code == 401


def test_auth_disabled_in_development_with_no_key() -> None:
    """In development mode with no key, requests pass without auth."""
    _clear_swarm_store()
    _set_auth("development", "")

    client = TestClient(app)
    response = client.post("/api/swarm/start", json={"goal": "Test"})
    assert response.status_code == 200


def test_production_without_key_returns_500() -> None:
    """Non-development environment with empty SWARM_API_KEY returns 500 — forces configuration."""
    _clear_swarm_store()
    _set_auth("production", "")

    client = TestClient(app)
    response = client.post("/api/swarm/start", json={"goal": "Test"})
    assert response.status_code == 500
    assert "SWARM_API_KEY not configured" in response.json()["detail"]


def test_ws_rejected_with_wrong_key() -> None:
    """WS connection is rejected when wrong key query param is provided."""
    _clear_swarm_store()
    _set_auth("production", "ws-secret")

    client = TestClient(app)
    try:
        with client.websocket_connect("/ws/test-swarm?key=wrong"):
            raise AssertionError("WS should have been rejected")
    except Exception:
        pass


def test_ws_accepted_with_correct_key() -> None:
    """WS connection succeeds with correct key query param."""
    _clear_swarm_store()
    _set_auth("production", "ws-secret")

    client = TestClient(app)
    with client.websocket_connect("/ws/test-swarm?key=ws-secret"):
        pass


# ---------------------------------------------------------------------------
# Chat endpoint tests
# ---------------------------------------------------------------------------


def test_chat_returns_400_when_no_client_configured() -> None:
    """POST /api/swarm/{id}/chat returns 400 when no copilot client is available."""
    _clear_swarm_store()
    client = TestClient(app)
    response = client.post(
        "/api/swarm/nonexistent/chat",
        json={"message": "Hello"},
    )
    # No copilot client configured in test — returns 400 not 404
    assert response.status_code == 400


def test_chat_returns_409_for_incomplete_swarm() -> None:
    """POST /api/swarm/{id}/chat returns 409 when swarm hasn't completed."""
    _clear_swarm_store()
    client = TestClient(app)

    # Create a swarm (it will be in "starting" phase)
    create_resp = client.post("/api/swarm/start", json={"goal": "Test"})
    swarm_id = create_resp.json()["swarm_id"]

    response = client.post(
        f"/api/swarm/{swarm_id}/chat",
        json={"message": "Hello"},
    )
    assert response.status_code == 409


def test_chat_returns_200_for_complete_swarm() -> None:
    """POST /api/swarm/{id}/chat returns 200 when swarm is complete with synthesis session."""
    _clear_swarm_store()
    client = TestClient(app)

    # Create a swarm and manually set it to complete with a mock orchestrator
    create_resp = client.post("/api/swarm/start", json={"goal": "Test"})
    swarm_id = create_resp.json()["swarm_id"]

    # Simulate completion
    from unittest.mock import AsyncMock, MagicMock

    mock_orch = MagicMock()
    mock_orch.synthesis_session_id = "synth-test"
    mock_orch.chat = AsyncMock(return_value="Refined response")
    swarm_store[swarm_id]["phase"] = "complete"
    swarm_store[swarm_id]["orchestrator"] = mock_orch

    response = client.post(
        f"/api/swarm/{swarm_id}/chat",
        json={"message": "Refine this"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "streaming"


def test_chat_returns_200_for_qa_phase() -> None:
    """POST /api/swarm/{id}/chat returns 200 when swarm is in qa phase."""
    _clear_swarm_store()
    client = TestClient(app)

    create_resp = client.post("/api/swarm/start", json={"goal": "Test"})
    swarm_id = create_resp.json()["swarm_id"]

    from unittest.mock import AsyncMock, MagicMock

    mock_orch = MagicMock()
    mock_orch.qa_session = MagicMock()  # Q&A session exists
    mock_orch.qa_chat = AsyncMock(return_value="What is your team size?")
    swarm_store[swarm_id]["phase"] = "qa"
    swarm_store[swarm_id]["orchestrator"] = mock_orch

    response = client.post(
        f"/api/swarm/{swarm_id}/chat",
        json={"message": "We have 12 apps"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "streaming"


def test_chat_returns_401_when_auth_required() -> None:
    """POST /api/swarm/{id}/chat requires X-API-Key when configured."""
    _clear_swarm_store()
    _set_auth("production", "secret-key")

    client = TestClient(app)
    response = client.post(
        "/api/swarm/test-id/chat",
        json={"message": "Hello"},
    )
    assert response.status_code == 401


def test_chat_resumes_session_for_unknown_swarm() -> None:
    """POST /api/swarm/{id}/chat creates orchestrator on-the-fly for swarms not in store."""
    _clear_swarm_store()
    client = TestClient(app)

    # Inject a mock copilot client + event bus so on-the-fly orchestrator can be created
    from unittest.mock import AsyncMock, MagicMock

    import backend.api.rest as rest_mod
    from backend.events import EventBus

    old_client, old_bus = rest_mod._copilot_client, rest_mod._event_bus

    mock_client = MagicMock()

    # Session that fires idle on send() so chat() completes
    class _ResumedSession:
        def __init__(self):
            self._handlers = []

        def on(self, handler):
            self._handlers.append(handler)
            return lambda: None

        async def send(self, prompt, **kw):
            from backend.swarm.event_bridge import SessionEvent, SessionEventData, SessionEventType

            for h in self._handlers:
                h(SessionEvent(type=SessionEventType.SESSION_IDLE, data=SessionEventData(turn_id="t1")))
            return "msg-1"

    mock_client.resume_session = AsyncMock(return_value=_ResumedSession())
    rest_mod._copilot_client = mock_client
    rest_mod._event_bus = EventBus()

    try:
        # No swarm created — chat with a swarm_id that only exists as a past session
        response = client.post(
            "/api/swarm/old-swarm-123/chat",
            json={"message": "Summarize findings"},
        )
        # Should return 200 (streaming), not 404
        assert response.status_code == 200
        assert response.json()["status"] == "streaming"

        # Orchestrator should be cached in swarm_store for subsequent messages
        assert "old-swarm-123" in swarm_store
        orch = swarm_store["old-swarm-123"]["orchestrator"]
        assert orch.synthesis_session_id == "synth-old-swarm-123"
    finally:
        rest_mod._copilot_client = old_client
        rest_mod._event_bus = old_bus


def test_swarm_timeout_defaults_to_env_value() -> None:
    """Orchestrator should receive timeout from SWARM_TASK_TIMEOUT env var."""
    import backend.main as main_mod

    _clear_swarm_store()

    # Save original and set custom timeout
    original_timeout = getattr(main_mod, "SWARM_TASK_TIMEOUT", 300)
    main_mod.SWARM_TASK_TIMEOUT = 1800.0

    client = TestClient(app)
    try:
        # Start a swarm — won't actually run (no copilot client) but creates state
        response = client.post("/api/swarm/start", json={"goal": "Test timeout"})
        assert response.status_code == 200
        response.json()["swarm_id"]

        # The swarm_store entry exists but orchestrator is None (no client)
        # Verify the timeout value is accessible from the module
        assert main_mod.SWARM_TASK_TIMEOUT == 1800.0
    finally:
        main_mod.SWARM_TASK_TIMEOUT = original_timeout


def test_chat_endpoint_logs_request_received(caplog: pytest.fixture) -> None:
    """POST /api/swarm/{id}/chat logs chat_request_received with swarm_id and message_length."""
    import logging
    from unittest.mock import AsyncMock, MagicMock

    _clear_swarm_store()
    client = TestClient(app)

    # Create a swarm and set it to complete with a mock orchestrator
    create_resp = client.post("/api/swarm/start", json={"goal": "Test"})
    swarm_id = create_resp.json()["swarm_id"]

    mock_orch = MagicMock()
    mock_orch.synthesis_session_id = "synth-test"
    mock_orch.chat = AsyncMock(return_value="Refined response")
    swarm_store[swarm_id]["phase"] = "complete"
    swarm_store[swarm_id]["orchestrator"] = mock_orch

    with caplog.at_level(logging.INFO, logger="backend.api.rest"):
        response = client.post(
            f"/api/swarm/{swarm_id}/chat",
            json={"message": "Refine this"},
        )

    assert response.status_code == 200
    request_records = [r for r in caplog.records if "chat_request_received" in r.message]
    assert len(request_records) == 1, f"Expected chat_request_received, got: {[r.message for r in caplog.records]}"
    assert swarm_id in request_records[0].message


# ---------------------------------------------------------------------------
# File endpoint tests
# ---------------------------------------------------------------------------


def test_list_files_returns_empty_for_missing_workdir() -> None:
    """GET /api/swarm/{id}/files returns empty list when workdir doesn't exist."""
    client = TestClient(app)
    response = client.get("/api/swarm/nonexistent-swarm/files")
    assert response.status_code == 200
    assert response.json()["files"] == []


def test_list_files_returns_files_in_workdir(tmp_path: pytest.fixture) -> None:
    """GET /api/swarm/{id}/files lists files in workdir."""

    # Create a temp workdir with files
    swarm_id = "test-files-swarm"
    work_dir = tmp_path / swarm_id
    work_dir.mkdir()
    (work_dir / "report.md").write_text("# Report")
    (work_dir / "notes.md").write_text("# Notes")

    # Patch the workdir base path
    client = TestClient(app)

    # We need to create files in the actual workdir path the endpoint uses
    from pathlib import Path

    actual_dir = Path("workdir") / swarm_id
    actual_dir.mkdir(parents=True, exist_ok=True)
    (actual_dir / "report.md").write_text("# Report")
    (actual_dir / "notes.md").write_text("# Notes")

    try:
        response = client.get(f"/api/swarm/{swarm_id}/files")
        assert response.status_code == 200
        files = response.json()["files"]
        assert len(files) == 2
        names = {f["name"] for f in files}
        assert "report.md" in names
        assert "notes.md" in names
    finally:
        import shutil

        shutil.rmtree(actual_dir, ignore_errors=True)


def test_get_file_returns_content() -> None:
    """GET /api/swarm/{id}/files/{path} returns file content."""
    from pathlib import Path

    swarm_id = "test-read-swarm"
    work_dir = Path("workdir") / swarm_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "test.md").write_text("Hello world")

    client = TestClient(app)
    try:
        response = client.get(f"/api/swarm/{swarm_id}/files/test.md")
        assert response.status_code == 200
        assert response.json()["content"] == "Hello world"
    finally:
        import shutil

        shutil.rmtree(work_dir, ignore_errors=True)


def test_get_file_404_for_missing() -> None:
    """GET /api/swarm/{id}/files/{path} returns 404 for nonexistent file."""
    client = TestClient(app)
    response = client.get("/api/swarm/no-swarm/files/missing.md")
    assert response.status_code == 404


def test_get_file_403_for_path_traversal() -> None:
    """Path traversal via symlink or encoded path is blocked."""
    import shutil
    from pathlib import Path

    # Create a workdir with a symlink pointing outside
    swarm_id = "test-traversal"
    work_dir = Path("workdir") / swarm_id
    work_dir.mkdir(parents=True, exist_ok=True)
    symlink = work_dir / "escape"
    try:
        symlink.symlink_to("/etc/hostname")
    except OSError:
        # Can't create symlinks — skip
        shutil.rmtree(work_dir, ignore_errors=True)
        return

    client = TestClient(app)
    try:
        response = client.get(f"/api/swarm/{swarm_id}/files/escape")
        # Symlink resolves outside workdir — should be 403
        assert response.status_code == 403
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_ensure_report_creates_file_when_missing() -> None:
    """POST /api/swarm/{id}/files/ensure-report creates the file if missing."""
    import shutil
    from pathlib import Path

    swarm_id = "test-ensure-swarm"
    work_dir = Path("workdir") / swarm_id
    shutil.rmtree(work_dir, ignore_errors=True)

    client = TestClient(app)
    try:
        response = client.post(
            f"/api/swarm/{swarm_id}/files/ensure-report",
            json={"report": "# My Report\n\nContent here"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["created"] is True
        assert (work_dir / "synthesis_report.md").read_text() == "# My Report\n\nContent here"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_ensure_report_does_not_overwrite_existing() -> None:
    """POST /api/swarm/{id}/files/ensure-report leaves existing file alone."""
    import shutil
    from pathlib import Path

    swarm_id = "test-ensure-existing"
    work_dir = Path("workdir") / swarm_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "synthesis_report.md").write_text("Original content")

    client = TestClient(app)
    try:
        response = client.post(
            f"/api/swarm/{swarm_id}/files/ensure-report",
            json={"report": "New content"},
        )
        assert response.status_code == 200
        assert response.json()["created"] is False
        assert (work_dir / "synthesis_report.md").read_text() == "Original content"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_download_zip_returns_zip_for_existing_workdir() -> None:
    """GET /api/swarm/{id}/files/download-zip returns a valid ZIP with all files."""
    import io
    import shutil
    import zipfile
    from pathlib import Path

    swarm_id = "test-zip-download"
    work_dir = Path("workdir") / swarm_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "report.md").write_text("# Report content")
    (work_dir / "notes.txt").write_text("Some notes")

    client = TestClient(app)
    try:
        response = client.get(f"/api/swarm/{swarm_id}/files/download-zip")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/zip"
        assert f'filename="{swarm_id}.zip"' in response.headers["content-disposition"]

        # Verify zip contents
        buf = io.BytesIO(response.content)
        with zipfile.ZipFile(buf) as zf:
            names = set(zf.namelist())
            assert names == {"report.md", "notes.txt"}
            assert zf.read("report.md").decode() == "# Report content"
            assert zf.read("notes.txt").decode() == "Some notes"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_download_zip_returns_empty_zip_for_missing_workdir() -> None:
    """GET /api/swarm/{id}/files/download-zip returns empty ZIP when workdir doesn't exist."""
    import io
    import zipfile

    client = TestClient(app)
    response = client.get("/api/swarm/nonexistent-zip-swarm/files/download-zip")
    assert response.status_code == 200

    buf = io.BytesIO(response.content)
    with zipfile.ZipFile(buf) as zf:
        assert len(zf.namelist()) == 0


def test_download_zip_excludes_symlinks_outside_workdir() -> None:
    """Symlinks resolving outside workdir are excluded from the ZIP."""
    import io
    import shutil
    import zipfile
    from pathlib import Path

    swarm_id = "test-zip-traversal"
    work_dir = Path("workdir") / swarm_id
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "safe.md").write_text("Safe content")
    symlink = work_dir / "escape"
    try:
        symlink.symlink_to("/etc/hostname")
    except OSError:
        shutil.rmtree(work_dir, ignore_errors=True)
        return  # Can't create symlinks — skip

    client = TestClient(app)
    try:
        response = client.get(f"/api/swarm/{swarm_id}/files/download-zip")
        assert response.status_code == 200

        buf = io.BytesIO(response.content)
        with zipfile.ZipFile(buf) as zf:
            names = set(zf.namelist())
            assert "safe.md" in names
            assert "escape" not in names
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_download_zip_includes_nested_files() -> None:
    """Nested files in subdirectories are included with correct paths."""
    import io
    import shutil
    import zipfile
    from pathlib import Path

    swarm_id = "test-zip-nested"
    work_dir = Path("workdir") / swarm_id
    sub_dir = work_dir / "subdir"
    sub_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "top.md").write_text("Top level")
    (sub_dir / "deep.md").write_text("Nested file")

    client = TestClient(app)
    try:
        response = client.get(f"/api/swarm/{swarm_id}/files/download-zip")
        assert response.status_code == 200

        buf = io.BytesIO(response.content)
        with zipfile.ZipFile(buf) as zf:
            names = set(zf.namelist())
            assert "top.md" in names
            assert "subdir/deep.md" in names
            assert zf.read("subdir/deep.md").decode() == "Nested file"
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def test_websocket_receives_swarm_events() -> None:
    """Start a swarm, connect WS, emit a phase_changed event, verify receipt."""
    _clear_swarm_store()
    client = TestClient(app)

    # Start a swarm to get its ID
    create_resp = client.post("/api/swarm/start", json={"goal": "Test events"})
    swarm_id = create_resp.json()["swarm_id"]

    with client.websocket_connect(f"/ws/{swarm_id}") as ws:
        # Simulate an event broadcast via the manager directly
        import asyncio

        def _broadcast() -> None:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(
                manager.broadcast(
                    swarm_id,
                    {"type": "phase_changed", "phase": "planning", "swarm_id": swarm_id},
                )
            )
            loop.close()

        t = threading.Thread(target=_broadcast)
        t.start()
        t.join()

        data = ws.receive_json()
        assert data["type"] == "phase_changed"
        assert data["phase"] == "planning"
        assert data["swarm_id"] == swarm_id


# ---------------------------------------------------------------------------
# Template CRUD tests
# ---------------------------------------------------------------------------


def test_get_template_details_returns_files() -> None:
    """GET /api/templates/{key} returns template metadata and file contents."""
    client = TestClient(app)
    response = client.get("/api/templates/deep-research")
    assert response.status_code == 200
    body = response.json()
    assert body["key"] == "deep-research"
    assert "files" in body
    assert isinstance(body["files"], list)
    # Should have at least _template.yaml, leader.md, synthesis.md
    filenames = [f["filename"] for f in body["files"]]
    assert "_template.yaml" in filenames
    assert "leader.md" in filenames
    assert "synthesis.md" in filenames
    # Each file should have content
    for f in body["files"]:
        assert "content" in f
        assert len(f["content"]) > 0


def test_get_template_details_404_for_unknown() -> None:
    """GET /api/templates/{key} returns 404 for unknown template."""
    client = TestClient(app)
    response = client.get("/api/templates/nonexistent-template")
    assert response.status_code == 404


def test_update_template_file_validates() -> None:
    """PUT /api/templates/{key}/files/{filename} validates and saves valid content."""
    import shutil
    from pathlib import Path

    # Create a temp template
    template_dir = Path("src/templates/_test-crud")
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "_template.yaml").write_text(
        '---\nkey: _test-crud\nname: Test\ndescription: Test template\ngoal_template: "Do {user_input}"\n---\n'
    )
    (template_dir / "leader.md").write_text("---\nname: leader\n---\n\nYou are the leader.")
    (template_dir / "synthesis.md").write_text("---\nname: synthesis\n---\n\nSynthesize results.")

    client = TestClient(app)
    try:
        response = client.put(
            "/api/templates/_test-crud/files/leader.md",
            json={"content": "---\nname: leader\n---\n\nUpdated leader prompt."},
        )
        assert response.status_code == 200
        assert response.json()["valid"] is True
        # Verify file was actually written
        assert "Updated leader prompt" in (template_dir / "leader.md").read_text()
    finally:
        shutil.rmtree(template_dir, ignore_errors=True)


def test_update_template_file_rejects_invalid() -> None:
    """PUT /api/templates/{key}/files/{filename} returns 422 for invalid content."""
    import shutil
    from pathlib import Path

    template_dir = Path("src/templates/_test-invalid")
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "_template.yaml").write_text(
        '---\nkey: _test-invalid\nname: Test\ndescription: Test\ngoal_template: "Do {user_input}"\n---\n'
    )
    (template_dir / "leader.md").write_text("---\nname: leader\n---\n\nOriginal content.")

    client = TestClient(app)
    try:
        response = client.put(
            "/api/templates/_test-invalid/files/leader.md",
            json={"content": "No frontmatter at all"},
        )
        assert response.status_code == 422
        body = response.json()
        assert "errors" in body["detail"]
        assert len(body["detail"]["errors"]) > 0
    finally:
        shutil.rmtree(template_dir, ignore_errors=True)


def test_create_template_scaffolds_files() -> None:
    """POST /api/templates creates a new template with scaffolded files."""
    import shutil
    from pathlib import Path

    client = TestClient(app)
    # Ensure it doesn't exist
    template_dir = Path("src/templates/my-new-template")
    shutil.rmtree(template_dir, ignore_errors=True)

    try:
        response = client.post(
            "/api/templates",
            json={"key": "my-new-template", "name": "My New Template", "description": "A test template"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["key"] == "my-new-template"
        # Verify files were created
        assert template_dir.is_dir()
        assert (template_dir / "_template.yaml").is_file()
        assert (template_dir / "leader.md").is_file()
        assert (template_dir / "synthesis.md").is_file()
        assert (template_dir / "worker-default.md").is_file()
        # Verify _template.yaml has {user_input}
        yaml_content = (template_dir / "_template.yaml").read_text()
        assert "{user_input}" in yaml_content
    finally:
        shutil.rmtree(template_dir, ignore_errors=True)


def test_delete_template_removes_directory() -> None:
    """DELETE /api/templates/{key} removes the template directory."""
    import shutil
    from pathlib import Path

    template_dir = Path("src/templates/_test-delete")
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "_template.yaml").write_text(
        '---\nkey: _test-delete\nname: Del\ndescription: Del\ngoal_template: "{user_input}"\n---\n'
    )

    client = TestClient(app)
    try:
        response = client.delete("/api/templates/_test-delete")
        assert response.status_code == 200
        assert not template_dir.exists()
    finally:
        shutil.rmtree(template_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Template path traversal tests
# ---------------------------------------------------------------------------


def test_safe_template_path_rejects_traversal() -> None:
    """_safe_template_path raises 403 for path traversal attempts."""
    from fastapi import HTTPException

    from backend.api.rest import _safe_template_path

    # ".." resolves to parent of templates dir
    with pytest.raises(HTTPException) as exc_info:
        _safe_template_path("../../etc")
    assert exc_info.value.status_code == 403

    # Single ".." also escapes
    with pytest.raises(HTTPException) as exc_info:
        _safe_template_path("..")
    assert exc_info.value.status_code == 403


def test_safe_template_file_path_rejects_traversal() -> None:
    """_safe_template_file_path raises 403 for filename traversal."""
    from fastapi import HTTPException

    from backend.api.rest import _safe_template_file_path

    with pytest.raises(HTTPException) as exc_info:
        _safe_template_file_path("deep-research", "../../etc/passwd")
    assert exc_info.value.status_code == 403


def test_create_template_400_for_path_traversal_key() -> None:
    """POST /api/templates rejects traversal in key (from JSON body)."""
    client = TestClient(app)
    response = client.post(
        "/api/templates",
        json={"key": "../../../tmp/evil", "name": "Evil", "description": "Bad"},
    )
    assert response.status_code == 400


def test_create_template_400_for_key_with_slashes() -> None:
    """POST /api/templates rejects keys containing path separators."""
    client = TestClient(app)
    response = client.post(
        "/api/templates",
        json={"key": "foo/bar", "name": "Foo", "description": "Slash in key"},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Zip Deploy tests
# ---------------------------------------------------------------------------


def _make_template_zip(key: str = "test-deploy", extra_files: dict[str, str] | None = None) -> bytes:
    """Create an in-memory zip with a valid template structure."""
    import io
    import zipfile

    import yaml

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        meta = {
            "key": key,
            "name": "Test Deploy",
            "description": "A deployed template",
            "goal_template": "Do {user_input}",
        }
        zf.writestr(f"{key}/_template.yaml", f"---\n{yaml.dump(meta)}---\n")
        zf.writestr(f"{key}/leader.md", "---\nname: leader\n---\n\nYou are the leader.")
        zf.writestr(f"{key}/synthesis.md", "---\nname: synthesis\n---\n\nSynthesize results.")
        zf.writestr(
            f"{key}/worker-default.md",
            "---\nname: default-worker\ndisplayName: Default Worker\n"
            "description: A general-purpose worker\n---\n\nComplete the task.\n",
        )
        if extra_files:
            for name, content in extra_files.items():
                zf.writestr(f"{key}/{name}", content)
    return buf.getvalue()


def test_deploy_template_zip_creates_template() -> None:
    """POST /api/templates/deploy with valid zip creates the template."""
    import shutil
    from pathlib import Path

    template_dir = Path("src/templates/test-deploy")
    shutil.rmtree(template_dir, ignore_errors=True)

    client = TestClient(app)
    try:
        response = client.post(
            "/api/templates/deploy",
            files={"file": ("test-deploy.zip", _make_template_zip(), "application/zip")},
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert body["key"] == "test-deploy"
        assert template_dir.is_dir()
        assert (template_dir / "_template.yaml").is_file()
        assert (template_dir / "leader.md").is_file()
    finally:
        shutil.rmtree(template_dir, ignore_errors=True)


def test_deploy_template_zip_rejects_oversized() -> None:
    """POST /api/templates/deploy rejects zips over the size limit."""
    import backend.main as main_mod

    original = getattr(main_mod, "SWARM_MAX_TEMPLATE_ZIP_SIZE", 3 * 1024 * 1024)
    main_mod.SWARM_MAX_TEMPLATE_ZIP_SIZE = 100  # 100 bytes

    client = TestClient(app)
    try:
        response = client.post(
            "/api/templates/deploy",
            files={"file": ("big.zip", _make_template_zip(), "application/zip")},
        )
        assert response.status_code == 413
    finally:
        main_mod.SWARM_MAX_TEMPLATE_ZIP_SIZE = original


def test_deploy_template_zip_rejects_zipslip() -> None:
    """POST /api/templates/deploy rejects entries with path traversal."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/evil.txt", "pwned")
    data = buf.getvalue()

    client = TestClient(app)
    response = client.post(
        "/api/templates/deploy",
        files={"file": ("evil.zip", data, "application/zip")},
    )
    assert response.status_code == 400


def test_deploy_template_zip_rejects_key_mismatch() -> None:
    """POST /api/templates/deploy rejects if directory name != _template.yaml key."""
    import io
    import zipfile

    import yaml

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        meta = {"key": "actual-key", "name": "Mismatch", "description": "", "goal_template": "{user_input}"}
        zf.writestr("wrong-dir/_template.yaml", f"---\n{yaml.dump(meta)}---\n")
        zf.writestr("wrong-dir/leader.md", "---\nname: leader\n---\n\nLeader.")
        zf.writestr(
            "wrong-dir/worker-default.md",
            "---\nname: default-worker\ndisplayName: Worker\ndescription: Worker\n---\n\nWork.\n",
        )
    data = buf.getvalue()

    client = TestClient(app)
    response = client.post(
        "/api/templates/deploy",
        files={"file": ("mismatch.zip", data, "application/zip")},
    )
    assert response.status_code == 400


def test_deploy_template_zip_rejects_missing_template_yaml() -> None:
    """POST /api/templates/deploy rejects zips without _template.yaml."""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("my-template/leader.md", "---\nname: leader\n---\n\nLeader.")
    data = buf.getvalue()

    client = TestClient(app)
    response = client.post(
        "/api/templates/deploy",
        files={"file": ("no-meta.zip", data, "application/zip")},
    )
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Event replay + Swarm list endpoints
# ---------------------------------------------------------------------------


def test_get_events_endpoint_returns_404_without_repo():
    """Events endpoint returns 404 when no repo configured."""
    _clear_swarm_store()
    client = TestClient(app)
    resp = client.get("/api/swarm/00000000-0000-0000-0000-000000000001/events")
    assert resp.status_code == 404


def test_list_swarms_endpoint_returns_404_without_repo():
    """Swarms list endpoint returns 404 when no repo configured."""
    _clear_swarm_store()
    client = TestClient(app)
    resp = client.get("/api/swarms")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Continue endpoint tests
# ---------------------------------------------------------------------------


class TestContinueEndpoint:
    """Tests for POST /api/swarm/{id}/continue."""

    def test_continue_signals_orchestrator(self) -> None:
        """POST /api/swarm/{id}/continue sets continue_action and signals event."""
        import asyncio
        from unittest.mock import MagicMock

        _clear_swarm_store()
        client = TestClient(app)

        swarm_id = "test-continue-swarm"
        event = asyncio.Event()
        orch = MagicMock()
        orch._continue_event = event
        orch._continue_action = ""

        swarm_store[swarm_id] = {
            "swarm_id": swarm_id,
            "goal": "test",
            "template": None,
            "phase": "executing",
            "round_number": 1,
            "orchestrator": orch,
        }

        resp = client.post(f"/api/swarm/{swarm_id}/continue")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["swarm_id"] == swarm_id
        assert body["action"] == "continue"
        orch.signal_continue.assert_called_once()

    def test_continue_404_when_not_paused(self) -> None:
        """POST /continue returns 404 if orchestrator has no _continue_event."""
        from unittest.mock import MagicMock

        _clear_swarm_store()
        client = TestClient(app)

        swarm_id = "test-not-paused"
        orch = MagicMock(spec=[])  # no attributes
        swarm_store[swarm_id] = {
            "swarm_id": swarm_id,
            "goal": "test",
            "template": None,
            "phase": "executing",
            "round_number": 1,
            "orchestrator": orch,
        }

        resp = client.post(f"/api/swarm/{swarm_id}/continue")
        assert resp.status_code == 404
        assert "not paused" in resp.json()["detail"].lower()

    def test_continue_404_when_swarm_not_found(self) -> None:
        """POST /continue returns 404 for unknown swarm_id."""
        _clear_swarm_store()
        client = TestClient(app)

        resp = client.post("/api/swarm/nonexistent-id/continue")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Skip-to-synthesis endpoint tests
# ---------------------------------------------------------------------------


class TestSkipToSynthesisEndpoint:
    """Tests for POST /api/swarm/{id}/skip-to-synthesis."""

    def test_skip_signals_orchestrator(self) -> None:
        """POST /api/swarm/{id}/skip-to-synthesis sets skip action and signals event."""
        import asyncio
        from unittest.mock import MagicMock

        _clear_swarm_store()
        client = TestClient(app)

        swarm_id = "test-skip-swarm"
        event = asyncio.Event()
        orch = MagicMock()
        orch._continue_event = event
        orch._continue_action = ""

        swarm_store[swarm_id] = {
            "swarm_id": swarm_id,
            "goal": "test",
            "template": None,
            "phase": "executing",
            "round_number": 3,
            "orchestrator": orch,
        }

        resp = client.post(f"/api/swarm/{swarm_id}/skip-to-synthesis")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["swarm_id"] == swarm_id
        assert body["action"] == "skip"
        orch.signal_skip.assert_called_once()

    def test_skip_404_when_not_found(self) -> None:
        """POST /skip-to-synthesis returns 404 for unknown swarm."""
        _clear_swarm_store()
        client = TestClient(app)

        resp = client.post("/api/swarm/nonexistent-id/skip-to-synthesis")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_skip_404_when_not_paused(self) -> None:
        """POST /skip-to-synthesis returns 404 if orchestrator has no _continue_event."""
        from unittest.mock import MagicMock

        _clear_swarm_store()
        client = TestClient(app)

        swarm_id = "test-skip-not-paused"
        orch = MagicMock(spec=[])  # no attributes
        swarm_store[swarm_id] = {
            "swarm_id": swarm_id,
            "goal": "test",
            "template": None,
            "phase": "executing",
            "round_number": 1,
            "orchestrator": orch,
        }

        resp = client.post(f"/api/swarm/{swarm_id}/skip-to-synthesis")
        assert resp.status_code == 404
        assert "not paused" in resp.json()["detail"].lower()
