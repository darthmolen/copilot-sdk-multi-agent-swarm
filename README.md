# Multi-Agent Swarm with Copilot SDK

A multi-agent swarm system using GitHub Copilot CLI in headless mode. A leader agent decomposes high-level goals into subtasks with dependency constraints, worker agents execute concurrently across rounds, and a synthesis agent consolidates results into a final report. Real-time visibility through WebSocket-driven event streaming and a React dashboard. Supports multiple concurrent swarms.

## Architecture Overview

Four-phase lifecycle: **Plan** (leader decomposes goal via tool-based structured output) → **Spawn** (workers created with role-specific system prompts and model selection) → **Execute** (round-based concurrent execution with dependency resolution) → **Synthesize** (results consolidated with work directory files injected into context).

An `EventBus` decouples all components. Every event carries a `swarm_id` for per-swarm routing. SDK session events flow through the EventBus to WebSocket connections, enabling real-time frontend updates.

See [documentation/Architecture.md](documentation/Architecture.md) for component diagrams and design decisions.

## What You Get

- **Parallel research teams on demand** — Describe a goal, get a coordinated team of AI agents that decompose, research, and synthesize a report. Run multiple teams simultaneously.
- **Ready-made team templates** — Deep Research and Warehouse Optimization with pre-configured roles and task dependencies. Create your own via the template editor or deploy template packs via zip.
- **Live dashboard** — Watch tasks move through Blocked → Pending → In Progress → Completed in real time. See which agent is doing what.
- **Refinement chat** — Talk to the synthesis agent after the report is done. Ask follow-up questions, request revisions, drill into specifics — all with full context of the original research.
- **Download session files** — Export all artifacts from any session as a ZIP archive directly from the UI.
- **Resumable sessions** — Share a URL to any report. Come back later and pick up the refinement conversation where you left off.
- **Custom templates** — Build your own team compositions through the in-browser template editor with live validation.
- **Run anywhere** — Run locally on your machine or hosted by your IT organization. Same experience either way.

## Under the Hood

- **Event-driven orchestration** — Four-phase lifecycle (Plan → Spawn → Execute → Synthesize) with an `EventBus` decoupling all components. No polling, no blocking.
- **Per-swarm isolation** — Every swarm gets its own state, work directory, and WebSocket channel. Multiple swarms run concurrently without interference.
- **Task dependency resolution** — Tasks declare `blocked_by` relationships; the orchestrator dispatches only runnable tasks each round.
- **Inter-agent messaging** — Shared inbox system lets agents coordinate without the orchestrator as a bottleneck.
- **Structured logging** — JSON-formatted structlog with tool names, duration tracking, and tool call counts on every chat interaction. Debug a hallucinating agent from the logs alone.
- **API key authentication** — Environment-based security policy: open for local dev, enforced in production. REST via `X-API-Key` header, WebSocket via query parameter.
- **Path traversal protection** — All file endpoints validate resolved paths stay within the work directory. Symlinks outside the boundary are rejected.
- **Defensive tool handlers** — All swarm tools validate arguments and return structured errors instead of crashing the session.
- **Dockerized deployment** — Container-ready for IT hosting with configurable auth and log output.

## Tech Stack

| Layer    | Technology                          |
|----------|-------------------------------------|
| Backend  | Python 3.10+, FastAPI, Pydantic v2, asyncio, uvicorn, structlog |
| Frontend | React 19, TypeScript 5.9, Vite      |
| SDK      | GitHub Copilot SDK (headless CLI), Gemini 3 Pro Preview |
| Testing  | pytest + pytest-asyncio (223+), Vitest (28+) |

## Project Structure

```
copilot-sdk-multi-agent-swarm/
  pyproject.toml
  src/
    backend/
      main.py                    # FastAPI app, auth middleware, WebSocket endpoint
      config.py                  # Default model config
      events.py                  # EventBus (pub-sub with async/sync emit)
      logging_config.py          # structlog JSON logging
      api/
        rest.py                  # REST endpoints: start, status, cancel, chat, files, download-zip, templates
        schemas.py               # Request/response Pydantic models
        websocket.py             # WebSocket connection manager (per-swarm routing)
      swarm/
        orchestrator.py          # Four-phase lifecycle with swarm_id routing
        agent.py                 # SwarmAgent: event-driven session with work_dir
        models.py                # Task, TaskStatus models
        tools.py                 # Tool factory with defensive error handling
        template_loader.py       # YAML template loader with system prompt frontmatter
        event_bridge.py          # SDK event type mapping
        task_board.py            # Shared task state with dependency tracking
        inbox_system.py          # Inter-agent message passing
        team_registry.py         # Agent registration and lookup
        prompts.py               # Prompt assembly (system preamble + template + work_dir)
    templates/
      system-prompt.md           # System coordination protocol (YAML frontmatter + body)
      deep-research/             # 3 workers: researcher, skeptic, data analyst
      # Templates deployed via zip (simple-coding-agent, azure-solutions-agent, etc.)
      warehouse-optimizer/       # 4 workers: inventory, layout, demand, planner
    frontend/
      src/
        App.tsx                  # Multi-swarm dashboard + report refinement view
        components/
          SwarmControls.tsx       # Goal input, template selection, API key header
          TaskBoard.tsx           # Kanban board with swarm_id labels
          AgentRoster.tsx         # Agent cards with status dots and swarm_id
          ChatPanel.tsx           # Refinement chat with streaming markdown
          ChatInput.tsx           # Chat input with Enter-to-send
          ArtifactList.tsx        # File explorer sidebar with ZIP download
          ResizableLayout.tsx     # Draggable two-column split view
          StreamingMarkdown.tsx   # Progressive markdown renderer
          ToolCard.tsx            # Tool execution status cards
          TemplateEditor.tsx      # In-browser template CRUD with validation
          InboxFeed.tsx           # Inter-agent message stream
        hooks/
          useSwarmState.ts        # Per-swarm reducer + multiSwarmReducer
          useWebSocket.ts         # WS with React Strict Mode active guard
        types/
          swarm.ts               # TypeScript types with swarm_id fields
  tests/unit/
    test_orchestrator.py         # Full lifecycle + swarm_id routing tests
    test_swarm_agent.py          # Agent execution tests
    test_swarm_tools.py          # Tool handlers + defensive error handling
    test_api.py                  # REST + WS + auth + file download tests
    test_event_bridge.py
    test_logging.py              # Structured logging configuration tests
    test_event_bus.py
    test_task_board.py
    test_inbox_integration.py
    test_inbox_system.py
    test_team_registry.py
    test_templates.py
    test_prompts.py
    test_cancellation.py
  documentation/
    Architecture.md
    Communication.md
    example_research_output/     # Sample outputs from deep research swarms
    test-prompts.md              # Test prompts for each template
  planning/
    backlog/                     # Future work: guardrails, warehouse movement system, refinement loop
```

## Getting Started

### Prerequisites

- Python 3.10 or later
- Node.js 18 or later
- GitHub Copilot CLI installed and **already authenticated** — run `copilot auth login` before starting the backend. The swarm spawns headless CLI sessions that require an active auth session.

### Install backend dependencies

```bash
pip install -e ".[dev]"
```

### Install frontend dependencies

```bash
cd src/frontend
npm install
```

### Configure environment

Copy `.env.template` to `.env` and adjust for your environment:

```bash
cp .env.template .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `DEBUG` | Logging verbosity (DEBUG, INFO, WARNING, ERROR) |
| `ENVIRONMENT` | — | Set to `development` to disable auth when no key is set |
| `SWARM_API_KEY` | — | API key for REST and WebSocket auth. Empty + development = open access |
| `SWARM_TASK_TIMEOUT` | `1800` | Max seconds per agent task before timeout (30 min) |
| `SWARM_MAX_ROUNDS` | `3` | Max execution rounds per swarm |
| `SWARM_MODEL` | `gemini-3-pro-preview` | LLM model identifier for agent sessions |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Comma-separated allowed CORS origins |
| `SWARM_WORK_DIR` | `workdir` | Agent work directory (use absolute path for Docker) |
| `TEMPLATES_DIR` | `src/templates` | Template directory (use absolute path for Docker) |
| `LOGS_DIR` | `logs` | Log output directory |
| `STATIC_DIR` | `static` | Built frontend static files directory |
| `SWARM_MAX_TEMPLATE_ZIP_SIZE` | `3145728` | Max zip size for template deploy (3MB) |

### Run the backend

```bash
uvicorn backend.main:app --reload --app-dir src
```

The API is at `http://localhost:8000`. WebSocket at `ws://localhost:8000/ws/{swarm_id}`.

### Run the frontend

```bash
cd src/frontend
npm run dev
```

Dashboard at `http://localhost:5173`.

## How to Run

### Quick start (VS Code)

The project includes VS Code tasks for one-click startup:

1. Open the project in VS Code
2. `Ctrl+Shift+B` (or `Cmd+Shift+B`) runs the **Start Full Stack** task
3. This launches both backend and frontend in parallel, with logs teed to `logs/`

### Quick start (terminal)

Open two terminals from the project root:

**Terminal 1 — Backend:**

```bash
source .env
mkdir -p logs
uvicorn backend.main:app --reload --app-dir src --port 8000 2>&1 | tee logs/backend-stdout.log
```

**Terminal 2 — Frontend:**

```bash
cd src/frontend
npm run dev
```

Then open `http://localhost:5173` in your browser. If auth is enabled, you'll be prompted for your API key.

### Running a swarm

1. Select a template from the dropdown (Deep Research, Warehouse Optimizer, or any deployed template pack)
2. Enter your goal in the text input
3. Click **Start Swarm**
4. Watch the task board update in real-time: Blocked → Pending → In Progress → Completed
5. When synthesis completes, the report modal auto-pops. Click **Copy** to grab the markdown.
6. You can start additional swarms while others are running — each gets its own swarm_id label on cards

### Test prompts

See [documentation/test-prompts.md](documentation/test-prompts.md) for ready-to-use prompts for each template.

## Authentication

API key authentication is controlled by two environment variables:

| ENVIRONMENT | SWARM_API_KEY | Behavior |
|---|---|---|
| `development` | empty | Auth disabled — open access for local dev |
| `development` | set | Auth enforced with that key |
| anything else | empty | **500 error** — forces you to configure a key |
| anything else | set | Auth enforced with that key |

When auth is enabled:
- REST endpoints require `X-API-Key` header
- WebSocket connections require `?key=` query parameter
- Frontend prompts for the key on first load, stores in `sessionStorage` (cleared on tab close)

To enable auth for production:

```bash
ENVIRONMENT=production
SWARM_API_KEY=your-secret-key-here
```

## Running Tests

### Backend (223+ tests)

```bash
pytest
```

### Frontend (28+ tests)

```bash
cd src/frontend
npx vitest run
```

## Templates

| Template | Workers | Dependency Pattern |
|----------|---------|-------------------|
| **Deep Research** | Primary Researcher, Skeptic, Data Analyst | All research parallel; synthesis blocked by all |
| **Simple Coding Agent** | Architect, Implementer, Tester, Documenter | Deployable via zip pack; includes Microsoft Learn MCP + C# quality skill |
| **Warehouse Optimization** | Inventory Analyst, Layout Optimizer, Demand Forecaster, Implementation Planner | Inventory + demand parallel; layout blocked by inventory; planner blocked by all three |

## Documentation

- [Architecture](documentation/Architecture.md) — system design, component interactions, design decisions
- [Communication](documentation/Communication.md) — event taxonomy, WebSocket protocol, inter-agent messaging
- [Template Creation Guide](documentation/template-creation-guide.md) — how to create custom templates, orchestrator workflow, artifact reference, relationship patterns
- [Replacement Variables](documentation/replacement-variables.md) — built-in template variables and expansion behavior
