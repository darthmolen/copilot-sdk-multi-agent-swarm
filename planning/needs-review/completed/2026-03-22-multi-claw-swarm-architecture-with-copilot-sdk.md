# Multi-Claw Swarm Architecture with Copilot SDK

## Context

We want to emulate the [multi-claw swarm intelligence architecture](research/multi-claw-article/README.md) — where a leader agent decomposes goals into subtasks assigned to specialized worker agents — powered by **copilot-cli in headless mode** (via copilot-sdk Python) with a React chat UI for real-time visibility.

The reference implementation (research/multi-claw-article/) uses OpenAI function calling with 4 coordination tools and shared in-memory state. We port this to copilot-sdk, leveraging its **native custom agents**, **sub-agent lifecycle events**, and **rich streaming event system** (70 event types).

## Architecture Decision: Copilot-SDK with Native Custom Agents

**Key discovery:** The copilot-sdk has a built-in `custom_agents` system ([docs](research/copilot-sdk/docs/features/custom-agents.md)) that provides:
- Per-agent system prompts, tool scoping, display names, descriptions
- Automatic inference-based routing (or explicit `session.rpc.agent.select()`)
- Sub-agent lifecycle events: `subagent.started`, `subagent.completed`, `subagent.failed`, `subagent.selected`, `subagent.deselected`
- Agent-specific MCP servers

**Architecture: One session per worker, custom_agents for identity**

Each worker agent gets its own `CopilotSession` with:
- A single `custom_agents` entry pre-selected via the `agent` parameter
- 4 swarm coordination tools registered via `define_tool`
- `on_event` callback streaming all 70 event types to the frontend

The leader agent gets its own session (no swarm tools, just planning).

**Why one session per worker (not one session with all agents)?**
The multi-claw pattern requires *concurrent* agent execution. A single session can only have one active agent at a time. Multiple sessions allow `asyncio.gather()` for true parallelism.

**Why custom_agents instead of raw `system_message: {"mode": "replace"}`?**
- Sub-agent lifecycle events come for free (`subagent.started/completed/failed`)
- Tool scoping is enforced at SDK level (not just prompt-based)
- Agent display names appear in events for the UI
- `infer: false` prevents unexpected agent switching

**Timeout handling insight:** `send_and_wait` defaults to 60s timeout, but the agent behind the scenes continues and finishes. We should use `session.on()` event subscription instead of `send_and_wait` for workers, listening for `assistant.turn_end` as the completion signal. This gives us streaming deltas during execution and graceful handling of long-running tasks.

## Data Flow

```text
User types goal in React UI
        │
        ▼
[WebSocket] → [FastAPI Backend]
                    │
             SwarmOrchestrator
                    │
    ┌───────────────┼───────────────────┐
    ▼               ▼                   ▼
  Leader          Worker 1            Worker N
  Session         Session             Session
  (plan only)     (custom_agent +     (custom_agent +
                   swarm tools)        swarm tools)
    │               │                   │
    │          on_event callback    on_event callback
    │               │                   │
    └───────────────┼───────────────────┘
                    ▼
              EventBus → WebSocket → React UI
                    │
             Shared State (asyncio.Lock)
               ├── TaskBoard
               ├── InboxSystem
               └── TeamRegistry
```

**Event flow per worker turn:**
```text
session.on(handler) receives:
  assistant.turn_start         → agent.status_changed {thinking}
  assistant.reasoning_delta*   → agent.reasoning_delta {streaming extended thinking}
  assistant.reasoning          → agent.reasoning {complete reasoning block}
  assistant.message_delta*     → agent.message_delta {streaming text}
  assistant.message            → MAY CONTAIN tool_requests (see note below)
  tool.execution_start         → agent.tool_call {tool_name, args}
  tool.execution_partial_result → agent.tool_output {streaming tool stdout}
  tool.execution_complete      → (swarm tool mutates shared state → task.updated / inbox.message)
  [loop: next assistant.message with tool results → more tool calls → ...]
  assistant.message            → final content (no tool_requests = agent is done thinking)
  subagent.started             → agent.status_changed {working}
  subagent.completed           → agent.status_changed {idle}
  assistant.turn_end           → COMPLETION SIGNAL (not session.idle)
  assistant.usage              → token tracking
```

**Critical: The tool_requests one-step-off pattern**

The `assistant.message` event has a dual nature (learned from the vscode extension):
- When `assistant.message.tool_requests` is present: the LLM decided to call tools, but they haven't executed yet. The `content` is mid-thought and should be **suppressed** from the UI. Tool execution events (`tool.execution_start/complete`) follow *after*.
- When `assistant.message.tool_requests` is absent: this is final content — the LLM is done reasoning for this cycle. Display it.

The extension handles this at [sdkSessionManager.ts:682-693](research/vscode-extension-copilot-cli/src/sdkSessionManager.ts#L682-L693):
```python
# Our event bridge must replicate this logic:
if event.type == SessionEventType.ASSISTANT_MESSAGE:
    has_tool_requests = bool(event.data.tool_requests)
    has_content = bool(event.data.content and event.data.content.strip())
    if has_content and not has_tool_requests:
        # Final content — emit to UI
        emit("agent.message", {"agent_name": name, "content": event.data.content})
    elif has_tool_requests:
        # Mid-thought — suppress content, finalize any streaming bubble
        emit("agent.message_finalize", {"agent_name": name, "message_id": event.data.message_id})
```

**Reasoning deltas** (`assistant.reasoning_delta`) stream the LLM's extended thinking (chain-of-thought) before it produces the visible response. Data shape: `{reasoning_id: str, delta_content: str}`. These are valuable for the UI to show "agent is thinking about..." indicators. The complete block arrives as `assistant.reasoning` with `{reasoning_id, content}`.

## File Structure

```text
src/
  backend/
    __init__.py
    main.py                      # FastAPI app, startup/shutdown
    config.py                    # Settings (model, timeouts, max_rounds)
    events.py                    # EventBus: bridges SDK events → WebSocket
    swarm/
      __init__.py
      models.py                  # Pydantic: Task, TaskStatus, AgentInfo, InboxMessage
      task_board.py              # TaskBoard with asyncio.Lock, dependency resolution
      inbox_system.py            # InboxSystem with asyncio.Lock
      team_registry.py           # TeamRegistry with asyncio.Lock
      tools.py                   # Factory: create_swarm_tools() → list[Tool]
      agent.py                   # SwarmAgent: CopilotSession + custom_agent + event bridging
      orchestrator.py            # SwarmOrchestrator: plan → spawn → execute → synthesize
      prompts.py                 # Leader + worker system prompts
      templates.py               # Pre-built templates (software-development, deep-research, warehouse-optimizer)
    api/
      __init__.py
      websocket.py               # WebSocket connection manager
      rest.py                    # REST: POST /swarm/start, GET /swarm/{id}/status, GET /templates
      schemas.py                 # API request/response models
  frontend/
    package.json
    vite.config.ts
    src/
      App.tsx
      main.tsx
      components/
        ChatPanel.tsx            # Leader conversation + final report (streaming)
        TaskBoard.tsx            # Kanban: BLOCKED | PENDING | IN_PROGRESS | COMPLETED
        AgentRoster.tsx          # Agent cards: name, role, status, tasks completed
        InboxFeed.tsx            # Scrolling inter-agent message feed
        SwarmControls.tsx        # Goal input, template select, start button
      hooks/
        useWebSocket.ts          # WebSocket connection + reconnect + resync
        useSwarmState.ts         # Reducer: accumulates WS events into state
      types/
        swarm.ts                 # TS types mirroring backend models
```

## Key Copilot-SDK Integration Patterns

### Worker session creation with custom_agents

```python
# src/backend/swarm/agent.py
session = await client.create_session(
    on_permission_request=PermissionHandler.approve_all,
    custom_agents=[{
        "name": agent_name,
        "display_name": f"{role} Agent",
        "description": f"Specialized worker: {role}",
        "prompt": worker_system_prompt,
        "tools": None,  # All session tools (the 4 swarm tools)
        "infer": False,  # Don't auto-switch; this session has one agent
    }],
    agent=agent_name,  # Pre-select this agent
    tools=create_swarm_tools(agent_name, task_board, inbox, event_bus),
    on_event=lambda evt: event_bridge(agent_name, evt),
)
```

### Event-driven execution (not send_and_wait)

```python
# src/backend/swarm/agent.py
async def execute_task(self, task: Task) -> None:
    """Send task to agent, wait for turn_end via event subscription."""
    turn_complete = asyncio.Event()

    def on_event(event: SessionEvent):
        # Bridge all events to frontend via EventBus
        self.event_bus.emit_sync(agent_name, event)
        # Detect completion
        if event.type == SessionEventType.ASSISTANT_TURN_END:
            turn_complete.set()
        elif event.type == SessionEventType.SESSION_ERROR:
            turn_complete.set()  # Don't hang on errors

    unsubscribe = self.session.on(on_event)
    try:
        self.task_board.update_status(task.id, "in_progress")
        await self.session.send(task_prompt)
        # Wait with generous timeout — agent continues behind the scenes
        await asyncio.wait_for(turn_complete.wait(), timeout=300.0)
    except TimeoutError:
        # Agent may still be working; mark as needs-attention, don't fail
        self.task_board.update_status(task.id, "timeout")
    finally:
        unsubscribe()
```

### Tool registration (closure-captured shared state)

```python
# src/backend/swarm/tools.py
def create_swarm_tools(agent_name: str, task_board: TaskBoard, inbox: InboxSystem, event_bus: EventBus) -> list[Tool]:

    @define_tool(description="Update a task's status and optionally record its result", skip_permission=True)
    async def task_update(params: TaskUpdateParams) -> str:
        task_board.update_status(params.task_id, params.status, params.result)
        await event_bus.emit("task.updated", {"task_id": params.task_id, "status": params.status})
        return json.dumps({"ok": True})

    @define_tool(description="Send a message to another agent or the leader", skip_permission=True)
    async def inbox_send(params: InboxSendParams) -> str:
        inbox.send(agent_name, params.to, params.message)
        await event_bus.emit("inbox.message", {"sender": agent_name, "to": params.to})
        return json.dumps({"ok": True})

    # ... inbox_receive, task_list (both skip_permission=True)
    return [task_update, inbox_send, inbox_receive, task_list]
```

Note: `skip_permission=True` on all swarm tools — these are internal coordination, not user-facing actions.

### Event bridge: SDK events → WebSocket

```python
# src/backend/events.py
def bridge_sdk_event(agent_name: str, event: SessionEvent, ws_manager: ConnectionManager):
    """Map SDK's 70 event types to our WebSocket event taxonomy.

    Key pattern from the vscode extension (sdkSessionManager.ts:659-892):
    - assistant.message with tool_requests → suppress content, finalize streaming bubble
    - assistant.message without tool_requests → final content, emit to UI
    - reasoning_delta → stream extended thinking for "agent is thinking" indicators
    """
    match event.type:
        # --- Turn lifecycle ---
        case SessionEventType.ASSISTANT_TURN_START:
            ws_manager.broadcast({"type": "agent.status_changed", "data": {"name": agent_name, "status": "thinking"}})
        case SessionEventType.ASSISTANT_TURN_END:
            ws_manager.broadcast({"type": "agent.status_changed", "data": {"name": agent_name, "status": "ready"}})

        # --- Reasoning (extended thinking) ---
        case SessionEventType.ASSISTANT_REASONING_DELTA:
            ws_manager.broadcast({"type": "agent.reasoning_delta", "data": {
                "agent_name": agent_name, "reasoning_id": event.data.reasoning_id, "delta": event.data.delta_content}})
        case SessionEventType.ASSISTANT_REASONING:
            ws_manager.broadcast({"type": "agent.reasoning", "data": {
                "agent_name": agent_name, "reasoning_id": event.data.reasoning_id, "content": event.data.content}})

        # --- Response streaming ---
        case SessionEventType.ASSISTANT_MESSAGE_DELTA:
            ws_manager.broadcast({"type": "agent.message_delta", "data": {
                "agent_name": agent_name, "delta": event.data.delta_content, "message_id": event.data.message_id}})

        # --- Complete message (handles tool_requests one-step-off) ---
        case SessionEventType.ASSISTANT_MESSAGE:
            has_tool_requests = bool(getattr(event.data, 'tool_requests', None))
            has_content = bool(getattr(event.data, 'content', '') and event.data.content.strip())
            if has_content and not has_tool_requests:
                ws_manager.broadcast({"type": "agent.message", "data": {
                    "agent_name": agent_name, "content": event.data.content}})
            elif has_tool_requests:
                # Mid-thought: LLM wants to call tools. Suppress content, finalize streaming bubble.
                ws_manager.broadcast({"type": "agent.message_finalize", "data": {
                    "agent_name": agent_name, "message_id": getattr(event.data, 'message_id', '')}})

        # --- Tool execution lifecycle ---
        case SessionEventType.TOOL_EXECUTION_START:
            ws_manager.broadcast({"type": "agent.tool_call", "data": {
                "agent_name": agent_name, "tool_name": event.data.tool_name, "tool_call_id": event.data.tool_call_id}})
        case SessionEventType.TOOL_EXECUTION_PARTIAL_RESULT:
            ws_manager.broadcast({"type": "agent.tool_output", "data": {
                "agent_name": agent_name, "tool_call_id": event.data.tool_call_id, "output": event.data.partial_output}})
        case SessionEventType.TOOL_EXECUTION_COMPLETE:
            ws_manager.broadcast({"type": "agent.tool_result", "data": {
                "agent_name": agent_name, "tool_call_id": event.data.tool_call_id, "success": event.data.success}})

        # --- Sub-agent lifecycle ---
        case SessionEventType.SUBAGENT_STARTED:
            ws_manager.broadcast({"type": "agent.status_changed", "data": {"name": agent_name, "status": "working"}})
        case SessionEventType.SUBAGENT_COMPLETED:
            ws_manager.broadcast({"type": "agent.status_changed", "data": {"name": agent_name, "status": "idle"}})
        case SessionEventType.SUBAGENT_FAILED:
            ws_manager.broadcast({"type": "agent.error", "data": {"name": agent_name, "error": event.data.error}})

        # --- Usage & errors ---
        case SessionEventType.ASSISTANT_USAGE:
            ws_manager.broadcast({"type": "agent.usage", "data": {"agent_name": agent_name, "tokens": event.data}})
        case SessionEventType.SESSION_ERROR:
            ws_manager.broadcast({"type": "agent.error", "data": {"name": agent_name, "error": event.data.message}})
```

## WebSocket Events (server → client)

| Event | Data |
| ----- | ---- |
| `swarm.phase_changed` | `{ phase: "planning" \| "spawning" \| "executing" \| "synthesizing" \| "complete" }` |
| `task.created` | `{ task: Task }` |
| `task.updated` | `{ task_id, status, result? }` |
| `agent.spawned` | `{ name, role, display_name }` |
| `agent.status_changed` | `{ name, status: "thinking" \| "working" \| "idle" \| "ready" \| "failed" }` |
| `agent.reasoning_delta` | `{ agent_name, reasoning_id, delta }` — streaming extended thinking |
| `agent.reasoning` | `{ agent_name, reasoning_id, content }` — complete thinking block |
| `agent.message_delta` | `{ agent_name, delta, message_id }` — streaming response text |
| `agent.message` | `{ agent_name, content }` — final content (no tool_requests) |
| `agent.message_finalize` | `{ agent_name, message_id }` — mid-thought suppression (has tool_requests) |
| `agent.tool_call` | `{ agent_name, tool_name, tool_call_id }` |
| `agent.tool_output` | `{ agent_name, tool_call_id, output }` — streaming tool stdout |
| `agent.tool_result` | `{ agent_name, tool_call_id, success }` |
| `agent.error` | `{ name, error }` |
| `agent.usage` | `{ agent_name, tokens }` |
| `inbox.message` | `{ sender, recipient, content }` |
| `round.started` / `round.completed` | `{ round_number }` |
| `leader.plan` | `{ tasks: Task[] }` |
| `leader.message_delta` | `{ delta }` |
| `leader.report` | `{ content }` |
| `swarm.complete` | `{ tasks_completed, agents_used, rounds }` |
| `swarm.error` | `{ message }` |

## Development Methodology: TDD (Red-Green-Refactor)

Every phase follows strict TDD. Tests exercise real production behavior through public APIs, not string comparisons or mock internals.

**Red-Green-Refactor cycle:**
1. **Red** — Write a failing test that describes the desired behavior against the production interface
2. **Green** — Write the minimum production code to make the test pass
3. **Refactor** — Clean up while keeping tests green

**Testing principles:**
- Tests call production code through its public API (e.g., `task_board.add_task()`, `task_board.update_status()`, `task_board.get_runnable_tasks()`)
- Assert on observable state changes and return values, not internal implementation details
- No mocking shared state — use real TaskBoard, InboxSystem, TeamRegistry instances
- For copilot-sdk integration (Phase 2), mock only the external boundary (`CopilotClient`/`CopilotSession`) — everything above that layer uses real objects
- For API tests (Phase 3), use FastAPI's `TestClient` with real WebSocket connections
- For frontend (Phase 4), test hooks with real reducers and mock only the WebSocket transport

## Implementation Phases

### Phase 1: Swarm Core (no SDK, no web)

TDD cycle for each module:

**1a. TaskBoard**

- RED: Test `add_task` returns task with PENDING status
- GREEN: Implement `add_task` in `task_board.py`
- RED: Test `update_status` transitions PENDING → IN_PROGRESS → COMPLETED
- GREEN: Implement `update_status`
- RED: Test dependency resolution — task blocked by task A becomes PENDING when A completes
- GREEN: Implement `_resolve_dependencies`
- RED: Test `get_runnable_tasks` returns only PENDING tasks (not BLOCKED, not COMPLETED)
- GREEN: Implement `get_runnable_tasks`
- RED: Test concurrent access — two async updates don't corrupt state
- GREEN: Add asyncio.Lock

**1b. InboxSystem**

- RED: Test `send` + `receive` delivers message with correct sender/recipient/content
- GREEN: Implement send/receive
- RED: Test `receive` is destructive (second call returns empty)
- GREEN: Implement consumption semantics
- RED: Test `peek` is non-destructive
- GREEN: Implement peek
- RED: Test `broadcast` delivers to all agents except sender
- GREEN: Implement broadcast

**1c. TeamRegistry**

- RED: Test `register` + `get_all` returns agent with correct name/role/status
- GREEN: Implement register/get_all
- RED: Test `update_status` changes agent status and increments task count
- GREEN: Implement update_status

**1d. Models + Prompts**

- `models.py` — Pydantic models (no TDD needed, these are data classes)
- `prompts.py` — System prompts (validated in Phase 2 integration tests)

Files:
- `src/backend/swarm/models.py`
- `src/backend/swarm/task_board.py`
- `src/backend/swarm/inbox_system.py`
- `src/backend/swarm/team_registry.py`
- `src/backend/swarm/prompts.py`
- `tests/test_task_board.py`
- `tests/test_inbox_system.py`
- `tests/test_team_registry.py`

### Phase 2: Copilot SDK Integration

**2a. Swarm Tools**

- RED: Test `create_swarm_tools` returns 4 Tool objects with correct names and `skip_permission=True`
- GREEN: Implement factory skeleton
- RED: Test calling `task_update` tool handler mutates a real TaskBoard instance (task status changes)
- GREEN: Wire tool handler to TaskBoard.update_status
- RED: Test calling `inbox_send` tool handler delivers message to real InboxSystem
- GREEN: Wire tool handler to InboxSystem.send
- RED: Test `task_list` returns correct JSON for a TaskBoard with mixed statuses
- GREEN: Wire tool handler to TaskBoard query

**2b. SwarmAgent**

- RED: Test SwarmAgent creates session with `custom_agents` config and `agent` pre-selection (mock CopilotClient boundary)
- GREEN: Implement SwarmAgent.create_session
- RED: Test `execute_task` uses `session.send` (not `send_and_wait`) and subscribes via `session.on` for `assistant.turn_end`
- GREEN: Implement event-driven execute_task
- RED: Test timeout handling — after timeout, task marked as "timeout" not "failed"
- GREEN: Implement graceful timeout logic

**2c. Event Bridge**

- RED: Test `bridge_sdk_event` maps `ASSISTANT_MESSAGE_DELTA` to `agent.message_delta` with correct shape
- GREEN: Implement bridge for streaming events
- RED: Test `bridge_sdk_event` maps `SUBAGENT_STARTED/COMPLETED/FAILED` to `agent.status_changed`
- GREEN: Implement bridge for sub-agent lifecycle
- RED: Test `bridge_sdk_event` maps `TOOL_EXECUTION_START/COMPLETE` to `agent.tool_call/tool_result`
- GREEN: Implement bridge for tool lifecycle

**2d. SwarmOrchestrator**

- RED: Test leader planning parses JSON response into real TaskBoard tasks
- GREEN: Implement plan phase
- RED: Test spawn phase creates correct number of SwarmAgents with custom_agents config
- GREEN: Implement spawn phase
- RED: Test execute_rounds runs agents concurrently via asyncio.gather
- GREEN: Implement round execution
- RED: Test synthesis phase produces final report
- GREEN: Implement synthesis

**2e. CLI test script** — end-to-end smoke test (manual, not unit test)

Files:
- `src/backend/swarm/tools.py`
- `src/backend/swarm/agent.py`
- `src/backend/events.py`
- `src/backend/swarm/orchestrator.py`
- `tests/test_swarm_tools.py`
- `tests/test_swarm_agent.py`
- `tests/test_event_bridge.py`
- `tests/test_orchestrator.py`
- `scripts/run_swarm.py` (CLI smoke test)

### Phase 3: FastAPI + WebSocket

**3a. WebSocket Connection Manager**

- RED: Test WebSocket connection receives broadcast events
- GREEN: Implement ConnectionManager
- RED: Test multiple connections receive same broadcast
- GREEN: Implement multi-client broadcast

**3b. REST + WebSocket API**

- RED: Test `POST /swarm/start` returns swarm_id and triggers orchestrator
- GREEN: Wire REST endpoint
- RED: Test WebSocket at `/ws/{swarm_id}` receives `swarm.phase_changed` when swarm starts
- GREEN: Wire EventBus → WebSocket bridge
- RED: Test `GET /swarm/{id}/status` returns current task/agent state snapshot
- GREEN: Implement status endpoint with resync capability

Files:
- `src/backend/api/websocket.py`
- `src/backend/api/rest.py`
- `src/backend/api/schemas.py`
- `src/backend/main.py`
- `tests/test_api.py`

### Phase 4: React Frontend

- Vite + React + TypeScript scaffold
- `useWebSocket` hook with reconnection
- `useSwarmState` reducer accumulating WS events into state
- `SwarmControls` — goal input, template select, start
- `TaskBoard` — kanban columns (BLOCKED, PENDING, IN_PROGRESS, COMPLETED)
- `AgentRoster` — agent cards with real-time status, streaming message preview
- `ChatPanel` — leader conversation + streaming final report
- `InboxFeed` — inter-agent messages
- Tests: reducer tests with real event sequences, component render tests

### Phase 5: Polish

- Error handling (agent timeout → UI indicator, session errors, WS disconnect)
- Cancellation support (abort in-flight sessions)
- Template system (software-development, deep-research, warehouse-optimizer)
- Reconnection with full state resync via `GET /swarm/{id}/status`

## Risks & Mitigations

| Risk | Mitigation |
| ---- | ---------- |
| Single CLI subprocess limits concurrent sessions | Test with 3 workers; spawn multiple CopilotClients if needed |
| `custom_agents` config rejected or unsupported | Fall back to `system_message: {"mode": "customize"}` with section overrides |
| Leader JSON parsing failure | Retry with stricter prompt; consider a `create_task` tool instead |
| Agent continues past timeout | Use `session.on()` + `assistant.turn_end` instead of `send_and_wait`; 300s generous timeout; mark as "timeout" not "failed" |
| copilot-sdk not on PyPI | Install from local `research/copilot-sdk/python/` via `pip install -e` |
| Tool permission prompts block execution | Set `skip_permission=True` on all 4 swarm tools |

## Key Reference Files

- [custom-agents docs](research/copilot-sdk/docs/features/custom-agents.md) — Custom agent config, inference, tool scoping
- [custom-agents test scenario](research/copilot-sdk/test/scenarios/tools/custom-agents/python/main.py) — Working example
- [session_events.py](research/copilot-sdk/python/copilot/generated/session_events.py) — All 70 SessionEventType definitions
- [tools.py](research/copilot-sdk/python/copilot/tools.py) — `define_tool`, `ToolResult`, `skip_permission`
- [session.py](research/copilot-sdk/python/copilot/session.py) — `send`, `send_and_wait`, `on()`, `CustomAgentConfig`, `SystemMessageConfig`
- [client.py](research/copilot-sdk/python/copilot/client.py) — `create_session` full signature with `custom_agents`, `agent` params
- [sdkSessionManager.ts](research/vscode-extension-copilot-cli/src/sdkSessionManager.ts) — Reference event bridge implementation
- [sessionErrorUtils.ts](research/vscode-extension-copilot-cli/src/sessionErrorUtils.ts) — Error classification and retry patterns
- [ADR-003](research/vscode-extension-copilot-cli/documentation/ADRS/ADR-003-SEPARATE-PLANNING-SESSION.md) — Dual-session pattern reference
- [multi-claw notebook](research/multi-claw-article/ClawTeam_Agent_Swarm_Intelligence_OpenAI_Marktechpost.ipynb) — Original swarm pattern to port

## Verification

1. **Phase 1**: `pytest tests/test_task_board.py tests/test_inbox_system.py tests/test_team_registry.py` — all green
2. **Phase 2**: `pytest tests/test_swarm_tools.py tests/test_swarm_agent.py tests/test_event_bridge.py tests/test_orchestrator.py` — all green; then `python scripts/run_swarm.py "Research the top 3 Python web frameworks"` — observe streaming events in terminal, tasks reach COMPLETED
3. **Phase 3**: `pytest tests/test_api.py` — all green; then start server, connect with wscat, send start request, observe real-time event stream
4. **Phase 4**: Open React app, submit goal, verify TaskBoard updates in real-time, see agent streaming output, read final report

---

## Plan Review Feedback
*Reviewed: 2026-03-23*

### Strengths

**Deep SDK Research:** The plan demonstrates thorough investigation of the copilot-sdk. References to `custom_agents`, sub-agent lifecycle events, and the 70-event type system show excellent grounding in actual SDK capabilities. Key references (session.py, client.py, session_events.py, custom-agents.md) all exist and match descriptions.

**Critical Pattern Discovery (tool_requests one-step-off):** Correctly documents the `assistant.message` dual-nature pattern from the VSCode extension. The reference to sdkSessionManager.ts:682-693 is accurate and the Python translation is spot-on.

**Architecture Justification:** The "Why one session per worker" decision is well-reasoned: single sessions can't have concurrent active agents, so multiple sessions enable true parallelism via `asyncio.gather()`. Demonstrates understanding of SDK constraints.

**TDD Methodology:** Phase 1 follows strict Red-Green-Refactor cycles with concrete test scenarios and actual assertions. Each module has test-first examples.

**Event-Driven Execution Pattern:** The shift from `send_and_wait` to `session.on()` + `assistant.turn_end` detection is correct and shows understanding of timeout behavior.

---

### Issues

#### Critical (Must Address Before Implementation)

**1. Missing EventBus Implementation Plan**
- **Section:** Event bridge (lines 230-295), SwarmOrchestrator data flow
- **Problem:** Plan references `EventBus` extensively (`event_bus.emit`, `event_bus.emit_sync`) but Phase 2 has no "2f. EventBus" task. The event bridge calls `ws_manager.broadcast()` directly, but SwarmAgent expects `self.event_bus.emit_sync()`.
- **Why it matters:** Without a clear EventBus abstraction, Phase 2 tests won't know what to assert against.
- **Fix:** Add Phase 2 task "2f. EventBus" with TDD cycle testing both `emit` and `emit_sync`. Clarify in Phase 3: "3b. Wire EventBus to WebSocket."

**2. Tool Closure Pattern Untested**
- **Section:** Phase 2a, tools.py code example
- **Problem:** "Test calling `task_update` tool handler mutates a real TaskBoard instance" doesn't specify how to test closure capture. Closure bugs (e.g., capturing loop variables incorrectly) are common and silent.
- **Fix:** Expand Phase 2a test spec: show that the test invokes `tools[0].handler(params, mock_invocation)` directly and asserts `TaskBoard.update_status` was called with correct args.

**3. Leader Session Has No Tools Defined**
- **Section:** Architecture diagram, Phase 2d orchestrator
- **Problem:** Line 24 says "leader agent gets its own session (no swarm tools, just planning)" but Phase 2d assumes the leader populates the TaskBoard. If no tools, orchestrator must parse JSON from text — fragile if malformed.
- **Fix:** Clarify leader interaction model:
  - **Option A:** Leader has a `create_task` tool — update line 24
  - **Option B:** Leader returns JSON in text, orchestrator parses — add test for malformed JSON and add Risk entry

**4. `agent` Parameter Not Verified in CustomAgentConfig**
- **Section:** Worker session creation (lines 153-170)
- **Problem:** Plan uses `agent=agent_name` in `create_session()` to pre-select agent, but this parameter's validity against the actual Python SDK hasn't been confirmed.
- **Fix:** Add Phase 2b verification step: check `client.create_session(agent="name", custom_agents=[...])` is valid in client.py. Fallback: use `session.rpc.agent.select(agent_name)` immediately after creation.

---

#### Important (Should Address)

**5. Swarm Tool Return Types Inconsistent**
- **Section:** tools.py code example
- **Problem:** All 4 swarm tools return `json.dumps({"ok": True})`. Does `inbox_receive` return message content? Or just `{"ok": True}`?
- **Fix:** Define tool schemas showing response shapes. Test `inbox_receive` returns `{"messages": [...]}` not just `{"ok": true}`.

**6. No Migration Guide from Research Notebook**
- **Section:** Key Reference Files
- **Problem:** Plan references the notebook as "original swarm pattern to port" but never maps notebook functions to plan modules.
- **Fix:** Add "Phase 0: Research Review" — document the 4 OpenAI function tools from the notebook, extract leader/worker prompt templates, deliver `research/PORT-GUIDE.md`.

**7. WebSocket Reconnection State Resync Underspecified**
- **Section:** Phase 5 polish
- **Problem:** "Reconnection with full state resync" doesn't specify payload shape, merge strategy, or event ordering guarantees.
- **Fix:** Add to Phase 3b: define resync payload `{tasks, agents, phase, latest_event_id?}` and explicitly document merge strategy ("Full replace on resync; accept in-flight delta loss").

**8. Concurrent Task Execution Not Load-Balanced**
- **Section:** Phase 2d orchestrator
- **Problem:** `asyncio.gather` for all tasks simultaneously doesn't handle 10 tasks with 3 workers (static vs dynamic dispatch unspecified).
- **Fix:** Clarify in Phase 2d: "MVP = round-based static assignment. Phase 5 = dynamic task queue with pull-based workers."

---

#### Minor (Consider)

**9.** No Python version requirement stated. Plan uses `match` (3.10+) and modern type hints (3.9+). Add requirement to config.

**10.** Frontend scaffold command not specified. Use `npm create vite@latest frontend -- --template react-ts` for consistency.

**11.** `templates.py` listed in Phase 1 structure but template TDD is Phase 5. Either defer file creation or define templates as JSON data files.

**12.** Phase 2e CLI smoke test is manual. Make it semi-automated: assert at least 1 `task.created` event and a final `swarm.complete` event, no `swarm.error`.

---

### Recommendations

1. **Add dependency graph clarity:** Document how `depends_on` is expressed in task dicts and test that `get_runnable_tasks` excludes blocked tasks.
2. **Security — tool permissions:** `skip_permission=True` on all swarm tools. Add Risk: "Prompt injection abuses inbox/task tools." Mitigation: "Tools validate sender matches session's agent_name from closure."
3. **Error recovery:** Agent crash mid-task is unspecified. Add to Phase 2d: test agent failure → task marked "failed" → orchestrator continues with remaining tasks.
4. **Integration test layer:** Add Phase 2.5 integration test against real copilot-cli subprocess to verify actual event shapes match expectations.

---

### Assessment

**Implementable as written?** With fixes

**Reasoning:** The architecture is sound and well-researched, but 4 critical gaps (EventBus abstraction, leader tool vs JSON parsing model, tool closure test patterns, `agent` parameter validation) would cause confusion during implementation. Resolving these and adding the notebook port guide would make this highly implementable.
