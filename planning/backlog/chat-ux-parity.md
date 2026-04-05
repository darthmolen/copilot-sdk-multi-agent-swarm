# Chat UX Parity + After-Action Report Upgrade

Use test-driven-development and using-superpowers skills to batch and parallel the work. Any python work needs to use python-quality-developer skill.

## Context

The chat experience in the swarm web app is far behind the VSCode extension it emulates. Tools show only IDs, arrive out of order, agent messages duplicate, and there's no tool grouping. The after-action report also needs task details surfaced.

**Reference implementation:** `research/vscode-extension-copilot-cli/` — specifically:
- `src/webview/app/components/ToolExecution/ToolExecution.js` — tool grouping + display
- `src/webview/app/components/MessageDisplay/MessageDisplay.js` — message + delta rendering
- `src/shared/models.ts` — ToolState with name, status, input, output, error

## Phase 1: Chat Fix (shared component for QA, after-action, and intervention)

### Problem Summary

1. **Tools show only ID** — `ActiveTool` has `toolCallId` and `toolName` but no input/output/error. ToolCard shows the ID, which is useless.
2. **Wrong ordering** — tools pile in above the agent message. Agent says something, then tools appear above it retroactively.
3. **Agent messages duplicate** — both streaming and final message divs update simultaneously.
4. **No tool grouping** — tools show as flat list, not collapsed groups.
5. **Deltas not chunked intelligently** — streaming markdown can break mid-structure.

### Solution: New chat message model + ToolGroup component

#### Data Model Changes

**File:** `src/frontend/src/types/swarm.ts`

Expand `ActiveTool` to match the extension's `ToolState`:

```typescript
interface ActiveTool {
  toolCallId: string;
  toolName: string;
  agentName?: string;
  status: 'running' | 'complete' | 'failed';
  input?: string;      // NEW: tool arguments summary
  output?: string;     // NEW: tool result text
  error?: string;      // NEW: error message if failed
  startedAt?: number;  // NEW: for duration display
  completedAt?: number;
}
```

Introduce `ChatEntry` — a union type that represents the chat timeline:

```typescript
type ChatEntry =
  | { type: 'message'; message: ChatMessage }
  | { type: 'tool_group'; tools: ActiveTool[] }
  | { type: 'streaming'; content: string };
```

#### Reducer Changes

**File:** `src/frontend/src/hooks/useChatState.ts`

Rewrite to produce `ChatEntry[]` timeline instead of separate `messages` + `activeTools`:

- `chat.tool_start` → if last entry is a `tool_group`, append to it. If last entry is a `message` or no entries, create new `tool_group`.
- `chat.tool_result` → update tool in its group, add output/error.
- `chat.message` → push new `message` entry. This **closes** the current tool group (any subsequent tools start a new group).
- `chat.delta` → update the single `streaming` entry (or create it).

This naturally produces the grouping: `[message, tool_group, message, tool_group, ...]`

#### Backend: Surface richer tool events

**File:** `src/backend/swarm/orchestrator.py` — the chat method

The backend already receives `tool.execution_start` and `tool.execution_complete` SDK events. Currently it emits:
- `leader.chat_tool_start` with `{tool_name, tool_call_id}`
- `leader.chat_tool_result` with `{tool_call_id, success}`

Need to also emit:
- `tool_input` (arguments) from `tool.execution_start` data
- `tool_output` / `tool_error` from `tool.execution_complete` data

Check what data the SDK events actually carry and forward it.

#### Component Changes

**New file:** `src/frontend/src/components/ToolGroup.tsx`

Renders a collapsible group of tools. Mirrors extension's `ToolExecution.js`:
- Header: status icon + count ("3 tools") + expand/collapse toggle
- Collapsed: shows tool names as comma-separated list
- Expanded: each tool shows name, status icon, input preview, output/error
- Auto-collapse after 2+ tools in the group
- Last tool in group stays expanded if running

**File:** `src/frontend/src/components/ChatPanel.tsx`

Replace flat rendering with `ChatEntry[]` timeline:

```tsx
{entries.map(entry => {
  if (entry.type === 'message') return <MessageBubble ... />;
  if (entry.type === 'tool_group') return <ToolGroup tools={entry.tools} />;
  if (entry.type === 'streaming') return <StreamingBubble ... />;
})}
```

**File:** `src/frontend/src/components/StreamingMarkdown.tsx`

Improve chunking — flush at paragraph breaks, completed code fences, headings. Match extension's progressive rendering approach.

---

## Phase 2: After-Action Report Upgrade

### New Layout (all views)

**QA View:**

```
Left:  [file pills] + artifact/report view
Right: chat only (no tasks)
```

**Report View (after-action):**

```
Left:  [file pills] + artifact/report view
Right: [task pills: worker:TaskName completed/pending/failed/timeout] + collapsible task drawer + chat
Bottom (if suspended): [Save & Retry]
```

**Intervention View:**

```
Left:  template editor panel
Right: [task pills] + resizable(logs top / chat bottom)
Bottom: [Save & Retry]
```

#### Task Pills

**New file:** `src/frontend/src/components/TaskPillBar.tsx`

```typescript
interface TaskPillBarProps {
  tasks: Task[];
  selectedTaskId: string | null;
  onSelect: (taskId: string) => void;
}
```

- Pill format: `{workerName}:{subject}` (truncated)
- Colors: green (#22c55e) completed, amber (#f59e0b) pending/blocked, red (#ef4444) failed, gray (#6b7280) timeout
- Click toggles a detail drawer below

#### Task Detail Drawer

**New file:** `src/frontend/src/components/TaskDetailDrawer.tsx`

Expandable panel below the task pills showing:
- Subject, description, worker name/role
- Status badge
- Result text (scrollable, monospace for code)
- Collapsible — click pill again to close

#### Layout Changes

**File:** `src/frontend/src/App.tsx` — report view right panel

```tsx
<div className="right-panel">
  <ArtifactList ... />                    {/* stays */}
  <TaskPillBar                            {/* NEW */}
    tasks={swarmTasks}
    selectedTaskId={selectedTaskId}
    onSelect={setSelectedTaskId}
  />
  {selectedTaskId && (                    {/* NEW */}
    <TaskDetailDrawer task={selectedTask} onClose={() => setSelectedTaskId(null)} />
  )}
  <ChatPanel ... />                       {/* stays, flex: 1 */}
</div>
```

Need task data in the report view — currently tasks are only in the dashboard reducer. For completed swarms loaded from DB, fetch tasks via `/api/swarm/{id}/status`.

---

## React Architecture (from react-specialist review)

**Core principle:** 3 explicit view components composing shared pieces — not one universal layout with boolean flags.

### SwarmContext Provider (new)

Extract state from the God Component (`App.tsx` / `SwarmDashboard`) into a context:

```typescript
// context/SwarmContext.tsx
SwarmContext provides:
  store, swarmDispatch        // multiSwarmReducer
  chatStore, chatDispatch     // chatReducer
  reportSwarmId / setReportSwarmId
  interventionTaskId / setInterventionTaskId
  handleSwarmEvent, handleSendChat, handleStartSwarm, handleResumeSwarm
```

### Shared Components

| Component | Used by | Description |
| --------- | ------- | ----------- |
| `ChatPanel` | QA, Report, Intervention | Pure props, no context access |
| `ArtifactPanel` | QA, Report | ArtifactList + ReportContent |
| `TaskPills` | Report, Intervention | Colored task pills |
| `RightPanel` | Report, Intervention | Slot-props stacker: pills -> middle -> chat -> footer |
| `AppHeader` | All views | Back button + title + action slots |
| `SaveRetryBar` | Report (conditional), Intervention | Footer button |

### View Components (new)

| View | Left Panel | Right Panel |
| ---- | ---------- | ----------- |
| `QAView` | ArtifactPanel | ChatPanel (standalone) |
| `ReportView` | ArtifactPanel | RightPanel(TaskPills + TaskDetailDrawer + ChatPanel) |
| `InterventionView` | TemplateEditorPanel | RightPanel(TaskPills + ResizableVertical(Logs, Chat)) |
| `DashboardView` | -- | Controls, agents, tasks, inbox |

### ViewRouter (replaces if/else chain in App.tsx)

Reads context state to pick active view. ~20 lines.

### Implementation Order (incremental, each step independently deployable)

1. Extract `SwarmContext` — wrap existing internals, no behavior change
2. Extract `useArtifacts` hook — pull fetch/select logic
3. Extract `AppHeader` — presentational
4. Build `ViewRouter` — replace if/else
5. Build `QAView` — simplest (artifacts + chat)
6. Build `ReportView` — add TaskPills, TaskDetailDrawer
7. Adapt `InterventionView` — read from context
8. Build `DashboardView` — extract dashboard JSX
9. Slim `App.tsx` to ~20 lines

---

## Execution: TDD Red-Green-Refactor with Parallel Batching

### Batch 1 (3 parallel agents)

#### Agent A: Backend — richer tool events

**RED:**
- `test_chat_tool_start_includes_input()` — tool_start event carries tool arguments
- `test_chat_tool_result_includes_output()` — tool_result event carries tool output/error

**GREEN:** Update chat method in orchestrator to forward tool input/output from SDK events.

**Files:** `orchestrator.py`, `test_orchestrator.py`

#### Agent B: Frontend — ChatEntry model + reducer rewrite

**RED/GREEN:** Rewrite `useChatState.ts`:
- New `ChatEntry` union type
- Reducer produces timeline with tool grouping
- `chat.tool_start` appends to or creates tool_group
- `chat.message` closes current tool_group

**Files:** `types/swarm.ts`, `useChatState.ts`

#### Agent C: Frontend — ToolGroup component

Build `ToolGroup.tsx`:
- Collapsible tool group with expand/collapse
- Shows tool name, status icon, input preview, output/error
- Auto-collapse after 2+ tools
- CSS matching dark theme

**Files:** `ToolGroup.tsx`, `App.css`

### Batch 2 (2 parallel agents)

#### Agent D: Frontend — ChatPanel rewrite + StreamingMarkdown fix

- Rewrite ChatPanel to render `ChatEntry[]` timeline
- Fix message ordering (tools inline with messages, not above)
- Fix duplicate message divs
- Improve StreamingMarkdown chunking

**Files:** `ChatPanel.tsx`, `StreamingMarkdown.tsx`

#### Agent E: Frontend — TaskPillBar + TaskDetailDrawer + report layout

- TaskPillBar component with colored pills
- TaskDetailDrawer with expandable result view
- Wire into App.tsx report view right panel
- Fetch tasks for completed swarms via `/status`

**Files:** `TaskPillBar.tsx`, `TaskDetailDrawer.tsx`, `App.tsx`, `App.css`

---

## Verification

1. **Tool display:** Start swarm, verify tools show name + input, not just ID
2. **Tool grouping:** Tools between agent messages group and collapse
3. **Message ordering:** Agent text appears, then tools below it, then next message
4. **No duplicates:** Streaming delta replaces cleanly with final message
5. **After-action tasks:** Report view shows task pills with colors, click expands details
6. **Shared component:** ChatPanel works in QA, after-action, and intervention views

## Files Modified

| File | Change |
| ---- | ------ |
| `src/backend/swarm/orchestrator.py` | Forward tool input/output in chat events |
| `src/frontend/src/types/swarm.ts` | Expand ActiveTool, add ChatEntry |
| `src/frontend/src/hooks/useChatState.ts` | Rewrite reducer for ChatEntry timeline |
| `src/frontend/src/components/ToolGroup.tsx` | New: collapsible tool group |
| `src/frontend/src/components/ChatPanel.tsx` | Rewrite for ChatEntry timeline |
| `src/frontend/src/components/StreamingMarkdown.tsx` | Better chunking |
| `src/frontend/src/components/TaskPillBar.tsx` | New: task pills for report |
| `src/frontend/src/components/TaskDetailDrawer.tsx` | New: expandable task details |
| `src/frontend/src/App.tsx` | Wire task pills into report view |
| `src/frontend/src/App.css` | Styles for ToolGroup, TaskPills, TaskDrawer |
