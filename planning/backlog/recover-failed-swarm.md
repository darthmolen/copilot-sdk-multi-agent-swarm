# Failed Task Recovery: Retry / Troubleshoot

## Context

When an agent fails (circuit breaker, tool errors, timeout), its task card sits as FAILED and all dependents stay BLOCKED forever. The user has no recourse except restarting the entire swarm. We need two recovery options on failed task cards.

**Prerequisite:** Requires the persistence layer from `live-chat-swarm-awareness.md` — without Postgres-backed state, we can't reliably recover swarm state after restarts or resume agent sessions.

**Decisions made:**
- Troubleshoot uses the SAME resumed agent session (preserves full context)
- After recovery, re-evaluate the entire task board (unblock dependents, continue execution)

## Part 1: Failed Task Card Actions (Frontend)

### UI Changes

On the task board, FAILED task cards get two action buttons:

**Retry** (dumb resume)
- Resumes the agent's session where it left off
- Sends a nudge: "Your previous attempt failed. Please try a different approach."
- Task resets to IN_PROGRESS
- Dashboard stays visible so user watches progress

**Troubleshoot** (smart resume)
- Switches to report view with Refinement Chat
- Injects failure context into the chat: tool errors, turn count, last error message
- User can converse with the agent to diagnose and guide it
- Once resolved, user clicks "Continue" → task completes → switch back to dashboard
- Board re-evaluates: dependents unblock, execution resumes

### Frontend Files

- `src/frontend/src/components/TaskBoard.tsx` — Retry/Troubleshoot buttons on FAILED cards
- Retry: POST `/api/swarm/{id}/task/{taskId}/retry`
- Troubleshoot: POST `/api/swarm/{id}/task/{taskId}/troubleshoot`, then `setReportSwarmId(swarmId)`

## Part 2: Backend — Session Resume + Task Recovery

### Agent Session ID Capture

- `src/backend/swarm/agent.py` — Store `self.session_id = self.session.session_id` after `create_session()`

### New REST Endpoints

`POST /api/swarm/{swarm_id}/task/{task_id}/retry`
1. Get orchestrator from `swarm_store`
2. Get agent for the failed task
3. Reset task to IN_PROGRESS via `task_board.update_status(task_id, "in_progress")`
4. Resume agent session: `client.resume_session(agent.session_id, ...)`
5. Send nudge prompt: "Previous attempt failed with: {error}. Try a different approach."
6. Wait for completion (same `execute_task` pattern with event handler)
7. On completion: re-evaluate board via `_continue_execution()`

`POST /api/swarm/{swarm_id}/task/{task_id}/troubleshoot`
1. Get orchestrator + agent
2. Reset task to IN_PROGRESS
3. Resume agent session
4. Inject failure context as first chat message via `leader.chat_delta` events
5. Set swarm phase to `'troubleshooting'` (new phase)
6. Route subsequent chat messages to this agent's session (like QA chat)
7. When user signals "continue" → agent finishes task → re-evaluate board

### Board Re-evaluation

New method on orchestrator: `async def _continue_execution()`
- Called after a retry/troubleshoot task completes
- Runs `get_runnable_tasks()` — newly unblocked tasks now appear as PENDING
- Executes another round of `_execute()` to process them
- If no more runnable tasks, proceeds to synthesis

### Task Board Transitions

- `update_status()` already supports any status transition
- On COMPLETED: auto-calls `_resolve_dependencies()` which unblocks dependents
- No task board changes needed

## Dependencies

- **Persistence layer** (Postgres) — session state must survive restarts
- **Event log** — need tool failure history to inject into troubleshoot context
- **Agent session_id capture** — needed for `client.resume_session()`

## Files To Modify (When Ready)

| File | What |
| ---- | ---- |
| `src/backend/swarm/agent.py` | Capture `session_id` |
| `src/backend/api/rest.py` | Retry + troubleshoot endpoints |
| `src/backend/swarm/orchestrator.py` | `_continue_execution()`, retry/troubleshoot orchestration |
| `src/frontend/src/components/TaskBoard.tsx` | Retry/Troubleshoot buttons on FAILED cards |
| `src/frontend/src/types/swarm.ts` | Add `'troubleshooting'` to SwarmPhase |
