# Fix Duplicate WS Events from React Strict Mode

## Context

React 18 Strict Mode double-invokes effects in development: mount → unmount → remount. The `useWebSocket` hook creates a WS connection on mount, but `ws.close()` is async — by the time it actually closes, React has already remounted and created a second WS. The backend's `ConnectionManager` now has TWO connections for the same `swarm_id`, so every `broadcast()` delivers the event twice. This causes duplicate `task.created`, `agent.spawned`, etc., which the append-based reducer turns into duplicate cards.

**Evidence:** Browser console shows `doubleInvokeEffectsOnFiber` in the stack trace of the "WebSocket is closed before the connection is established" warning.

## Root Cause

`useWebSocket.ts` cleanup calls `ws.close()` which is async. The backend receives WS #2 before WS #1's TCP close completes, so `ConnectionManager._connections[swarmId]` has `[ws1, ws2]` briefly (or permanently if ws1 close never propagates cleanly).

## Fix: Frontend stale connection guard

In `useWebSocket.ts`, use a local `active` boolean scoped to each effect invocation. When Strict Mode unmounts, cleanup sets `active = false`. All WS handlers (`onopen`, `onmessage`, `onclose`) check `active` before acting — stale connections silently no-op.

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

Key changes:

- `active` boolean is local to each effect invocation — stale closures silently no-op
- `disconnect` removed from dependency array — it's defined with `useCallback(fn, [])` (empty deps, line 22) so it's referentially stable across renders. Including it was unnecessary.
- No backend changes needed — `ConnectionManager` is designed for multiple observers per swarm_id (multi-tab support). Restricting to one connection would break that.

## Files to Modify

| File | Change |
|------|--------|
| `src/frontend/src/hooks/useWebSocket.ts` | Add `active` guard, remove `disconnect` dep |
| `src/frontend/src/__tests__/useWebSocket.test.ts` | Create — test stale connection event dropping |

## TDD

**RED:** Test that onmessage after cleanup doesn't dispatch:

```typescript
// 1. renderHook(() => useWebSocket(swarmId, onEvent))
// 2. Get ws mock instance (ws1)
// 3. unmount() — cleanup runs, active = false
// 4. Trigger ws1.onmessage with mock event
// 5. Assert: onEvent NOT called
```

**RED:** Test that remount creates fresh connection that DOES dispatch:

```typescript
// 1. renderHook, unmount, remount (simulating Strict Mode)
// 2. Get ws2 mock instance
// 3. Trigger ws2.onmessage
// 4. Assert: onEvent called exactly once
```

**GREEN:** Implement `active` guard in useWebSocket.

## Verification

1. Frontend tests pass (vitest)
2. Backend tests pass (pytest, 171+)
3. Manual single-swarm test: Open dev tools, start ONE swarm, observe Strict Mode mount/unmount/remount in console — no duplicate cards, no "two children with same key" warnings
4. Manual multi-swarm test: Start two swarms simultaneously — each swarm's cards appear once with correct swarm_id labels, no cross-contamination
