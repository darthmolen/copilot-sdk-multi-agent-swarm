# BACKLOG: Live Chat Agent with Swarm Awareness

## Vision

Make the report view's Refinement Chat useful **during** execution — not just after. The chat agent should be able to report swarm progress, answer status questions, and eventually let users steer in-flight work.

## Prerequisite

Persistence layer (COMPLETED — see `planning/completed/persistence-layer.md`). SwarmService + SwarmRepository + EventLogger are in place.

## Remaining Work

### 1. Swarm State MCP Server (stdio)

A lightweight MCP stdio server that the chat/synthesis agent session connects to. Gives the agent tools to query live swarm state:

| Tool | Description |
|------|-------------|
| `get_swarm_status` | Current phase, round number, active agent count |
| `list_tasks` | All tasks with status, optionally filtered by status/worker |
| `get_task_detail` | Full task result + timeline for a specific task |
| `get_recent_events` | Last N events or events since timestamp |
| `list_agents` | Agent names, roles, current status, tasks completed |
| `read_artifact` | Read a file from the work directory |
| `list_artifacts` | List files created so far |

**Implementation**: Python `mcp` SDK, stdio transport. Reads from SwarmService (cache-first, backed by Postgres). Registered as an MCP server on the chat/synthesis session.

**Key design choice**: Read-only initially. The agent can report status but not modify tasks. Write tools (e.g., `request_task_change`, `pause_agent`) come later after we validate the read pattern.

### 2. Chat During Execution

Currently `chat_with_swarm()` in `rest.py` blocks chat unless phase is `qa` or `complete`. Open this up:

- **During execution**: Create a new "observer" session with the swarm state MCP server. This session can answer "what's the status?" using the MCP tools. It doesn't interfere with running agents.
- **During synthesis**: The existing synthesis session gets the MCP server added, so it can check task results dynamically.
- **After completion**: Same as today, but with richer context via MCP.

### 3. Document Streaming + User Edits

The synthesis agent streams `leader.report_delta` events. To allow mid-stream user interaction:

- User sends a chat message during synthesis → backend interrupts synthesis session with the user's feedback
- Synthesis agent sees the feedback + can re-query task results via MCP
- Requires the SDK to support mid-stream message injection (or we pause/resume synthesis)

This is the highest-risk feature — depends on SDK capabilities. Defer until read-only MCP is validated.

## Open Questions

- **MCP server lifecycle**: One per swarm? Shared singleton with swarm_id parameter?
- **Observer session model**: Which model for the mid-execution chat agent? Same as leader?
- **SDK support**: Can we inject messages into a running session, or must we pause/resume?
