# COMPLETED: Swarm State MCP Server (In-Process, Streamable HTTP)

**Branch**: `feature/swarm-state-mcp-server`
**Depends on**: Persistence layer (PR #8, `feature/swarm-state-persistence`)

## What was built

In-process FastMCP server mounted on the FastAPI app at `/mcp` (streamable HTTP, `streamable_http_path="/"`). Agent sessions connect via URL — the SDK handles auth at the transport layer so credentials never enter agent context.

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
| ~~`restart_agent`~~ | *(removed — replaced by `resume_agent`)* |

### Key design decisions

- **`swarm_id` is required** on all tools except `get_active_swarms`. Optional swarm_id with auto-inference was a cross-contamination risk in multi-swarm scenarios.
- **ToolError for errors** — raises `ToolError` which FastMCP converts to `CallToolResult(isError=true)`. Not `return {"error": "..."}` which the client sees as a successful call.
- **Type-safe end-to-end** — `SwarmState` TypedDict flows from store through `_resolve_swarm()` to typed key access in every tool. No `dict(state)` erasure.
- **Auth via headers** — API key passed in `MCPRemoteServerConfig.headers`, invisible to agent context. OAuth upgrade path exists via SDK's `oauthClientId` support.
- **Auto-injection** — all agent sessions automatically get the swarm-state MCP server config via `_get_mcp_servers()` on the orchestrator.

### Files

- `src/backend/mcp/__init__.py`, `deps.py`, `server.py` — MCP server + dependency holder
- `src/backend/main.py` — ASGI mount, session manager lifecycle, auth middleware
- `src/backend/swarm/orchestrator.py` — `_get_mcp_servers()`, auto-injection (note: `restart_agent()` removed)
- `tests/unit/test_mcp_server.py` — 20 unit tests
- `tests/integration/test_mcp_mount.py` — 5 integration tests (ASGI mount + auth)

## Open questions answered

- **MCP server lifecycle**: Mounted on FastAPI app, starts/stops with lifespan. One server, `swarm_id` required per call.
- **Auth**: API key in headers (transport layer). Agent never sees credentials.
- **Transport**: Streamable HTTP (not stdio). In-process, same event loop, direct access to live state.

## Code Review

### 🔴 Critical: MCP auth middleware allows access when `SWARM_API_KEY` is empty

**File:** `src/backend/main.py` — `_MCPAuthMiddleware`

The middleware compares `key != SWARM_API_KEY` without first checking if `SWARM_API_KEY` itself is empty. In a misconfigured production environment (`ENVIRONMENT != "development"` but `SWARM_API_KEY=""`), a request with no key passes the check because `"" == ""`. The REST API's `verify_api_key()` correctly handles this case by returning HTTP 500 when the key is unconfigured.

**Fix:** Add the same empty-key guard used in `verify_api_key()` before the comparison:
```python
if not SWARM_API_KEY:
    return PlainTextResponse("SWARM_API_KEY not configured", status_code=500)
if key != SWARM_API_KEY:
    return PlainTextResponse("Unauthorized", status_code=401)
```

---

### 🟡 Medium: `read_artifact()` crashes on binary files with `UnicodeDecodeError`

**File:** `src/backend/mcp/server.py` — `read_artifact()`

`Path.read_text()` assumes UTF-8. If an agent writes binary files (images, compiled artifacts, etc.), this tool raises an unhandled `UnicodeDecodeError` rather than a clean `ToolError`.

**Fix:** Wrap the read in a try/except:
```python
try:
    return target.read_text()
except UnicodeDecodeError:
    raise ToolError(f"File '{filename}' is not a text file and cannot be read as text")
```

---

### 🟡 Medium: `get_active_swarms()` is unsafe under concurrent swarm creation

**File:** `src/backend/mcp/server.py` — `get_active_swarms()`

Iterating over `deps.swarm_store.values()` is not safe if the REST API adds or removes a swarm concurrently — Python raises `RuntimeError: dictionary changed size during iteration`.

**Fix:** Snapshot the values before iterating:
```python
for state in list(deps.swarm_store.values()):
```
