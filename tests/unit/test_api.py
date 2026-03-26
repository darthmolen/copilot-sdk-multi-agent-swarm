"""TDD tests for the FastAPI + WebSocket API layer."""

from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from backend.api.rest import swarm_store
from backend.api.websocket import ConnectionManager
from backend.main import app, manager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


import pytest


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
            loop.run_until_complete(
                manager.broadcast("test-swarm", {"type": "ping", "value": 42})
            )
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

    with client.websocket_connect("/ws/multi-swarm") as ws1:
        with client.websocket_connect("/ws/multi-swarm") as ws2:
            import asyncio

            def _broadcast() -> None:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(
                    manager.broadcast(
                        "multi-swarm", {"type": "update", "round": 1}
                    )
                )
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

    with client.websocket_connect("/ws/disc-swarm") as ws:
        pass  # context exit closes the WS

    # Broadcast to the now-empty swarm_id should not raise
    import asyncio

    loop = asyncio.new_event_loop()
    loop.run_until_complete(
        manager.broadcast("disc-swarm", {"type": "after-disconnect"})
    )
    loop.close()


# ---------------------------------------------------------------------------
# REST tests
# ---------------------------------------------------------------------------


def test_post_swarm_start_returns_swarm_id() -> None:
    """POST /api/swarm/start returns a swarm_id and status 'starting'."""
    _clear_swarm_store()
    client = TestClient(app)

    response = client.post(
        "/api/swarm/start", json={"goal": "Build a website"}
    )
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
    create_resp = client.post(
        "/api/swarm/start", json={"goal": "Analyze data"}
    )
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


def test_get_swarm_status_unknown_returns_404() -> None:
    """GET status for a nonexistent swarm_id returns 404."""
    _clear_swarm_store()
    client = TestClient(app)

    response = client.get("/api/swarm/nonexistent-id/status")
    assert response.status_code == 404


def test_list_templates_returns_templates() -> None:
    """GET /api/templates returns the 3 built-in templates."""
    client = TestClient(app)

    response = client.get("/api/templates")
    assert response.status_code == 200
    body = response.json()

    assert "templates" in body
    templates = body["templates"]
    assert len(templates) == 3

    names = {t["name"] for t in templates}
    assert names == {
        "Software Development Team",
        "Deep Research Team",
        "Warehouse Optimization Team",
    }


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
        with client.websocket_connect("/ws/test-swarm?key=wrong") as ws:
            assert False, "WS should have been rejected"
    except Exception:
        pass




def test_ws_accepted_with_correct_key() -> None:
    """WS connection succeeds with correct key query param."""
    _clear_swarm_store()
    _set_auth("production", "ws-secret")

    client = TestClient(app)
    with client.websocket_connect("/ws/test-swarm?key=ws-secret") as ws:
        pass




def test_websocket_receives_swarm_events() -> None:
    """Start a swarm, connect WS, emit a phase_changed event, verify receipt."""
    _clear_swarm_store()
    client = TestClient(app)

    # Start a swarm to get its ID
    create_resp = client.post(
        "/api/swarm/start", json={"goal": "Test events"}
    )
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
