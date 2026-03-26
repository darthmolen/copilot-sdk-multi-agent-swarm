# Swarm Refinement: Two-Mode Feedback Loop

## Context

The swarm produces a report but there's no way to refine it. Two distinct needs exist:
1. **Close but needs tweaks** — The report is mostly right, a few sections need adjustment. Don't re-run 4 agents for minor edits.
2. **Good start but needs depth** — The direction is right but multiple sections need the specialists to dig deeper with additional context from the user.

## Design: Two Refinement Modes

### Mode 1: Synthesist Chat (Light Touch)

A conversational interface with the synthesis agent that has the full report + all worker outputs in context.

**UX Flow:**
1. Report modal shows with a chat input at the bottom
2. User types feedback: "The ROI section is too optimistic. What if implementation takes 2x?"
3. Synthesis agent responds with revised text, referencing the worker data it already has
4. User continues the conversation until satisfied
5. "Accept Report" button saves the final version
6. If the user realizes deeper changes are needed → "Send to Full Review" escalates to Mode 2

**Implementation:**
- Keep the synthesis session alive after report generation (don't close it)
- Chat messages go via `session.send()` on the existing synthesis session
- The session already has all task results in context from the synthesis prompt
- New `leader.report_update` event pushes revised report to the modal in real-time
- Report modal gets a chat input bar below the report text

**Backend changes:**
- `SwarmOrchestrator` stores the synthesis session reference after `_synthesize()`
- New API endpoint: `POST /api/swarm/{swarm_id}/chat` — sends message to synthesis session
- New event: `leader.report_update` — streams revised report sections to frontend

**Frontend changes:**
- Report modal adds chat input + message history below the report
- `swarm.event` handler for `leader.report_update` updates `leaderReport` in state
- "Accept Report" button marks the swarm as finalized
- "Send to Full Review" button switches to Mode 2

### Mode 2: Section Annotations + Full Re-Run (Deep Refinement)

User annotates specific report sections with feedback, then re-submits through the full swarm.

**UX Flow:**
1. Report modal shows with a "Reply" button next to each section header
2. User clicks Reply → inline text input expands below that section
3. User types annotation: "Challenge the 15% growth assumption — our market is contracting"
4. User can annotate multiple sections
5. "Re-submit" button at the bottom triggers a new swarm run
6. The new swarm goal = original goal + "REFINEMENT FEEDBACK:" + all annotations
7. Workers get the original report + annotations as context in their task descriptions
8. New report appears — user can annotate again or accept

**Implementation:**
- Report sections need to be parseable (split on `##` headers)
- Annotations stored as `Array<{section: string, feedback: string}>` in frontend state
- Re-submit calls `POST /api/swarm/start` with enriched goal
- The leader prompt for refinement runs includes: original goal, previous report, section annotations
- Workers get their previous output + relevant annotations in their task description

**Backend changes:**
- New field on `SwarmStartRequest`: `refinement_context?: { previous_report: string, annotations: Array<{section, feedback}> }`
- `_plan()` detects refinement context and includes it in the leader prompt
- Workers receive annotation feedback in their task descriptions

**Frontend changes:**
- Report modal sections become annotatable (Reply button per `##` heading)
- Annotation state: `Record<string, string>` keyed by section title
- Re-submit button creates new swarm with refinement context
- Visual indicator that this is a "refinement run" vs. fresh run

### Escalation Path

```text
Report arrives
     ↓
Chat with synthesist (Mode 1)
     ↓
Satisfied? → Accept Report → Done
     ↓ (no)
Need deeper changes? → "Send to Full Review"
     ↓
Annotate sections (Mode 2)
     ↓
Re-submit through full swarm
     ↓
New report → back to Mode 1 chat or annotate again
```

## Implementation Order

1. **Mode 1 first** — Faster to implement (session already exists), immediately useful, validates the UX
2. **Mode 2 second** — Requires prompt engineering for refinement context, more frontend work
3. **Escalation path** — Wire Mode 1 → Mode 2 transition button

## Open Questions

- Should Mode 1 chat history persist across page refreshes? (sessionStorage vs. backend state)
- Should the synthesist be able to call worker tools during chat? (e.g., re-query a specialist)
- Max conversation turns in Mode 1 before suggesting Mode 2?
- Should Mode 2 re-run only the annotated sections' workers, or all workers?
