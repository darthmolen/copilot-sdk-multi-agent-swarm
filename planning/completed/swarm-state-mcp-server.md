# COMPLETED: Swarm State MCP Server (In-Process, Streamable HTTP)

**Branch**: `feature/swarm-state-mcp-server`
**Depends on**: Persistence layer (PR #8, `feature/swarm-state-persistence`)

## What was built

In-process FastMCP server mounted on the FastAPI app at `/mcp`. Agent sessions connect via URL (streamable HTTP transport) — the SDK handles auth at the transport layer so credentials never enter agent context.

### 9 Tools

| Tool | Description |
|------|-------------|
| `get_active_swarms` | Discovery — list all swarms with phase/goal/template |
| `get_swarm_status` | Status summary (phase, round, agent/task counts) |
| `list_tasks` | All tasks with optional status/worker filters |
| `get_task_detail` | Full task with result |
| `get_recent_events` | Event history (requires DB) |
| `list_agents` | Agent roster with status |
| `list_artifacts` | Files in work directory |
| `read_artifact` | Read a specific file |
| `restart_agent` | Restart a stuck/failed agent |

### Key design decisions

- **`swarm_id` is required** on all tools except `get_active_swarms`. Optional swarm_id with auto-inference was a cross-contamination risk in multi-swarm scenarios.
- **ToolError for errors** — raises `ToolError` which FastMCP converts to `CallToolResult(isError=true)`. Not `return {"error": "..."}` which the client sees as a successful call.
- **Type-safe end-to-end** — `SwarmState` TypedDict flows from store through `_resolve_swarm()` to typed key access in every tool. No `dict(state)` erasure.
- **Auth via headers** — API key passed in `MCPRemoteServerConfig.headers`, invisible to agent context. OAuth upgrade path exists via SDK's `oauthClientId` support.
- **Auto-injection** — all agent sessions automatically get the swarm-state MCP server config via `_get_mcp_servers()` on the orchestrator.

### Files

- `src/backend/mcp/__init__.py`, `deps.py`, `server.py` — MCP server + dependency holder
- `src/backend/main.py` — ASGI mount, session manager lifecycle, auth middleware
- `src/backend/swarm/orchestrator.py` — `restart_agent()`, `_get_mcp_servers()`, auto-injection
- `tests/unit/test_mcp_server.py` — 20 unit tests
- `tests/integration/test_mcp_mount.py` — 5 integration tests (ASGI mount + auth)

## Open questions answered

- **MCP server lifecycle**: Mounted on FastAPI app, starts/stops with lifespan. One server, `swarm_id` required per call.
- **Auth**: API key in headers (transport layer). Agent never sees credentials.
- **Transport**: Streamable HTTP (not stdio). In-process, same event loop, direct access to live state.
