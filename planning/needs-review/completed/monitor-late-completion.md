# Plan: Monitor timed-out tasks for late completion

## Context

When an agent task times out, the SDK session keeps running in the background and often completes its work. Currently the orchestrator marks the task "timeout", unsubscribes from events, and moves on — discarding work that finishes minutes later. The task board already allows `timeout → completed` transitions (no guards). We just need to keep listening.

## Design

After timeout, DON'T unsubscribe and DON'T return immediately from the background monitoring perspective. Instead:

1. Mark task as `timeout` (existing behavior)
2. Spawn a background coroutine that continues waiting on the same `done` event
3. The original `_handler` is still subscribed — it keeps accumulating `text_content` and `delta_parts`, and will set `done` when `session.idle` fires
4. When the background monitor sees `done` set, it updates the task from `timeout → completed` with captured content
5. Emits events so frontend updates the task card
6. Then unsubscribes

The `execute_task()` method still returns immediately after timeout (so `asyncio.gather` in `_execute()` can finish the round). The monitoring happens in the background.

## Implementation

### File: `src/backend/swarm/agent.py`

**Change `execute_task()`** — restructure the timeout handling:

```python
async def execute_task(self, task, *, timeout=DEFAULT_TIMEOUT_SECONDS):
    await self.task_board.update_status(task.id, "in_progress")
    done = asyncio.Event()
    error_holder = []
    text_content = []
    delta_parts = []

    def _handler(event):
        # ... existing handler (unchanged) ...

    unsubscribe = self.session.on(_handler)

    try:
        await self.session.send(task_prompt)
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await self.task_board.update_status(task.id, "timeout")
            # Keep monitoring — spawn background task, don't unsubscribe
            asyncio.create_task(self._monitor_late_completion(
                task, done, text_content, delta_parts, unsubscribe,
            ))
            return
        # ... normal completion handling (unchanged) ...
    finally:
        # Only unsubscribe on the normal path (not timeout)
        # Timeout path delegates unsubscribe to the monitor
        if not done.is_set() or task.status != TaskStatus.TIMEOUT:
            unsubscribe()
```

Wait — the finally block runs on BOTH paths. Need a flag:

```python
    monitoring = False
    try:
        await self.session.send(task_prompt)
        try:
            await asyncio.wait_for(done.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await self.task_board.update_status(task.id, "timeout")
            monitoring = True
            asyncio.create_task(self._monitor_late_completion(
                task, done, text_content, delta_parts, unsubscribe,
            ))
            return
        # ... normal completion ...
    finally:
        if not monitoring:
            unsubscribe()
```

**Add `_monitor_late_completion()` method:**

```python
async def _monitor_late_completion(
    self,
    task: Task,
    done: asyncio.Event,
    text_content: list[str],
    delta_parts: list[str],
    unsubscribe: Callable[[], None],
    monitor_timeout: float = 3600,
) -> None:
    """Background monitor: wait for a timed-out task's SDK session to complete."""
    try:
        await asyncio.wait_for(done.wait(), timeout=monitor_timeout)

        # Session completed — recover the work
        current_tasks = await self.task_board.get_tasks()
        current = next((t for t in current_tasks if t.id == task.id), None)
        if current and current.status == TaskStatus.TIMEOUT:
            result = (
                "\n".join(text_content) if text_content
                else "".join(delta_parts) if delta_parts
                else ""
            )
            await self.task_board.update_status(task.id, "completed", result)
            log.info("task_late_completed", task_id=task.id, agent=self.name,
                     result_len=len(result))
            if self.swarm_id:
                self.event_bus.emit_sync("task.updated", {
                    "task": current.to_dict(),
                    "swarm_id": self.swarm_id,
                })
    except asyncio.TimeoutError:
        log.info("monitor_expired", task_id=task.id, agent=self.name)
    finally:
        unsubscribe()
```

### Tests (TDD)

**File: `tests/unit/test_swarm_agent.py`**

- `test_timed_out_task_recovers_on_late_completion` — Create agent with short timeout (0.1s). Mock session that fires idle after 0.3s. Verify task goes from timeout → completed.
- `test_late_completion_captures_content` — Same setup but with content. Verify the result text is captured.
- `test_monitor_expires_without_completion` — Mock session that never fires idle. Verify monitor eventually gives up (use short monitor_timeout).

**File: `tests/unit/test_orchestrator.py`**

- `test_execute_continues_after_timeout` — Verify that _execute() finishes its round even when a task times out (existing behavior, just confirming no regression).

### Execution Order

| Step | Action | Files |
| ---- | ------ | ----- |
| 1 | Write failing tests | `tests/unit/test_swarm_agent.py` |
| 2 | Confirm RED | — |
| 3 | Implement _monitor_late_completion + restructure execute_task | `src/backend/swarm/agent.py` |
| 4 | Confirm GREEN | — |
| 5 | Full suite | `pytest tests/unit/ -v` |

## Verification

1. All tests pass
2. Run a focused prompt — workers complete normally, no monitoring needed
3. Run the bloated prompt overnight — if synthesis task times out, monitor recovers it
4. Check logs for `task_late_completed` events

## Critical Files

- `src/backend/swarm/agent.py` — execute_task restructure + _monitor_late_completion
- `tests/unit/test_swarm_agent.py` — late completion tests

---

## Plan Review

**Reviewed:** 2026-03-27 15:45
**Reviewer:** Claude Code (plan-review-intake)

### Strengths
1. Solves a real problem — verified that unsubscribe at agent.py:197 kills late completion recovery
2. Minimal surface area — scoped to agent.py only, no model/task board/orchestrator changes
3. Task board timeout→completed transition verified to work (no guards in update_status)
4. Monitoring flag approach is sound for all three paths (success, error, timeout)
5. TDD execution order matches project conventions

### Issues

#### Critical (Must Address Before Implementation)

**C1: agent.py has no structlog import.** Plan uses `log.info(...)` in `_monitor_late_completion` but agent.py has no `import structlog` or `log = structlog.get_logger()`. Will cause `NameError` at runtime.

**C3: Fire-and-forget `asyncio.create_task` leaks.** Task reference is never stored. If event loop shuts down, monitor is silently cancelled without cleanup. Store on `self._monitor_tasks` list, add `cancel_monitors()` method, handle `asyncio.CancelledError`.

**C4: Event emission uses stale task reference.** `current` fetched before `update_status()` — use return value of `update_status()` instead for the event.

#### Important (Should Address)

**I1: Late completion doesn't re-trigger execution loop.** `_resolve_dependencies` fires but `_execute()` may have already exited. Downstream blocked tasks won't run. Document as known limitation.

**I2: Thread safety of list appends.** Handler runs in SDK callback (potentially different thread), monitor reads lists from async context. GIL makes this safe in CPython but it's an implementation detail. Document the assumption.

**I3: Use `await self.event_bus.emit()` not `emit_sync()`.** Monitor is a coroutine on the event loop — `emit_sync` uses unnecessary `call_soon_threadsafe` indirection and may swallow exceptions.

**I4: Test plan underspecified.** Need concrete assertions: how to await background task, verify unsubscribe called, verify event emitted.

**I5: Missing cancellation test.** No test for monitor cleanup when event loop cancels during the 1-hour wait.

#### Minor (Consider)

**M1: Inconsistent path references** in plan text.
**M2: `monitor_timeout=3600` not configurable** from orchestrator config.
**M3: Self-correction narrative** ("Wait — the finally block...") should be removed from final plan.

### Recommendations
1. Add `import structlog` + `log = structlog.get_logger()` to agent.py (C1)
2. Store `asyncio.Task` on `self._monitor_tasks`, add `cancel_monitors()`, wire to orchestrator `cancel()` (C3)
3. Use `await self.event_bus.emit()` instead of `emit_sync()` in monitor (I3)
4. Use return value of `task_board.update_status()` for event emission (C4)
5. Add "Known Limitations" section re: downstream tasks (I1)
6. Expand test assertions and add cancellation test (I4, I5)

### Assessment
**Implementable as written?** With fixes
**Reasoning:** Core design is sound — background coroutine monitoring is the right pattern. Three items must be fixed first: missing structlog import (runtime crash), fire-and-forget task leak (silent monitor death), and emit_sync misuse in async context (swallowed exceptions).
