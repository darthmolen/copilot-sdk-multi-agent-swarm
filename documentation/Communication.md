# Communication Flow

## Overview

The swarm system communicates through a layered event-driven architecture with per-swarm routing. The **React UI** initiates swarm runs via authenticated REST calls to **FastAPI**, which creates a **SwarmOrchestrator** and returns a `swarm_id`. The UI opens a **WebSocket** connection (with API key) to receive real-time updates scoped to that swarm. The orchestrator manages the full lifecycle by delegating planning to a **Leader Session** (via tool-based structured output) and distributing work to **Worker Sessions** (event-driven, waiting for `session.idle`). Workers mutate shared state on the **TaskBoard** through defensive tool handlers, while all state transitions flow through the **EventBus** tagged with `swarm_id` for per-swarm routing.

## Full Swarm Lifecycle

```mermaid
sequenceDiagram
    participant User as User (React UI)
    participant Auth as AuthGate
    participant FastAPI
    participant Orch as SwarmOrchestrator
    participant Leader as Leader Session (Copilot CLI)
    participant W1 as Worker Session 1
    participant W2 as Worker Session 2
    participant TB as TaskBoard
    participant EB as EventBus
    participant WS as WebSocket

    %% Auth
    User->>Auth: Enter API key
    Auth->>Auth: Store in sessionStorage

    %% Start swarm
    User->>FastAPI: POST /api/swarm/start {goal, template}<br/>X-API-Key header
    FastAPI->>FastAPI: verify_api_key()
    FastAPI->>Orch: create SwarmOrchestrator(swarm_id, work_base)
    FastAPI-->>User: {swarm_id, status: "starting"}

    %% Connect WebSocket
    User->>WS: connect /ws/{swarm_id}?key=...
    WS->>WS: verify key
    WS-->>User: connection established

    %% Create work directory
    Orch->>Orch: mkdir workdir/{swarm_id}/

    %% Plan phase (tool-based)
    Orch->>Leader: create_session(system_message=LEADER_PROMPT, tools=[create_plan])
    Orch->>Leader: session.send(goal)
    Leader->>Leader: calls create_plan tool with SwarmPlan schema
    Leader-->>Orch: plan captured via tool handler

    %% Create tasks
    Orch->>EB: _emit("swarm.phase_changed", {phase: "planning", swarm_id})
    loop for each task in plan
        Orch->>TB: add_task(id, subject, description, blocked_by)
        Orch->>EB: _emit("task.created", {task, swarm_id})
    end
    EB->>WS: broadcast to swarm_id connections
    WS-->>User: task.created events

    %% Spawn workers
    loop for each unique worker
        Orch->>W1: SwarmAgent.create_session(system_message=mode:replace, model=gemini-3-pro-preview, work_dir)
    end
    Orch->>EB: _emit("agent.spawned", {agent, swarm_id})
    EB->>WS: broadcast agent.spawned
    WS-->>User: agent cards appear

    %% Execute round 1
    Orch->>EB: _emit("agent.status_changed", {status: "working", swarm_id})
    Orch->>W1: session.send("Your task ID is: task-0\nSubject: ...\n\nDescription")
    Orch->>W2: session.send("Your task ID is: task-1\n...")

    %% Worker calls task_update
    W1->>TB: task_update(task_id="task-0", status="in_progress")
    W1->>EB: tool event → "task.updated" {task, swarm_id}
    EB->>WS: broadcast task.updated (real-time status change)
    WS-->>User: task moves to In Progress column

    %% Worker completes
    W1->>TB: task_update(task_id="task-0", status="completed", result="...")
    W1->>EB: tool event → "task.updated" {task, swarm_id}
    W1-->>Orch: SessionEvent(session.idle)
    Note over Orch: SwarmAgent._handler sets done event

    Orch->>EB: _emit("agent.status_changed", {status: "idle", tasks_completed: 1, swarm_id})

    %% Synthesis
    Orch->>Orch: Read all .md files from workdir/{swarm_id}/
    Orch->>Leader: create_session(synthesis_prompt + task_results + work_dir_content)
    Orch->>Leader: session.send(synthesis_prompt)
    Leader-->>Orch: assistant.message text captured via session.on()
    Orch->>EB: _emit("leader.report", {content: report, swarm_id})
    EB->>WS: broadcast leader.report
    WS-->>User: report modal auto-pops
```

## Event Routing

All events carry `swarm_id`. The WebSocket forwarder in `main.py` uses `data.get("swarm_id")` (non-destructive) to route events to the correct WS connections via `ConnectionManager.broadcast(swarm_id, ...)`.

### Unified SDK Event Bridge

All SDK tool events — from leader sessions (QA, synthesis, chat) and worker sessions alike — flow through a single `bridge_raw_sdk_event()` function in `event_bridge.py`. This replaces the former split between `leader.chat_tool_*` and `agent.tool_*` event paths.

```
SDK Event (raw)                         WebSocket Event (unified)
─────────────────                       ──────────────────────────
tool.execution_start       ──►          agent.tool_call
tool.execution_complete    ──►          agent.tool_result
tool.execution_partial     ──►          agent.tool_output
assistant.message_delta    ──►          agent.message_delta
```

**Two emission paths, one bridge:**

| Path | Source | How it reaches the bridge |
| --- | --- | --- |
| **Leader sessions** | Orchestrator's `chat()`, `qa_chat()`, `start_qa()` | `_forward_chat_sdk_event()` calls `bridge_raw_sdk_event("leader", event, message_id=...)` and emits directly via `EventBus.emit_sync()` |
| **Worker sessions** | `SwarmAgent._on_event()` | Emits raw `sdk_event` to EventBus → `_forward()` in `main.py` calls `bridge_raw_sdk_event(agent_name, event)` and broadcasts via WebSocket |

**`message_id` discriminates context:** When present, the tool event belongs to a chat conversation (QA, after-action, troubleshoot). When absent, it's background agent work. The frontend uses this to route events:

- `message_id` present → dispatched to **chat reducer** (appears in ChatPanel timeline)
- Always dispatched to **swarm reducer** (appears in dashboard ToolCardList)

### Frontend Event Routing

The frontend's `SwarmConnection` component tags each incoming WS event with the `swarmId` from the connection URL, then dispatches to the `multiSwarmReducer` which routes to the correct per-swarm state.

**Dual dispatch for tool events:**

```typescript
case 'agent.tool_call':
  if (data.message_id) chatDispatch({ type: 'chat.tool_start', ... });
  swarmDispatch({ type: 'swarm.event', ... });

case 'agent.tool_result':
  if (data.message_id) chatDispatch({ type: 'chat.tool_result', ... });
  swarmDispatch({ type: 'swarm.event', ... });
```

## WebSocket Event Taxonomy

### Orchestrator Events

Emitted by `SwarmOrchestrator._emit()` — all include `swarm_id`.

| Event Type | Description | Data Shape |
| --- | --- | --- |
| `swarm.phase_changed` | Phase transition | `{ phase, swarm_id }` |
| `swarm.plan_complete` | Leader finished task decomposition | `{ task_count, swarm_id }` |
| `swarm.spawn_complete` | All worker sessions created | `{ agent_count, swarm_id }` |
| `swarm.round_start` | Execution round beginning | `{ round, runnable_count, swarm_id }` |
| `swarm.round_end` | Execution round finished | `{ round, swarm_id }` |
| `swarm.synthesis_complete` | Final report produced | `{ swarm_id }` |
| `swarm.error` | Fatal error | `{ message, swarm_id }` |
| `swarm.cancelled` | User cancelled | `{ swarm_id }` |
| `swarm.task_failed` | Task execution failed | `{ task_id, agent, error, swarm_id }` |
| `swarm.rounds_exhausted` | Max rounds reached with tasks remaining | `{ remaining_tasks, max_rounds, swarm_id }` |
| `swarm.suspended` | Swarm paused awaiting user decision | `{ remaining_tasks, max_rounds, reason, swarm_id }` |

### Task and Agent Events

| Event Type | Source | Description | Data Shape |
| --- | --- | --- | --- |
| `task.created` | Orchestrator plan phase | New task added to board | `{ task: {id, subject, status, ...}, swarm_id }` |
| `task.updated` | Tool handler + orchestrator | Task status/result changed | `{ task: {id, status, result, ...}, swarm_id }` |
| `agent.spawned` | Orchestrator spawn phase | New agent registered | `{ agent: {name, role, display_name, status, tasks_completed}, swarm_id }` |
| `agent.status_changed` | Orchestrator execute phase | Agent working/idle/failed | `{ agent_name, status, tasks_completed?, swarm_id }` |
| `agent.resumed` | Orchestrator resume_agent | Agent session resumed after failure | `{ agent_name, swarm_id }` |
| `inbox.message` | Tool handler (inbox_send) | Inter-agent message | `{ sender, recipient, content, timestamp, swarm_id }` |
| `leader.plan` | Orchestrator plan phase | Raw plan text | `{ content, swarm_id }` |
| `leader.report` | Orchestrator synthesis phase | Final report | `{ content, swarm_id }` |

### Unified Tool Events (via `bridge_raw_sdk_event`)

These events are emitted by both leader and worker sessions through the unified bridge. `message_id` is present when the tool event belongs to a chat conversation, absent for background work.

| Event Type | Description | Data Shape |
| --- | --- | --- |
| `agent.tool_call` | Tool execution started | `{ agent_name, tool_name, tool_call_id, input, message_id?, swarm_id }` |
| `agent.tool_result` | Tool execution completed | `{ agent_name, tool_call_id, success, output?, error?, message_id?, swarm_id }` |
| `agent.tool_output` | Partial tool result (streaming) | `{ agent_name, tool_call_id, output, message_id?, swarm_id }` |
| `agent.message_delta` | Streaming assistant text chunk | `{ agent_name, delta, message_id?, swarm_id }` |

The `input` field is a human-readable summary of tool arguments (e.g., `file_path=/src/foo.py` for read, `command=ls -la` for bash). The `output` field is truncated to 500 chars; `error` to 300 chars.

### Chat Events

Emitted by the orchestrator's leader sessions during QA, synthesis, and refinement chat. These drive the ChatPanel timeline.

| Event Type | Description | Data Shape |
| --- | --- | --- |
| `leader.chat_delta` | Streaming chat text chunk | `{ delta, message_id, swarm_id }` |
| `leader.chat_message` | Complete chat response | `{ content, message_id, swarm_id }` |
| `leader.report_delta` | Streaming report text | `{ delta, swarm_id }` |

### Frontend Reducer Events

Two reducers handle events on the frontend:

**Swarm reducer** (`multiSwarmReducer` → `swarmReducer`) — dashboard state:

| Event Type | State Effect |
| --- | --- |
| `swarm.phase_changed` | Sets `phase` |
| `task.created` | Appends to `tasks` with `swarm_id` from event data |
| `task.updated` | Updates matching task by `id` |
| `agent.spawned` | Appends to `agents` with `swarm_id` from event data |
| `agent.status_changed` | Updates agent status and `tasks_completed` |
| `agent.tool_call` | Appends to `activeTools` with `input`, `startedAt` |
| `agent.tool_result` | Updates tool status, `output`, `error`, `completedAt` |
| `inbox.message` | Appends to `messages` with `swarm_id` from event data |
| `leader.report` | Sets `leaderReport` |
| `round.started` / `swarm.round_start` | Sets `roundNumber` |
| `swarm.complete` | Sets `phase` to `"complete"` |
| `swarm.error` | Sets `error` |
| `swarm.suspended` | Sets `phase` to `"suspended"`, stores pause metadata |

**Chat reducer** (`chatReducer`) — chat timeline state per swarm:

| Action Type | State Effect |
| --- | --- |
| `chat.delta` | Appends to `streamingMessage` content |
| `chat.message` | Pushes `{ type: 'message' }` entry, clears `streamingMessage` |
| `chat.user_send` | Pushes `{ type: 'message' }` entry, sets `sessionStarting` |
| `chat.tool_start` | Appends tool to current `tool_group` entry (or creates new one) |
| `chat.tool_result` | Updates tool in its `tool_group` with status, output, error |
| `chat.clear` | Resets entries and streaming state |

The chat state uses a `ChatEntry[]` timeline — a union of `message | tool_group | streaming` entries. Tool groups form naturally: consecutive tool events accumulate in the same group until a message entry closes it.

### Multi-Swarm Store Actions

| Action Type | Effect |
| --- | --- |
| `swarm.add` | Creates new per-swarm state, adds to `activeSwarmIds` |
| `swarm.remove` | Frees all data for that swarm |
| `swarm.event` | Routes inner event to correct swarm's reducer |

Auto-transitions: When a swarm's phase becomes `complete`, `cancelled`, or `failed`, it moves from `activeSwarmIds` to `completedSwarmIds` (WS disconnects, data retained for report viewing). Suspended swarms remain in `activeSwarmIds` — the user hasn't decided yet. Hard cap of 10 swarms with oldest-completed auto-eviction.

See [MCP-Swarm-Server.md](MCP-Swarm-Server.md) for the full MCP tool reference, agentic use cases, and configuration.

See [Agents.md](Agents.md) for system prompt architecture, agent roles, coordination tools, and template configuration.