# Multi-Agent Swarm with Copilot SDK

A multi-agent swarm system using GitHub Copilot CLI in headless mode. A leader agent decomposes high-level goals into subtasks with dependency constraints, worker agents execute concurrently across rounds, and a synthesis agent consolidates results into a final report. Real-time visibility through WebSocket-driven event streaming and a React dashboard. Supports multiple concurrent swarms.

## Architecture Overview

Four-phase lifecycle: **Plan** (leader decomposes goal via tool-based structured output) → **Spawn** (workers created with role-specific system prompts and model selection) → **Execute** (round-based concurrent execution with dependency resolution) → **Synthesize** (results consolidated with work directory files injected into context).

An `EventBus` decouples all components. Every event carries a `swarm_id` for per-swarm routing. SDK session events flow through the EventBus to WebSocket connections, enabling real-time frontend updates.

See [documentation/Architecture.md](documentation/Architecture.md) for component diagrams and design decisions.

## Key Features

- **Multi-swarm support** — Run multiple swarms simultaneously with isolated state per swarm
- **Event-driven execution** — `session.send()` + `session.on()` pattern, waiting for `session.idle` (not `turn_end`)
- **No `customAgents`** — Uses `system_message: mode:"replace"` for better custom tool compliance
- **Per-swarm work directories** — Each swarm gets `workdir/<swarm_id>/` for agent file output
- **Defensive tool handlers** — All 4 swarm tools validate arguments and return errors instead of crashing
- **Real-time WebSocket streaming** — All events routed by `swarm_id` to correct frontend connections
- **Task dependency resolution** — Tasks declare `blocked_by` relationships; orchestrator dispatches only runnable tasks
- **Inter-agent messaging** — Shared inbox system with send/receive tools and anti-polling instructions
- **API key authentication** — Configurable auth with environment-based security policy
- **3 built-in templates** — Pre-configured team compositions for common workflows
- **Synthesis with full context** — Work directory files injected into synthesis prompt so the synthesis agent has all research content

## Tech Stack

| Layer    | Technology                          |
|----------|-------------------------------------|
| Backend  | Python 3.10+, FastAPI, Pydantic v2, asyncio, uvicorn, structlog |
| Frontend | React 19, TypeScript 5.9, Vite      |
| SDK      | GitHub Copilot SDK (headless CLI), Gemini 3 Pro Preview |
| Testing  | pytest + pytest-asyncio (178+), Vitest (28+) |

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
        rest.py                  # REST endpoints: start, status, cancel, templates
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
      software-development/      # 4 workers: architect, implementer, tester, documenter
      warehouse-optimizer/       # 4 workers: inventory, layout, demand, planner
    frontend/
      src/
        App.tsx                  # Multi-swarm dashboard with auth gate
        components/
          SwarmControls.tsx       # Goal input, template selection, API key header
          TaskBoard.tsx           # Kanban board with swarm_id labels
          AgentRoster.tsx         # Agent cards with status dots and swarm_id
          ChatPanel.tsx           # Synthesis report display
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
    test_api.py                  # REST + WS + auth tests
    test_event_bridge.py
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

Create a `.env` file in the project root:

```bash
LOG_LEVEL=DEBUG
ENVIRONMENT=development
SWARM_API_KEY=
```

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

1. Select a template from the dropdown (Deep Research, Software Development, or Warehouse Optimizer)
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

### Backend (178+ tests)

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
| **Software Development** | Architect, Implementer, Tester, Documenter | Implementation blocked by design; testing blocked by implementation; docs parallel with testing |
| **Warehouse Optimization** | Inventory Analyst, Layout Optimizer, Demand Forecaster, Implementation Planner | Inventory + demand parallel; layout blocked by inventory; planner blocked by all three |

## Documentation

- [Architecture](documentation/Architecture.md) — system design, component interactions, design decisions
- [Communication](documentation/Communication.md) — event taxonomy, WebSocket protocol, inter-agent messaging
