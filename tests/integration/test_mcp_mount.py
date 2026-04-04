"""Integration tests for the MCP server ASGI mount on the FastAPI app.

These tests validate the ASGI mount, auth middleware, and MCP protocol
by testing the Starlette MCP sub-app directly with the session manager
lifecycle properly managed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from backend.api.rest import swarm_store
from backend.mcp.deps import MCPDeps
from backend.swarm.task_board import TaskBoard
from backend.swarm.team_registry import TeamRegistry


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset global state before/after each test."""
    import backend.main as main_mod
    import backend.mcp.deps as mcp_deps

    main_mod.ENVIRONMENT = "development"
    main_mod.SWARM_API_KEY = ""
    swarm_store.clear()

    deps = MCPDeps(swarm_store=swarm_store, work_dir="/tmp/test-workdir")
    mcp_deps._deps = deps

    yield

    swarm_store.clear()
    main_mod.ENVIRONMENT = "development"
    main_mod.SWARM_API_KEY = ""
    mcp_deps._deps = None


@pytest.fixture
def _with_swarm():
    """Add a test swarm to the store."""
    orch = MagicMock()
    orch.service = MagicMock()
    orch.service.task_board = TaskBoard()
    orch.service.registry = TeamRegistry()
    orch.agents = {}
    swarm_store["test-swarm"] = {
        "swarm_id": "test-swarm",
        "goal": "Test goal",
        "template": None,
        "phase": "executing",
        "round_number": 1,
        "orchestrator": orch,
    }


def _make_mcp_app():
    """Create a fresh MCP Starlette app with its own session manager."""
    from backend.mcp import server as mcp_mod

    fresh_mcp = FastMCP(
        "swarm-state-test",
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        streamable_http_path="/",
    )
    # Re-register all tools from the real server
    for name, tool in mcp_mod.mcp._tool_manager._tools.items():
        fresh_mcp._tool_manager._tools[name] = tool

    starlette_app = fresh_mcp.streamable_http_app()
    return starlette_app, fresh_mcp._session_manager


MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}


async def _mcp_init_body():
    return {
        "jsonrpc": "2.0",
        "method": "initialize",
        "id": 1,
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }


class TestMCPServer:
    """Test the MCP server directly (bypassing FastAPI mount).

    This validates the MCP protocol, tool listing, and tool execution.
    """

    async def test_initialize_returns_200(self):
        starlette_app, session_mgr = _make_mcp_app()

        async def _run(*, task_status=anyio.TASK_STATUS_IGNORED):
            async with session_mgr.run():
                task_status.started()
                await anyio.sleep_forever()

        async with anyio.create_task_group() as tg:
            await tg.start(_run)
            async with AsyncClient(
                transport=ASGITransport(app=starlette_app),
                base_url="http://localhost",
            ) as client:
                resp = await client.post("/", json=await _mcp_init_body(), headers=MCP_HEADERS)
                assert resp.status_code == 200
                # Response is SSE; parse the JSON-RPC result from event stream
                assert "swarm-state-test" in resp.text
            tg.cancel_scope.cancel()

    async def test_tools_list_returns_9_tools(self, _with_swarm):
        starlette_app, session_mgr = _make_mcp_app()

        async def _run(*, task_status=anyio.TASK_STATUS_IGNORED):
            async with session_mgr.run():
                task_status.started()
                await anyio.sleep_forever()

        async with anyio.create_task_group() as tg:
            await tg.start(_run)
            async with AsyncClient(
                transport=ASGITransport(app=starlette_app),
                base_url="http://localhost",
            ) as client:
                # Initialize
                init_resp = await client.post("/", json=await _mcp_init_body(), headers=MCP_HEADERS)
                session_id = init_resp.headers.get("mcp-session-id", "")

                sess_headers = {**MCP_HEADERS, "mcp-session-id": session_id}

                # Send initialized notification
                await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                    headers=sess_headers,
                )

                # List tools
                tools_resp = await client.post(
                    "/",
                    json={"jsonrpc": "2.0", "method": "tools/list", "id": 2, "params": {}},
                    headers=sess_headers,
                )
                assert tools_resp.status_code == 200
                # Parse tool names from SSE response body
                body = tools_resp.text
                expected_tools = [
                    "get_active_swarms",
                    "get_swarm_status",
                    "list_tasks",
                    "get_task_detail",
                    "get_recent_events",
                    "list_agents",
                    "list_artifacts",
                    "read_artifact",
                    "resume_agent",
                ]
                for tool_name in expected_tools:
                    assert tool_name in body, f"Tool '{tool_name}' not found in response"
            tg.cancel_scope.cancel()


class TestMCPAuth:
    """Test the auth middleware in isolation."""

    async def test_rejects_without_key(self):
        """When SWARM_API_KEY is set, /mcp should require X-API-Key."""
        import backend.main as main_mod

        main_mod.ENVIRONMENT = "production"
        main_mod.SWARM_API_KEY = "test-secret-key"

        from backend.main import app

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as client:
            resp = await client.post(
                "/mcp/",
                json=await _mcp_init_body(),
                headers=MCP_HEADERS,
            )
            assert resp.status_code == 401

    async def test_accepts_with_valid_key(self):
        """When SWARM_API_KEY is set, valid X-API-Key passes through to MCP.

        Without the lifespan running in tests, MCP's session manager isn't
        initialized — but getting past 401 proves auth middleware worked.
        """
        import backend.main as main_mod

        main_mod.ENVIRONMENT = "production"
        main_mod.SWARM_API_KEY = "test-secret-key"

        from backend.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://localhost",
        ) as client:
            resp = await client.post(
                "/mcp/",
                json=await _mcp_init_body(),
                headers={**MCP_HEADERS, "X-API-Key": "test-secret-key"},
            )
            # Should NOT be 401 — auth passed.
            assert resp.status_code != 401

    async def test_dev_mode_skips_auth(self):
        """In development with no key, /mcp should pass through without auth."""
        import backend.main as main_mod

        main_mod.ENVIRONMENT = "development"
        main_mod.SWARM_API_KEY = ""

        from backend.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://localhost",
        ) as client:
            resp = await client.post(
                "/mcp/",
                json=await _mcp_init_body(),
                headers=MCP_HEADERS,
            )
            # Should NOT be 401 — dev mode skips auth
            assert resp.status_code != 401
