# Work Package: Streaming Fix + Mermaid + Tool Cards + Dockerfile + Template Editor

## Instructions

Execute this plan using strict TDD (test-driven-development skill). For each task: RED test first, verify it fails, GREEN minimal implementation, verify it passes, then move on. Commit after each task completes.

## Tasks (in execution order)

### Task 1: Synthesis Streaming Fix

**Problem:** `resume_session` doesn't emit `assistant.message_delta` events — only `assistant.message` (complete). Logs confirm: no deltas during chat, only final message. Chat feels stuck with "starting session" and no progress.

**Fix:** In `orchestrator.py` `chat()` `_on_event`, also check for `assistant.message` events and emit them as `leader.chat_delta` (since the SDK is sending complete messages instead of deltas). This way the frontend gets content progressively even without true deltas.

Additionally, the `_on_event` handler should treat each `assistant.message` as a delta and accumulate, rather than only capturing at the end.

**Files:** `src/backend/swarm/orchestrator.py`

**TDD:**

- RED: `test_chat_emits_delta_from_assistant_message` — when SDK sends `assistant.message` (no deltas), orchestrator emits `leader.chat_delta` so frontend sees streaming
- GREEN: In `_on_event`, when `assistant.message` is received, also emit `leader.chat_delta` with the content

### Task 2: Tool Execution Cards in Chat

**What:** Show tool calls (file reads, searches) as collapsible cards inline in chat during refinement.

**State already exists:** `ChatState.activeTools` tracks `{ toolCallId, toolName, status }`. Events `leader.chat_tool_start` and `leader.chat_tool_result` already flow through. Just need the UI.

**Approach:**

- Create `ToolCard.tsx` component — collapsible card with status icon (spinner running, check complete, x failed)
- Render active tools in ChatPanel between user message and streaming response
- Port pattern from VS Code extension's `ToolExecution.js` at `/home/smolen/dev/vscode-copilot-cli-extension/src/webview/app/components/ToolExecution/ToolExecution.js`

**Files:**

- `src/frontend/src/components/ToolCard.tsx` — Create
- `src/frontend/src/components/ChatPanel.tsx` — Render ToolCards from activeTools prop
- `src/frontend/src/App.css` — Tool card styles

**TDD:**

- The ChatPanel already receives `activeTools` state. Just need visual rendering — this is primarily a UI component, test that ToolCard renders correct status icons.

### Task 3: Mermaid Diagram Rendering

**What:** Render mermaid code blocks in reports and chat as SVG diagrams.

**Approach:**

- `cd src/frontend && npm install mermaid`
- Create `useMermaid.ts` hook: after markdown renders to DOM, scan for `code.language-mermaid` or `pre > code.language-mermaid` elements, call `mermaid.run({ nodes })` on them
- Apply hook to both report view (left pane) and chat message container
- Add "View Source" toggle button on each diagram (switches between rendered SVG and raw mermaid code)
- Use dark theme config: `mermaid.initialize({ theme: 'dark', startOnLoad: false })`

**Files:**

- `src/frontend/package.json` — add mermaid dep
- `src/frontend/src/hooks/useMermaid.ts` — Create hook
- `src/frontend/src/App.tsx` — apply hook to report content div via ref
- `src/frontend/src/components/ChatPanel.tsx` — apply hook to message container
- `src/frontend/src/App.css` — mermaid container styles

### Task 4: Dockerfile

**What:** Multi-stage Dockerfile for production deployment.

**Approach:**

- Stage 1 (frontend-builder): Node 20 alpine, `npm ci && npm run build` in `src/frontend/`
- Stage 2 (runtime): Python 3.12 slim, install backend deps from `pyproject.toml`, copy built frontend to `static/`, copy backend source
- Serve frontend static files from FastAPI via `StaticFiles` middleware (only when `static/` dir exists)
- `.dockerignore` for node_modules, `__pycache__`, workdir, .git, logs, .env
- `docker-compose.yml` with `SWARM_API_KEY`, `ENVIRONMENT=production`, port 8000

**Files:**

- `Dockerfile` — Create (project root)
- `.dockerignore` — Create
- `docker-compose.yml` — Create
- `src/backend/main.py` — Add conditional `StaticFiles` mount for production frontend

**TDD:**

- No unit tests for Docker itself, but verify `npm run build` succeeds and `main.py` StaticFiles mount doesn't break existing tests

### Task 5: Template Editor with Validation (Bonus)

**What:** Edit button next to template dropdown opens a template browser/editor. All saves validated.

**Backend — Validation (TDD first):**

- Create `src/backend/swarm/template_validator.py` with pure function `validate_template_file(filename: str, content: str) -> ValidationResult`
- `ValidationResult` dataclass: `valid: bool`, `errors: list[ValidationError]`
- `ValidationError` dataclass: `message: str`, `line: int | None`
- Validation rules:
  - Valid YAML frontmatter delimited by `---` on lines 1 and N
  - For `_template.yaml`: required fields `key`, `name`, `description`, `goal_template`; `goal_template` must contain `{user_input}`
  - For `worker-*.md`: required frontmatter fields `name`, `displayName`, `description`
  - For `leader.md` / `synthesis.md`: must have non-empty body after frontmatter
  - `tools` list (if present) only contains known tool names: `task_update`, `inbox_send`, `inbox_receive`, `task_list`
  - Invalid YAML returns parse error with line number

**Tests (RED first):** `tests/unit/test_template_validator.py`

- `test_valid_worker_file_passes`
- `test_missing_frontmatter_fails`
- `test_invalid_yaml_fails`
- `test_missing_required_fields_fails`
- `test_unknown_tool_name_fails`
- `test_template_yaml_missing_user_input_placeholder_fails`
- `test_leader_with_empty_body_fails`
- `test_valid_template_yaml_passes`

**Backend — CRUD endpoints:**

- `GET /api/templates/{key}` — Full template: metadata + list of files with content
- `PUT /api/templates/{key}/files/{filename}` — Update file content (validates first, returns 422 with errors if invalid)
- `POST /api/templates` — Create new template (scaffolds `_template.yaml`, `leader.md`, `synthesis.md`, one `worker-default.md`)
- `DELETE /api/templates/{key}` — Delete template directory

**Tests:** `tests/unit/test_api.py` additions

- `test_get_template_details_returns_files`
- `test_update_template_file_validates`
- `test_update_template_file_rejects_invalid`
- `test_create_template_scaffolds_files`
- `test_delete_template_removes_directory`

**Frontend — TemplateEditor component:**

- `src/frontend/src/components/TemplateEditor.tsx` — Modal/overlay component
  - Left sidebar: list of template names (fetched from `GET /api/templates`)
  - Click template → fetches `GET /api/templates/{key}` → shows file list
  - Click file → shows content in a `<textarea>` with monospace font
  - Save button → `PUT /api/templates/{key}/files/{filename}` → shows validation errors inline if 422
  - New Template button → `POST /api/templates` → refreshes list
  - Delete button → `DELETE /api/templates/{key}` with confirmation
  - Close button returns to SwarmControls
- Edit button (pencil icon) added to the left of the template `<select>` in `SwarmControls.tsx`
- Clicking edit opens `TemplateEditor` as a full-screen overlay

**Files:**

- `src/backend/swarm/template_validator.py` — Create (pure validation)
- `tests/unit/test_template_validator.py` — Create (RED tests first)
- `src/backend/api/rest.py` — Add template CRUD endpoints (validate on PUT)
- `src/frontend/src/components/TemplateEditor.tsx` — Create
- `src/frontend/src/components/SwarmControls.tsx` — Add edit button + modal state
- `src/frontend/src/App.css` — Template editor styles (overlay, sidebar, editor area)

## Execution Order

1. Streaming fix (quick, high impact)
2. Tool cards (state exists, just UI)
3. Mermaid (npm install + hook)
4. Dockerfile (independent)
5. Template validator (TDD — RED tests, then GREEN)
6. Template CRUD endpoints (TDD)
7. Template editor frontend

## Verification

- All existing tests pass after each task
- New tests for: streaming behavior, template validation, template CRUD endpoints
- Manual: chat shows streaming text + tool cards + mermaid diagrams
- `docker build -t swarm . && docker run -p 8000:8000 swarm` works
- Template editor: create, edit, save (with validation errors), delete
