# Fix Duplicate WS Events from React Strict Mode

## Context

React 18 Strict Mode double-invokes effects in development: mount → unmount → remount. The `useWebSocket` hook creates a WS connection on mount, but `ws.close()` is async — by the time it actually closes, React has already remounted and created a second WS. The backend's `ConnectionManager` now has TWO connections for the same `swarm_id`, so every `broadcast()` delivers the event twice. This causes duplicate `task.created`, `agent.spawned`, etc., which the append-based reducer turns into duplicate cards.

**Evidence:** Browser console shows `doubleInvokeEffectsOnFiber` in the stack trace of the "WebSocket is closed before the connection is established" warning. This confirms React Strict Mode is the trigger.

## Client side errors

```text
useWebSocket.ts:29 WebSocket connection to 'ws://localhost:5173/ws/8424fa83-f720-4d69-81b1-20553464141f' failed: WebSocket is closed before the connection is established.
(anonymous) @ useWebSocket.ts:29
(anonymous) @ useWebSocket.ts:85
react_stack_bottom_frame @ react-dom-client.development.js:26001
runWithFiberInDEV @ react-dom-client.development.js:871
commitHookEffectListUnmount @ react-dom-client.development.js:13316
commitHookPassiveUnmountEffects @ react-dom-client.development.js:13347
disconnectPassiveEffect @ react-dom-client.development.js:16216
doubleInvokeEffectsOnFiber @ react-dom-client.development.js:18701
runWithFiberInDEV @ react-dom-client.development.js:871
recursivelyTraverseAndDoubleInvokeEffectsInDEV @ react-dom-client.development.js:18667
recursivelyTraverseAndDoubleInvokeEffectsInDEV @ react-dom-client.development.js:18673
recursivelyTraverseAndDoubleInvokeEffectsInDEV @ react-dom-client.development.js:18673
recursivelyTraverseAndDoubleInvokeEffectsInDEV @ react-dom-client.development.js:18673
recursivelyTraverseAndDoubleInvokeEffectsInDEV @ react-dom-client.development.js:18673
commitDoubleInvokeEffectsInDEV @ react-dom-client.development.js:18712
flushPassiveEffects @ react-dom-client.development.js:18439
(anonymous) @ react-dom-client.development.js:17923
performWorkUntilDeadline @ scheduler.development.js:45
<SwarmConnection>
exports.jsxDEV @ react-jsx-dev-runtime.development.js:335
(anonymous) @ App.tsx:102
App @ App.tsx:101
react_stack_bottom_frame @ react-dom-client.development.js:25904
renderWithHooksAgain @ react-dom-client.development.js:7762
renderWithHooks @ react-dom-client.development.js:7674
updateFunctionComponent @ react-dom-client.development.js:10166
beginWork @ react-dom-client.development.js:11778
runWithFiberInDEV @ react-dom-client.development.js:871
performUnitOfWork @ react-dom-client.development.js:17641
workLoopSync @ react-dom-client.development.js:17469
renderRootSync @ react-dom-client.development.js:17450
performWorkOnRoot @ react-dom-client.development.js:16504
performWorkOnRootViaSchedulerTask @ react-dom-client.development.js:18957
performWorkUntilDeadline @ scheduler.development.js:45
<App>
exports.jsxDEV @ react-jsx-dev-runtime.development.js:335
(anonymous) @ main.tsx:8

useWebSocket.ts:29 WebSocket connection to 'ws://localhost:5173/ws/b32e90cd-35c6-4bc5-8708-ac60a9a54213' failed: WebSocket is closed before the connection is established.
```

## Root Cause

`useWebSocket.ts` cleanup calls `ws.close()` which is async. The backend receives WS #2 before WS #1's TCP close completes, so `ConnectionManager._connections[swarmId]` has `[ws1, ws2]` briefly (or permanently if ws1 close never propagates cleanly).

## Fix

### Approach: Stale connection guard + backend dedup

Two layers of defense:

### Layer 1: Frontend — ignore events from stale connections

In `useWebSocket.ts`, use a local `active` boolean that tracks whether the current effect invocation is still active. When Strict Mode unmounts, the cleanup sets `active = false`. The `onmessage` handler checks `active` before dispatching — stale WS connections silently drop their events.

**File:** `src/frontend/src/hooks/useWebSocket.ts`

```typescript
useEffect(() => {
  if (!swarmId) return;

  // Guard against stale connections from Strict Mode double-invoke
  let active = true;

  function connect() {
    const url = `${WS_BASE}/ws/${swarmId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!active) { ws.close(); return; }
      setConnected(true);
      reconnectDelay.current = INITIAL_RECONNECT_DELAY;
    };

    ws.onmessage = (evt) => {
      if (!active) return; // Drop events from stale connection
      try {
        const event: SwarmEvent = JSON.parse(evt.data);
        onEventRef.current(event);
      } catch { /* ignore */ }
    };

    ws.onclose = () => {
      if (!active) return; // Don't reconnect from stale connection
      setConnected(false);
      if (!shouldReconnect.current) return;
      reconnectTimer.current = setTimeout(() => {
        reconnectDelay.current = Math.min(
          reconnectDelay.current * 2,
          MAX_RECONNECT_DELAY,
        );
        if (active) connect();
      }, reconnectDelay.current);
    };

    ws.onerror = () => { ws.close(); };
  }

  shouldReconnect.current = true;
  connect();

  return () => {
    active = false; // Mark this effect invocation as stale
    shouldReconnect.current = false;
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setConnected(false);
  };
}, [swarmId]);
```

Key change: The `active` boolean is local to each effect invocation. When Strict Mode unmounts, `active = false` for that invocation. When remounted, a new `active = true` is created. The stale WS #1's `onmessage`/`onclose` handlers check `active` and silently no-op.

Also: remove `disconnect` from the dependency array — it's a `useCallback` that never changes, but including it in deps is unnecessary and could theoretically cause extra effect runs.

### Layer 2: Backend — limit one WS per swarm_id (optional hardening)

In `ConnectionManager.connect()`, close any existing connections for the same `swarm_id` before adding the new one. This ensures at most one active WS per swarm.

**File:** `src/backend/api/websocket.py`

```python
async def connect(self, websocket: WebSocket, swarm_id: str) -> None:
    await websocket.accept()
    # Close stale connections for this swarm_id
    for old_ws in self._connections.get(swarm_id, []):
        try:
            await old_ws.close()
        except Exception:
            pass
    self._connections[swarm_id] = [websocket]
```

This is belt-and-suspenders — the frontend fix alone should be sufficient, but the backend limit prevents any future source of duplicate connections.

## Files to Modify

| File                                        | Change                                       |
|---------------------------------------------|----------------------------------------------|
| `src/frontend/src/hooks/useWebSocket.ts`    | Add `active` guard, remove `disconnect` dep  |
| `src/backend/api/websocket.py`              | Limit one WS per swarm_id (optional)         |

## TDD

- **RED:** Test that `onmessage` after cleanup doesn't dispatch
- **GREEN:** Add `active` guard
- Frontend test: dispatch mock WS events, verify no duplicates after cleanup

## Verification

1. Frontend tests pass (vitest, 28+)
2. Backend tests pass (pytest, 171+)
3. Manual: Open browser dev tools console, start 2 swarms simultaneously
   - No "two children with same key" warnings
   - No duplicate task/agent cards
   - Strict Mode double-mount warning still appears (expected) but events aren't duplicated

---

## Plan Review Feedback

> Reviewed by: plan-reviewer subagent — 2026-03-25

### Strengths

1. **Root Cause Analysis is Excellent**: Correctly identifies React 18 Strict Mode's double-invoke behavior and the async `ws.close()` race condition. The stack trace evidence (`doubleInvokeEffectsOnFiber`) is solid proof.
2. **Defense-in-Depth Approach**: Two-layer fix is architecturally sound in intent.
3. **Specific Code Examples**: Complete TypeScript/Python snippets with comments explaining the `active` flag mechanism.
4. **Verification Strategy**: Automated + manual testing with clear success criteria.
5. **TDD Structure**: Follows RED-GREEN pattern.
6. **Files Exist and Are Compatible**: Both `useWebSocket.ts` and `websocket.py` exist and are compatible with the proposed changes.

---

### Issues

#### Critical (Must Address Before Implementation)

None. The plan is fundamentally sound and implementable as written.

---

#### Important (Should Address)

**Issue 1 — Missing `disconnect` Dependency Removal Context**
- **Section:** Layer 1 Frontend, deps array
- **Problem:** The plan says to remove `disconnect` from deps but doesn't explain why it's safe. The current code has `[swarmId, disconnect]`.
- **Why it matters:** Implementer may question this without context.
- **Fix:** Add a sentence: "The `disconnect` callback is stable (empty dependency array in its `useCallback`, line 22), so including it is unnecessary."

**Issue 2 — Backend Layer 2 Breaks Multi-Client Support** ⚠️
- **Section:** Layer 2: Backend
- **Problem:** Closing *all* existing connections for a swarm_id when a new client connects breaks legitimate multi-tab/multi-viewer scenarios.
- **Evidence:** `_connections` stores a `list` per swarm_id, and `broadcast()` iterates all of them — the system is explicitly designed for multiple observers.
- **Impact:** Opening a second browser tab to the same swarm would close the first tab's connection. This is a regression.
- **Fix:** **Remove Layer 2 entirely.** The plan itself says "the frontend fix alone should be sufficient" (line 153). If backend hardening is ever needed in the future, use per-client connection IDs rather than closing all connections.

**Issue 3 — TDD Section is Incomplete**
- **Section:** TDD (lines 163-166)
- **Problem:** "dispatch mock WS events, verify no duplicates after cleanup" is too vague. Doesn't specify how to simulate Strict Mode's double-invoke, or what "cleanup" means in test context.
- **Fix:** Expand with a pseudocode outline:
  ```typescript
  // 1. renderHook(() => useWebSocket(swarmId, onEvent))
  // 2. Get ws mock instance (ws1)
  // 3. unmount() — cleanup runs, active = false
  // 4. Trigger ws1.onmessage with mock event
  // 5. Assert: onEvent NOT called
  ```

**Issue 4 — No Frontend Test File Specified**
- **Section:** Verification (line 170)
- **Problem:** Plan references "28+ frontend tests" but there is no existing `useWebSocket.test.ts`. Only `swarmReducer.test.ts` exists.
- **Fix:** Add to "Files to Modify" table:
  - `src/frontend/src/hooks/__tests__/useWebSocket.test.ts` — **Create** with Strict Mode double-invoke test.

---

#### Minor (Consider)

**Issue 5 — "Optional" Layer 2 Messaging is Contradictory**
- The plan calls Layer 2 "optional hardening" then also "belt-and-suspenders." Mixed messaging. Either move it to a "Future Hardening" section or remove it.

**Issue 6 — Manual Verification Step is Ambiguous**
- "Start 2 swarms simultaneously" tests multi-swarm isolation (already covered by reducer tests), not the Strict Mode fix. Clarify: test ONE swarm, observe in dev tools that Strict Mode triggers mount→unmount→remount, no duplicate cards.

---

### Recommendations

1. **Remove Backend Layer 2** — breaks multi-client support, not needed.
2. **Expand TDD section** with concrete test pattern for Strict Mode double-invoke.
3. **Add `useWebSocket.test.ts`** to Files to Modify table.
4. **Clarify manual testing** to focus on single-swarm Strict Mode behavior.
5. **Add one sentence** explaining why `disconnect` is safe to remove from deps.

---

### Assessment

**Implementable as written?** Yes, with Layer 2 removed.

**Reasoning:** The frontend fix (Layer 1) is architecturally sound, solves the root cause, and is compatible with the existing codebase. Layer 2 would break multi-client support, which `ConnectionManager` is explicitly designed to provide. TDD and verification sections need minor clarifications but are not blockers.
