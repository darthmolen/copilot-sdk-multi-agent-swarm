# BACKLOG: Live Chat Agent with Swarm Awareness

## Vision

Make the report view's Refinement Chat useful **during** execution — not just after. The chat agent should be able to report swarm progress, answer status questions, and eventually let users steer in-flight work.

## Current Architecture Gaps

| Gap | Current State |
|-----|---------------|
| Event persistence | EventBus is fire-and-forget. No history. Late-connecting clients miss everything |
| State persistence | `swarm_store` + `TaskBoard` are in-memory dicts. Lost on restart |
| Chat during execution | REST endpoint returns 409 unless phase is `qa` or `complete` |
| Agent awareness | Synthesis agent gets task results once in its initial prompt. Cannot re-query |
| MCP server | Templates reference external MCP servers (e.g. Microsoft Learn). No internal MCP for swarm state |

## Proposed Architecture

### 1. PostgreSQL Persistence Layer

Replace in-memory stores with Postgres. This enables:
- Event replay for late-connecting clients
- Swarm state survives restarts
- MCP server can query independently of the Python process
- Foundation for analytics, audit trail, multi-user

**Tables:**
```
swarms        (id, template_key, goal, refined_goal, phase, created_at, completed_at)
tasks         (id, swarm_id, subject, description, worker_name, status, result, created_at, updated_at)
agents        (id, swarm_id, name, role, display_name, status, tasks_completed)
events        (id, swarm_id, event_type, data_json, created_at)  -- append-only log
inbox         (id, swarm_id, sender, recipient, content, created_at, read_at)
files         (id, swarm_id, filename, path, size_bytes, created_at)
```

**Migration path**: Keep `swarm_store` dict as hot cache, write-through to Postgres. EventBus gets a new subscriber that appends to `events` table. TaskBoard writes through to `tasks` table.

### 2. Swarm State MCP Server (stdio)

A lightweight MCP stdio server that the chat/synthesis agent session connects to. Gives the agent tools to query live swarm state:

**Tools:**
| Tool | Description |
|------|-------------|
| `get_swarm_status` | Current phase, round number, active agent count |
| `list_tasks` | All tasks with status, optionally filtered by status/worker |
| `get_task_detail` | Full task result + timeline for a specific task |
| `get_recent_events` | Last N events or events since timestamp |
| `list_agents` | Agent names, roles, current status, tasks completed |
| `read_artifact` | Read a file from the work directory |
| `list_artifacts` | List files created so far |

**Implementation**: Python `mcp` SDK, stdio transport. Reads from Postgres (or from in-memory stores as interim). Registered as an MCP server on the chat/synthesis session.

**Key design choice**: Read-only initially. The agent can report status but not modify tasks. Write tools (e.g., `request_task_change`, `pause_agent`) come later after we validate the read pattern.

### 3. Chat During Execution

Currently `chat_with_swarm()` in `rest.py` blocks chat unless phase is `qa` or `complete`. Open this up:

- **During execution**: Create a new "observer" session with the swarm state MCP server. This session can answer "what's the status?" using the MCP tools. It doesn't interfere with running agents.
- **During synthesis**: The existing synthesis session gets the MCP server added, so it can check task results dynamically.
- **After completion**: Same as today, but with richer context via MCP.

### 4. Document Streaming + User Edits

The synthesis agent streams `leader.report_delta` events. To allow mid-stream user interaction:

- User sends a chat message during synthesis → backend interrupts synthesis session with the user's feedback
- Synthesis agent sees the feedback + can re-query task results via MCP
- Requires the SDK to support mid-stream message injection (or we pause/resume synthesis)

This is the highest-risk feature — depends on SDK capabilities. Defer until read-only MCP is validated.

## Implementation Phases

### Phase 1: Postgres + Event Log (foundation) — COMPLETED
See `planning/completed/persistence-layer.md` (PR #8)

### Phase 2: Swarm State MCP Server — COMPLETED

See `planning/completed/swarm-state-mcp-server.md` (branch `feature/swarm-state-mcp-server`)
9 tools, in-process streamable HTTP, type-safe, `restart_agent` write tool included.

### Phase 3: Chat During Execution
- Remove phase gate on chat endpoint
- Create observer session with MCP server for mid-execution queries
- User can ask "how's task X going?" and get a real answer
- Toast/notification when agent completes a task (frontend already handles `task.updated`)

### Phase 4: Interactive Synthesis
- User can send feedback while synthesis streams
- Agent pauses, incorporates feedback, continues
- Requires SDK investigation for mid-stream injection

## Open Questions
- **Postgres hosting**: Local dev via Docker? Managed for production?
- **MCP server lifecycle**: One per swarm? Shared singleton with swarm_id parameter?
- **Observer session model**: Which model for the mid-execution chat agent? Same as leader?
- **SDK support**: Can we inject messages into a running session, or must we pause/resume?
