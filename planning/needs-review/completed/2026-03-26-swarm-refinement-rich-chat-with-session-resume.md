# Swarm Refinement: Rich Chat with Session Resume

## Context

After a swarm completes, the report is read-only. We're building a full chat experience ported from the VS Code extension — streaming markdown, mermaid diagrams, auto-scroll, user/assistant bubbles — so users can refine reports by chatting with the synthesis agent. Session resume via `client.resume_session(session_id)` means no sessions held open.

## Layout Change

Replace the report modal with a full-screen two-column view:
- **Left column:** Report content rendered as rich markdown (headings, code blocks, mermaid diagrams)
- **Right column:** Chat panel (full height) with message history, streaming responses, chat input
- **Resizable divider** between columns (drag to resize)
- **Back button** to return to dashboard

## Phase 1: Backend — Session ID + Chat Endpoint (TDD)

### 1A. Store synthesis session ID

**File:** `src/backend/swarm/orchestrator.py`

- Add `self.synthesis_session_id: str | None = None` to `__init__`
- In `_synthesize()`, pass `session_id=f"synth-{self.swarm_id}"` to `create_session()`
- After synthesis completes: `self.synthesis_session_id = f"synth-{self.swarm_id}"`

### 1B. Add `chat()` method to orchestrator

**File:** `src/backend/swarm/orchestrator.py`

```python
async def chat(self, message: str) -> str:
    """Resume synthesis session and send a refinement message."""
    session = await self.client.resume_session(
        self.synthesis_session_id,
        on_permission_request=_approve_all,
    )
    # Event-driven capture (same pattern as _synthesize)
    done = asyncio.Event()
    text_content: list[str] = []
    message_id = f"chat-{uuid4().hex[:8]}"

    def _on_event(event):
        raw = getattr(event, "type", "")
        et = getattr(raw, "value", str(raw)).lower()
        if "idle" in et:
            done.set()
        if "assistant.message" in et and "delta" not in et:
            data = getattr(event, "data", None)
            content = getattr(data, "content", None)
            if content and str(content).strip():
                text_content.append(str(content))
        # Stream deltas to frontend
        if "assistant.message_delta" in et:
            data = getattr(event, "data", None)
            delta = getattr(data, "content", "")
            if delta:
                self._emit_sync("leader.chat_delta", {
                    "delta": str(delta), "message_id": message_id,
                })

    unsubscribe = session.on(_on_event)
    try:
        await session.send(message)
        await asyncio.wait_for(done.wait(), timeout=300)
    finally:
        unsubscribe()

    response = "\n".join(text_content) if text_content else ""
    await self._emit("leader.chat_message", {
        "content": response, "message_id": message_id,
    })
    return response
```

### 1C. Chat REST endpoint

**File:** `src/backend/api/rest.py`

```python
@router.post("/api/swarm/{swarm_id}/chat")
async def chat_with_swarm(swarm_id: str, request: ChatRequest, background_tasks: BackgroundTasks):
    if swarm_id not in swarm_store:
        raise HTTPException(status_code=404, detail="Swarm not found")
    state = swarm_store[swarm_id]
    if state["phase"] != "complete":
        raise HTTPException(status_code=409, detail="Swarm not yet complete")
    orch = state.get("orchestrator")
    if not orch or not orch.synthesis_session_id:
        raise HTTPException(status_code=400, detail="No synthesis session available")
    background_tasks.add_task(orch.chat, request.message)
    return {"status": "streaming"}
```

### 1D. Schema

**File:** `src/backend/api/schemas.py`

- `ChatRequest(BaseModel): message: str`

### TDD for Phase 1

- **RED:** `test_synthesize_stores_session_id` — after synthesis, `orch.synthesis_session_id == "synth-swarm-abc"`
- **RED:** `test_chat_emits_leader_chat_message` — calling `chat()` emits `leader.chat_message` event
- **RED:** `test_chat_endpoint_404_unknown_swarm`
- **RED:** `test_chat_endpoint_409_incomplete_swarm`
- **RED:** `test_chat_endpoint_200_complete_swarm`
- **RED:** `test_chat_endpoint_401_unauthenticated` — when `SWARM_API_KEY` set, chat requires `X-API-Key`
- **GREEN:** Implement all

Note: The chat endpoint uses the same `verify_api_key` dependency as all other routes (applied via `app.include_router(router, dependencies=[Depends(verify_api_key)])`), so auth is automatic. The test confirms it.

## Phase 2: Frontend State + Basic Chat (TDD)

### 2A. Types

**File:** `src/frontend/src/types/swarm.ts`

```typescript
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export interface ChatState {
  messages: ChatMessage[];
  streamingMessage: { id: string; content: string } | null;
  activeSwarmId: string | null;  // which swarm we're chatting with
}
```

### 2B. Separate `chatReducer` (separation of concerns)

**New file:** `src/frontend/src/hooks/useChatState.ts`

Chat gets its own reducer, separate from the swarm execution reducer. The swarm reducer manages task boards, agents, and inbox. The chat reducer manages refinement conversations.

```typescript
export type ChatAction =
  | { type: 'chat.delta'; swarmId: string; delta: string; messageId: string }
  | { type: 'chat.message'; swarmId: string; content: string; messageId: string }
  | { type: 'chat.user_send'; swarmId: string; message: ChatMessage }
  | { type: 'chat.select_swarm'; swarmId: string }
  | { type: 'chat.clear'; swarmId: string };

export interface ChatStore {
  chats: Record<string, ChatState>;  // per-swarm chat state
  activeSwarmId: string | null;
}

export function chatReducer(state: ChatStore, action: ChatAction): ChatStore
```

The `multiSwarmReducer` does NOT handle chat events. When WS events arrive for `leader.chat_delta` or `leader.chat_message`, `App.tsx` dispatches to the chat reducer, not the swarm reducer.

### 2C. Wire chat events in App.tsx

`SwarmConnection` already receives all WS events. In `handleSwarmEvent`, route chat events to the chat dispatch:

```typescript
const handleSwarmEvent = useCallback((swarmId: string, event: SwarmEvent) => {
  if (event.type.startsWith('leader.chat')) {
    chatDispatch({ ... }); // route to chatReducer
  } else {
    swarmDispatch({ type: 'swarm.event', swarmId, event }); // existing
  }
}, []);
```

### TDD for Phase 2

**New test file:** `src/frontend/src/__tests__/chatReducer.test.ts`

- **RED:** `test chat.delta creates streaming message for swarm`
- **RED:** `test chat.delta appends to existing streaming message`
- **RED:** `test chat.message finalizes to messages array and clears streaming`
- **RED:** `test chat.user_send appends user message`
- **RED:** `test chat.select_swarm sets activeSwarmId`
- **RED:** `test chat.clear removes chat history for swarm`
- **RED:** `test chats are isolated per swarm_id`
- **GREEN:** Implement

## Phase 3: Frontend Components

### 3A. Install dependencies

```bash
cd src/frontend && npm install marked dompurify @types/dompurify
```

### 3B. `flushSafeMarkdown` utility (TDD)

**New file:** `src/frontend/src/utils/flushSafeMarkdown.ts`

Port from extension's `MessageDisplay._flushSafeMarkdown` (lines 506-607). Pure function — stateful parser that only renders complete markdown units (paragraphs, headings, code fences, tables, images).

**Test file:** `src/frontend/src/__tests__/flushSafeMarkdown.test.ts`

- Tests for paragraphs, headings, code fences, tables, incomplete constructs

### 3C. `useAutoScroll` hook

**New file:** `src/frontend/src/hooks/useAutoScroll.ts`

Port from extension's scroll logic (MessageDisplay lines 137-253):
- `userHasScrolled` ref — tracks if user scrolled away
- `isProgrammaticScroll` ref — prevents fighting own scrolls
- `useEffect` on deps triggers scroll if near bottom
- 100px threshold for "near bottom"

### 3D. `StreamingMarkdown` component

**New file:** `src/frontend/src/components/StreamingMarkdown.tsx`

- Props: `content: string`, `isStreaming: boolean`
- Uses `flushSafeMarkdown` to progressively render complete units
- When `isStreaming` becomes false, flush everything remaining via `marked.parse()`
- Renders via `dangerouslySetInnerHTML` with DOMPurify sanitization

### 3E. `ChatInput` component

**New file:** `src/frontend/src/components/ChatInput.tsx`

- Text input with Enter-to-send, send button
- Disabled while streaming
- Props: `onSend: (message: string) => void`, `disabled: boolean`

### 3F. `ChatPanel` replacement

**File:** `src/frontend/src/components/ChatPanel.tsx` (replace)

Full chat panel:
- Message list with user/assistant bubbles (user right-aligned blue border, assistant left-aligned green border — same as extension)
- Completed messages: `marked.parse()` + DOMPurify
- Streaming message: `<StreamingMarkdown />`
- `useAutoScroll` on messages container
- `ChatInput` at bottom
- Swarm selector dropdown at top (pick which completed swarm to chat with)

### 3G. `ResizableLayout` component

**New file:** `src/frontend/src/components/ResizableLayout.tsx`

- Props: `left: ReactNode`, `right: ReactNode`, `defaultLeftPercent?: number`
- Mouse-drag divider with min-width constraints (250px each side)
- CSS: flex container, divider is 4px wide with grab cursor

### 3H. Wire into App.tsx

**File:** `src/frontend/src/App.tsx`

- When `reportSwarmId` is set, render full-screen `ResizableLayout` instead of modal
- Left: Report rendered via `marked.parse()` (not `<pre>`)
- Right: `ChatPanel` with swarm's chat state
- `handleSendChat(swarmId, message)` — optimistically adds user message + POSTs to API
- Back button returns to dashboard

## Phase 4: Mermaid Diagrams

### 4A. `MermaidDiagram` component

**New file:** `src/frontend/src/components/MermaidDiagram.tsx`

- `useEffect` post-processor that scans rendered HTML for `code.language-mermaid`
- Dynamic import of mermaid@11 from CDN
- Toolbar: "View Source" toggle (diagram vs code), "Copy" button
- Dark/light theme detection

### 4B. Apply to both report view and chat messages

Both the left-column report and assistant chat messages get mermaid post-processing.

## Files to Modify/Create

| File | Action |
|------|--------|
| `src/backend/swarm/orchestrator.py` | Modify — session ID, chat method |
| `src/backend/api/rest.py` | Modify — chat endpoint |
| `src/backend/api/schemas.py` | Modify — ChatRequest |
| `tests/unit/test_orchestrator.py` | Modify — session ID + chat tests |
| `tests/unit/test_api.py` | Modify — chat endpoint tests |
| `src/frontend/package.json` | Modify — add marked, dompurify |
| `src/frontend/src/types/swarm.ts` | Modify — ChatMessage, SwarmState |
| `src/frontend/src/hooks/useChatState.ts` | Create — chat reducer (separate from swarm) |
| `src/frontend/src/hooks/useSwarmState.ts` | Modify — remove chat concern, stays swarm-only |
| `src/frontend/src/utils/flushSafeMarkdown.ts` | Create — streaming parser |
| `src/frontend/src/hooks/useAutoScroll.ts` | Create — auto-scroll hook |
| `src/frontend/src/hooks/useMarkdown.ts` | Create — markdown render util |
| `src/frontend/src/components/ChatPanel.tsx` | Replace — full rich chat |
| `src/frontend/src/components/ChatInput.tsx` | Create — input + send |
| `src/frontend/src/components/StreamingMarkdown.tsx` | Create — streaming renderer |
| `src/frontend/src/components/ResizableLayout.tsx` | Create — two-column resizable |
| `src/frontend/src/components/MermaidDiagram.tsx` | Create — mermaid post-processor |
| `src/frontend/src/App.tsx` | Modify — full-screen chat view |
| `src/frontend/src/App.css` | Modify — chat styling |
| `src/frontend/src/__tests__/swarmReducer.test.ts` | Modify — chat tests |
| `src/frontend/src/__tests__/chatReducer.test.ts` | Create — chat reducer tests |
| `src/frontend/src/__tests__/flushSafeMarkdown.test.ts` | Create — parser tests |
| `src/frontend/src/components/ToolCard.tsx` | Create — tool execution cards (Phase 5) |

## Phase 5: Tool Execution Display in Chat

When chatting with the synthesis agent, it may use tools (e.g., reading work directory files, running searches). These tool calls should be visible in the chat.

### 5A. Tool event types

New WS events from the chat session:
- `leader.chat_tool_start` — `{ tool_name, tool_call_id, message_id, swarm_id }`
- `leader.chat_tool_result` — `{ tool_call_id, success, output?, message_id, swarm_id }`

### 5B. Chat state extension

Add to `ChatState`:
```typescript
activeTools: Array<{
  toolCallId: string;
  toolName: string;
  status: 'running' | 'complete' | 'failed';
  output?: string;
}>;
```

### 5C. `ToolCard` component

**New file:** `src/frontend/src/components/ToolCard.tsx`

Port from extension's `ToolExecution.js`:
- Collapsible card with status icon (⏳ ✅ ❌)
- Tool name + arguments preview
- Output on completion (collapsed by default)
- Inline in the message stream between the user message and assistant response

### 5D. Wire into ChatPanel

Tool cards render inline in the message list between the user's message and the streaming assistant response. When `chat.tool_start` arrives, a `ToolCard` appears. When `chat.tool_result` arrives, it updates to show completion.

### TDD for Phase 5

- **RED:** `test chat.tool_start adds tool to activeTools`
- **RED:** `test chat.tool_result updates tool status`
- **GREEN:** Implement

## Porting Reference

Source components in `/home/smolen/dev/vscode-copilot-cli-extension/src/webview/`:
- `app/components/MessageDisplay/MessageDisplay.js` — streaming markdown, auto-scroll, mermaid
- `app/components/InputArea/InputArea.js` — chat input
- `app/components/ToolExecution/ToolExecution.js` — tool cards (deferred)
- `styles.css` — BEM-based styling to port

## Verification

1. Backend tests pass (pytest, 178+)
2. Frontend tests pass (vitest, 28+)
3. `flushSafeMarkdown` unit tests pass
4. Manual: Run swarm → report renders with rich markdown on left → chat on right → type message → streaming response with markdown → mermaid diagrams render → auto-scroll works → resize divider → back to dashboard

---

## Plan Review

**Reviewed:** 2026-03-26 11:59
**Reviewer:** Claude Code (plan-review-intake)

### Strengths

**Phase structure:** The four-phase breakdown (Backend → Frontend State → Components → Mermaid) creates logical dependency ordering with no circular concerns. Each phase is independently testable.

**TDD discipline:** Every phase specifies RED tests before GREEN implementation, with concrete test names. The test count baseline (178+ backend, 28+ frontend) enables regression detection.

**Separation of concerns (Phase 2B):** Splitting chat state into a dedicated `chatReducer` / `useChatState.ts` separate from the swarm execution reducer is architecturally sound. The routing logic in §2C is explicit and minimal.

**Auth coverage:** The note in §1C correctly identifies that `verify_api_key` is wired globally via `app.include_router(router, dependencies=[Depends(verify_api_key)])` (confirmed in `main.py:177`) — no additional work needed and TDD confirms it.

**REST endpoint pattern:** The §1C endpoint matches the existing patterns in `rest.py` exactly — same `swarm_store` access, same `HTTPException` codes, same `background_tasks` pattern.

**Porting reference is real:** The extension source at `/home/smolen/dev/vscode-copilot-cli-extension/src/webview/app/components/MessageDisplay/MessageDisplay.js` exists and line references are actionable.

### Issues

#### Critical (Must Address Before Implementation)

**1. `_emit_sync` does not exist — Phase 1B**

- **Section:** Phase 1B `chat()` method
- **What's wrong:** The `chat()` method's `_on_event` callback is synchronous (required by `session.on()`), but it calls `self._emit_sync("leader.chat_delta", ...)`. The orchestrator only has `async def _emit(...)`. No `_emit_sync` method exists anywhere in the codebase.
- **Why it matters:** `NameError` at runtime. Streaming deltas will never reach the frontend.
- **Suggested fix:** Either add a sync-safe bridge (e.g., `asyncio.create_task(self._emit(...))` wrapped in a loop reference, or a thread-safe queue drained by the async path), or match the pattern from `_synthesize` which does NOT emit from inside `_on_event` and instead relies on the final `leader.chat_message` event. The plan must specify which approach and implement it.

**2. `create_session` does not accept `session_id` — Phase 1A**

- **Section:** Phase 1A task
- **What's wrong:** Task 1A says `pass session_id=f"synth-{self.swarm_id}"` to `create_session()`. The actual `_create_session_with_tools` wrapper and `client.create_session()` calls in the codebase show no `session_id` parameter. The SDK shows `session_id` is a property on the returned session object, assigned by the server — you read it, not pass it.
- **Why it matters:** The implementation instruction is wrong. `create_session(session_id=...)` will either be ignored silently or raise a `TypeError`.
- **Suggested fix:** Change 1A to: after `_synthesize()` completes, capture the session ID from the `session` object (e.g., `self.synthesis_session_id = session.session_id`). Requires storing the `session` object (or its ID) from within `_synthesize()` and exposing it on the orchestrator.

**3. `resume_session` API call signature — Phase 1B**

- **Section:** Phase 1B `chat()` method
- **What's wrong:** The plan calls `client.resume_session(self.synthesis_session_id, on_permission_request=_approve_all)`. The SDK signature is `client.resume_session(session_id, config)` where `config` is a structured config object — not a bare keyword argument. `_approve_all` is also not defined or imported anywhere in the plan.
- **Why it matters:** Wrong call signature causes `TypeError` at runtime. `_approve_all` undefined causes `NameError`.
- **Suggested fix:** Verify the exact `resume_session` signature from the installed SDK. Define `_approve_all` (or reference where it comes from). Model the call on how the research agent framework uses it.

#### Important (Should Address)

**4. Concurrent chat calls — no mutex — Phase 1B/1C**

- **Section:** Phase 1C REST endpoint, Phase 1B `chat()` method
- **What's wrong:** Two simultaneous POST requests to `/api/swarm/{id}/chat` will both call `orch.chat()`, each resuming the same session concurrently. Both register `_on_event` handlers; events and `done` signals will interleave.
- **Why it matters:** Garbled responses, duplicate events, or both requests seeing each other's `idle` signal and returning early.
- **Suggested fix:** Add a lock (e.g., `asyncio.Lock` on the orchestrator) or return 409 if chat is already in progress.

**5. Phase 5 backend tool event emission is absent — Phase 5A**

- **Section:** Phase 5A defines `leader.chat_tool_start` and `leader.chat_tool_result` WS events
- **What's wrong:** The `chat()` method in Phase 1B has no logic to detect or emit tool calls. Phase 5 only defines frontend types/components and reducer tests. The backend change needed to detect tool-use events and emit them is never described.
- **Why it matters:** Phase 5 frontend will be built against events that the backend never emits. Tool cards will never appear.
- **Suggested fix:** Add a Phase 5A-Backend task: in `_on_event`, detect `tool_call` / `tool_result` event types and emit `leader.chat_tool_start` / `leader.chat_tool_result`.

**6. `useMarkdown.ts` listed in file table but never defined**

- **Section:** "Files to Modify/Create" table — `src/frontend/src/hooks/useMarkdown.ts`
- **What's wrong:** No phase section describes what this file should contain or when to create it.
- **Why it matters:** An implementer will see this in the table and have no instructions.
- **Suggested fix:** Either remove it (if covered by `flushSafeMarkdown.ts` + `marked`) or add a task to the appropriate phase.

**7. Session object not persisted after synthesis — Phase 1A/1B**

- **Section:** Phase 1A stores only `self.synthesis_session_id` (a string). Phase 1B calls `resume_session` with that ID.
- **What's wrong:** `_synthesize()` currently holds `session` as a local variable and it goes out of scope. The plan must explicitly state that the `session` local var needs to be read for its `.session_id` before `_synthesize` returns.
- **Why it matters:** Without this, `synthesis_session_id` would hold a constructed string that may not match the actual server-assigned session ID.

**8. `swarmReducer.test.ts` modify description is misleading — File Table**

- **Section:** File table: `src/frontend/src/__tests__/swarmReducer.test.ts` — "Modify — chat tests"
- **What's wrong:** Phase 2B explicitly routes chat events to the chat reducer, not the swarm reducer. The description implies adding chat tests to the wrong file.
- **Suggested fix:** Change description to "Modify — remove any chat-related tests (now in chatReducer.test.ts)" or omit if no changes are needed.

#### Minor (Consider)

**9. Mermaid loaded from CDN — Phase 4A**

- **Section:** Phase 4A: "Dynamic import of mermaid@11 from CDN"
- **What's wrong:** CDN dependency is a security/availability risk and inconsistent with the bundled npm dependency model used for `marked` and `dompurify`.
- **Suggested fix:** Add `mermaid` to the `npm install` command in Phase 3A and import from node_modules.

**10. No edge case for viewing report before synthesis completes**

- **Section:** Phase 3H / App.tsx wiring
- **What's wrong:** The plan doesn't address what happens if a user navigates to the chat view while synthesis is still in progress (`reportSwarmId` set but `leaderReport` null/partial).
- **Suggested fix:** The condition `reportSwarmId && currentReport` likely handles this implicitly — worth confirming in the plan.

**11. No explicit `message: str` validation — Phase 1D**

- **Section:** Phase 1D `ChatRequest`
- **What's wrong:** `message: str` with no length constraints. An empty or very large message will be forwarded to the API.
- **Suggested fix:** Add `message: str = Field(..., min_length=1, max_length=10000)`.

### Recommendations

1. **Resolve `_emit_sync` before writing any code.** The sync-to-async bridge in event callbacks is a recurring pattern challenge. The chosen approach should be documented and consistent with how `event_bridge.py` handles similar problems.

2. **Prototype `resume_session` in a small integration test first.** The entire feature depends on session resumption working correctly with the installed SDK version. Validating the API call signature before building the full stack will prevent Phase 1 from blocking Phases 2–5.

3. **Clarify the session ID capture sequence** as a numbered step within Phase 1A, since it's the foundational prerequisite for the whole feature and the current instruction is incorrect.

### Assessment
**Implementable as written?** No — with fixes required.
**Reasoning:** Three critical issues (`_emit_sync` missing, incorrect `create_session(session_id=...)` call, and undefined `_approve_all` with wrong `resume_session` signature) will cause runtime failures on Phase 1 before any frontend work can be tested. Fixing these requires non-trivial design decisions about sync/async bridging and SDK usage that need to be resolved in the plan.
