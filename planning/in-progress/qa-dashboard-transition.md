# QA→Dashboard Auto-Transition, Toast, Active Sessions in Sidebar

## Context

After QA completes and the leader calls `begin_swarm`, the user is stuck on the report view (empty left panel + stale QA chat). They have to manually click "← Dashboard" to see the task board, and once they do, the running session vanishes from the sidebar with no way back. The user wants the transition to feel seamless.

## Scope — 3 Changes

### A) Auto-navigate to dashboard when swarm kicks off

**File**: `src/frontend/src/App.tsx`

In `handleSwarmEvent` (line ~199), after the existing `phase === 'qa'` auto-switch block, add:

```typescript
if (event.type === 'swarm.phase_changed' && event.data.phase === 'planning') {
  setReportSwarmId(null);  // return to dashboard/kanban
}
```

Both `setReportSwarmId` (React setter) and `toast` (module import) are stable refs — no change to the `[]` deps array needed.

### B) Toast notification when swarm starts

**File**: `src/frontend/src/App.tsx`

Change line 2 from `import { Toaster } from 'react-hot-toast'` to:
```typescript
import toast, { Toaster } from 'react-hot-toast';
```

In the same planning phase block from (A):
```typescript
if (event.type === 'swarm.phase_changed' && event.data.phase === 'planning') {
  setReportSwarmId(null);
  toast('Swarm started! Watch progress on the task board.', { icon: '🚀', duration: 5000 });
}
```

Toast system is already wired — `<Toaster>` renders in App.tsx.

### C) Active sessions visible in sidebar

**Files**: `src/frontend/src/utils/buildReportList.ts`, `src/frontend/src/App.css`

**Naming**: Use `'running'` not `'active'` — `.report-list-item--active` already exists in CSS for the selected-item highlight (App.css:250).

Update `ReportStatus` type:
```typescript
export type ReportStatus = 'running' | 'generating' | 'live' | 'saved';
```

Rewrite the active swarms loop (lines 22-35) to include ALL active swarms:
```typescript
for (const id of activeSwarmIds) {
  const swarm = swarms[id];
  if (!swarm) continue;
  if (swarm.leaderReport && swarm.phase === 'synthesizing') {
    // existing: push as 'generating' with report title
    const firstLine = swarm.leaderReport.split('\n')[0].replace(/^#+\s*/, '');
    items.push({ swarmId: id, title: truncateTitle(firstLine), timestamp: Date.now(), status: 'generating' });
  } else {
    // NEW: any other active phase
    items.push({ swarmId: id, title: `Session ${id.slice(0, 8)}...`, timestamp: Date.now(), status: 'running' });
  }
  seenIds.add(id);
}
```

Update sort to prioritize `running` + `generating` above `live`/`saved`:
```typescript
const priority = (s: ReportStatus) => (s === 'running' || s === 'generating') ? 0 : 1;
```

Add CSS for running status (pulsing blue dot):
```css
.report-list-item--running { border-left-color: #3b82f6; }
.report-status-dot--running { background: #3b82f6; animation: pulse-dot 1.5s ease-in-out infinite; }
```

## Tests (TDD — Red then Green)

### reportList.test.ts
- `'includes active swarm in executing phase as running'` — expects `status === 'running'` (currently returns empty)
- `'includes active swarm in qa phase as running'` — same
- `'running items sort before live and saved'`
- Update existing test `'skips active swarms without leaderReport'` → rename to `'includes active swarms without leaderReport as running'`, flip assertion

### swarmReducer.test.ts
- `'shouldShowReportView returns false when phase is planning and no report'` — documents the contract

### toastNotifications.test.tsx
- Spy on `toast` default export, render App or simulate the event handler, verify `toast()` called when `swarm.phase_changed` with `phase === 'planning'` arrives

## Files Modified

| File | What |
|------|------|
| `src/frontend/src/App.tsx` | Import `toast`, add planning phase handler (auto-nav + toast) |
| `src/frontend/src/utils/buildReportList.ts` | Add `'running'` status, include all active swarms, update sort |
| `src/frontend/src/App.css` | Add `.report-list-item--running` and `.report-status-dot--running` |
| `src/frontend/src/__tests__/reportList.test.ts` | 3-4 new tests, 1 updated test |
| `src/frontend/src/__tests__/swarmReducer.test.ts` | 1 new test |
| `src/frontend/src/__tests__/toastNotifications.test.tsx` | 1 new test |

## Verification

```bash
cd src/frontend && npx vitest run          # all frontend tests
cd ../.. && python -m pytest tests/unit/ -x -q  # backend unchanged but confirm
```

Manual: start azure-solutions-agent swarm → complete QA → verify auto-return to dashboard + toast + session in sidebar list.
