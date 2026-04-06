# Chat UX Parity + After-Action Report Upgrade — COMPLETED

## What Was Done

### Phase 1: Unified Tool Event Stream (Backend)
- **`bridge_raw_sdk_event()`** in `event_bridge.py` — single bridge for ALL SDK tool events with `input`, `output`, `error` fields
- Orchestrator `chat()`, `qa_chat()`, and `start_qa()` all use unified bridge via `_forward_chat_sdk_event()`
- Eliminated `leader.chat_tool_start/result` — replaced by `agent.tool_call/result` with `message_id` discriminator
- Agent worker SDK events now bridged and broadcast via WebSocket (were dropped)
- Fixed bug: `qa_chat._on_event` had NO tool forwarding; `start_qa._on_init_event` also missing

### Phase 2: Chat Timeline with Tool Grouping (Frontend)
- `ChatEntry` union type (`message | tool_group | streaming`) replaces flat `messages[] + activeTools[]`
- Chat reducer rewritten — tools group naturally between messages
- `ToolGroup.tsx` — collapsible tool groups with status icons, input preview, duration, error display
- `ChatPanel.tsx` — renders timeline inline (message → tool group → message)

### Phase 3: After-Action Report Upgrade (Frontend)
- `TaskPillBar.tsx` — colored status pills for tasks
- `TaskDetailDrawer.tsx` — expandable task details with Prompt/Result sections
- `ReportRightPanel.tsx` — composed right panel (task pills + drawer + chat)
- `ArtifactList` moved to left panel above report content

### Phase 4: Postgres Hard Requirement + DB Fallback
- `DATABASE_URL` now required — server fails fast if not set
- Removed `if _repository` / `if self._repo` guards throughout
- `/api/swarm/{id}/status` falls back to DB when swarm not in `swarm_store`, backfills cache
- Frontend hydrates tasks from `/status` response via `hydrateTasksIntoSwarm()` utility

## Test Coverage
- Backend: 456 tests
- Frontend: 182 tests (17 test files)
- Zero regressions

## Files Modified (Backend)
- `src/backend/swarm/event_bridge.py` — `bridge_raw_sdk_event()`, `_summarize_args()`, `_truncate()`
- `src/backend/swarm/orchestrator.py` — unified bridge, `_forward_chat_sdk_event()`
- `src/backend/swarm/agent.py` — `swarm_id` in sdk_event emission
- `src/backend/main.py` — bridge wiring, Postgres required
- `src/backend/api/rest.py` — DB fallback in `/status`, removed None guards
- `src/backend/services/swarm_service.py` — removed repo None guards
- `src/backend/mcp/server.py` — removed repo None guard

## Files Modified/Created (Frontend)
- `src/frontend/src/types/swarm.ts` — ActiveTool expanded, ChatEntry union, ChatState
- `src/frontend/src/hooks/useChatState.ts` — timeline reducer
- `src/frontend/src/hooks/useSwarmState.ts` — rich tool fields
- `src/frontend/src/components/ToolGroup.tsx` — new
- `src/frontend/src/components/ChatPanel.tsx` — timeline rendering
- `src/frontend/src/components/TaskPillBar.tsx` — new
- `src/frontend/src/components/TaskDetailDrawer.tsx` — new
- `src/frontend/src/components/ReportRightPanel.tsx` — new
- `src/frontend/src/utils/hydrateTasksIntoSwarm.ts` — new
- `src/frontend/src/App.tsx` — event dispatch, layout, task hydration
- `src/frontend/src/App.css` — all new component styles

## Remaining (moved to backlog)
- Mermaid diagram toggle control (View Source / Rendered) — see `planning/backlog/mermaid-toggle.md`
- SwarmContext provider, ViewRouter, extracted view components (architecture refactor)
