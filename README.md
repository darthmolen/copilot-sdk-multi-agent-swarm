# Multi-Claw Swarm Architecture with Copilot SDK

A multi-agent swarm system that emulates swarm intelligence using GitHub Copilot CLI in headless mode. A leader agent decomposes high-level goals into subtasks with dependency constraints, worker agents execute those subtasks concurrently across rounds, and a synthesis agent consolidates results into a final report. The system provides real-time visibility into agent activity through WebSocket-driven event streaming and a React dashboard.

## Architecture Overview

The system follows a four-phase lifecycle: **Plan** (leader decomposes the goal into a task graph), **Spawn** (worker agents are created with custom roles and tools), **Execute** (round-based concurrent execution with dependency resolution), and **Synthesize** (results are consolidated into a final report).

An `EventBus` decouples all components. SDK session events are mapped through an `EventBridge` to WebSocket messages, enabling real-time frontend updates without polling.

For a detailed architecture diagram and component descriptions, see [documentation/Architecture.md](documentation/Architecture.md).

## Key Features

- **Custom agents** -- leader decomposes goals; workers are dynamically spawned with role-specific system prompts
- **Event-driven execution** -- publish-subscribe `EventBus` with both async and sync emission for SDK callback compatibility
- **Real-time WebSocket streaming** -- all swarm events (task updates, agent status changes, tool calls, reasoning deltas) are streamed to connected clients
- **Task dependency resolution** -- tasks declare `blocked_by` relationships; the orchestrator only dispatches runnable tasks each round
- **3 built-in templates** -- pre-configured team compositions for common workflows (see [Templates](#templates))
- **Cancellation support** -- running swarms can be cancelled via REST API, propagating through the orchestrator to all active agents
- **Inter-agent messaging** -- agents communicate through a shared inbox system with send/receive tools

## Tech Stack

| Layer    | Technology                          |
|----------|-------------------------------------|
| Backend  | Python 3.10+, FastAPI, Pydantic v2, asyncio, uvicorn |
| Frontend | React 19, TypeScript 5.9, Vite      |
| SDK      | GitHub Copilot SDK (headless CLI)   |
| Testing  | pytest + pytest-asyncio, Vitest     |

## Project Structure

```
copilot-sdk-multi-agent-swarm/
  pyproject.toml
  src/
    backend/
      main.py                    # FastAPI app, WebSocket endpoint, lifespan
      config.py                  # SwarmConfig (model, rounds, timeout, workers)
      events.py                  # EventBus (pub-sub with async/sync emit)
      api/
        rest.py                  # REST endpoints: start, status, cancel, templates
        schemas.py               # Request/response Pydantic models
        websocket.py             # WebSocket connection manager
      swarm/
        orchestrator.py          # Four-phase lifecycle: plan, spawn, execute, synthesize
        agent.py                 # SwarmAgent: wraps CopilotSession with event-driven execution
        models.py                # Task, AgentInfo, InboxMessage models
        tools.py                 # Tool factory: task_update, inbox_send/receive, task_list
        templates.py             # Pre-built swarm templates
        event_bridge.py          # SDK event -> WebSocket event mapping
        task_board.py            # Shared task state with dependency tracking
        inbox_system.py          # Inter-agent message passing
        team_registry.py         # Agent registration and lookup
        prompts.py               # Leader and synthesis system prompts
    frontend/
      src/
        App.tsx                  # Root component with dashboard layout
        components/
          SwarmControls.tsx       # Goal input and template selection
          TaskBoard.tsx           # Task status visualization
          AgentRoster.tsx         # Agent list with live status and output
          ChatPanel.tsx           # Leader plan and final report display
          InboxFeed.tsx           # Inter-agent message stream
        hooks/
          useSwarmState.ts        # Reducer-based state management
          useWebSocket.ts         # WebSocket connection and event dispatch
        types/
          swarm.ts               # Shared TypeScript type definitions
  tests/
    test_orchestrator.py
    test_swarm_agent.py
    test_swarm_tools.py
    test_event_bridge.py
    test_event_bus.py
    test_task_board.py
    test_inbox_system.py
    test_team_registry.py
    test_templates.py
    test_api.py
    test_cancellation.py
  documentation/
    Architecture.md
    Communication.md
```

## Getting Started

### Prerequisites

- Python 3.10 or later
- Node.js 18 or later
- GitHub Copilot CLI installed and authenticated

### Install backend dependencies

```bash
pip install -e ".[dev]"
```

### Install frontend dependencies

```bash
cd src/frontend
npm install
```

### Run the backend

```bash
uvicorn backend.main:app --reload --app-dir src
```

The API will be available at `http://localhost:8000`. The WebSocket endpoint is at `ws://localhost:8000/ws/{swarm_id}`.

### Run the frontend

```bash
cd src/frontend
npm run dev
```

The dashboard will be available at `http://localhost:5173`.

## Running Tests

### Backend

```bash
pytest
```

To skip integration tests that require a live Copilot CLI session:

```bash
pytest -m "not integration"
```

### Frontend

```bash
cd src/frontend
npm test
```

## Templates

| Template | Description |
|----------|-------------|
| **Software Development Team** | Assembles specialists for architecture/design, implementation, testing, and documentation. Implementation is blocked by design; testing is blocked by implementation; documentation runs in parallel with testing. |
| **Deep Research Team** | Creates researchers for primary sources, contrarian analysis, and quantitative data gathering. All research runs in parallel; a synthesis task is blocked by all research tasks. |
| **Warehouse Optimization Team** | Deploys specialists for inventory analysis, layout/flow optimization, demand forecasting, and implementation planning. Analysis and forecasting run in parallel; layout depends on inventory; implementation depends on all others. |

## Documentation

- [Architecture](documentation/Architecture.md) -- system design, component interactions, and data flow
- [Communication](documentation/Communication.md) -- event taxonomy, WebSocket protocol, and inter-agent messaging
