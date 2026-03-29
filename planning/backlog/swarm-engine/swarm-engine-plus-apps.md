# Monorepo Restructure: Swarm Engine + Apps

## Problem

This repo serves three diverging concerns: the swarm orchestration engine, a deep research UI, and upcoming remote code agent work (K8s pod orchestration, IDE layer). These will compete for attention and pollute each other if kept in a flat structure.

## Decision: Monorepo with Clear Hierarchy

Single repo, separated by concern. Solo dev — no need for multi-repo overhead. One clone, one CI, atomic cross-cutting changes, local path dependencies.

### Target Structure

```text
copilot-sdk-multi-agent-swarm/
├── swarm-engine/                       # the library
│   ├── src/                            # orchestrator, agents, tools, events, models
│   ├── tests/                          # all engine tests (223+)
│   └── pyproject.toml                  # pip-installable (`pip install -e ./swarm-engine`)
├── apps/
│   ├── deep-research/                  # current UI + deep research template
│   │   ├── frontend/                   # React 19 + Vite (current frontend, as-is)
│   │   ├── backend/                    # thin API layer consuming swarm-engine
│   │   └── Dockerfile
│   ├── coding-agent/                   # remote code agent platform
│   │   ├── frontend/                   # session manager UI + IDE (Monaco/code-server)
│   │   ├── backend/                    # K8s pod orchestration, session tracking
│   │   └── Dockerfile
│   └── test-harness/                   # minimal UI for exercising the engine
├── templates/                          # shared template format + examples
├── docker-compose.yml                  # can spin up any app
└── pyproject.toml                      # workspace root
```

### swarm-engine/

Extracted from current `src/backend/swarm/` + `src/backend/events.py`. Contains: orchestrator, agents, tools, models, task board, inbox, team registry, template loader, event bus. All 223+ tests move here. Pip-installable as a local path dependency.

### apps/deep-research/

Current React 19 + Vite frontend (snapshot) + thin backend wrapping swarm-engine. Owns: report refinement, Mermaid rendering, production auth/deployment. Consumes swarm-engine via `pip install -e ../../swarm-engine`.

### apps/coding-agent/

New. Centralized session manager that spawns K8s pods per coding session. Each pod runs the full swarm + Copilot SDK/CLI. Streams events back to manager. IDE layer on top (Monaco editor, file API, or code-server). Future: pods produce deployable environments via helm charts per branch for UAT isolation.

### apps/test-harness/

Stripped-down UI for exercising the swarm engine directly. Developer tool for validating templates, debugging agent behavior. No production polish.

## Sequencing

1. Finish current in-progress testing work
2. Extract swarm-engine as a standalone package with clear import boundaries
3. Move current frontend + backend into apps/deep-research/
4. Create apps/test-harness/ (stripped-down version of current UI)
5. Start apps/coding-agent/ — K8s manager + IDE

Steps 2-4 are the restructure. Step 5 is new feature work and can begin once boundaries are defined.

## Key Decisions

- Monorepo over multi-repo — solo dev, no team coordination overhead needed
- `pip install -e ./swarm-engine` for local path dependencies — change engine, all apps see it immediately
- Each pod in the coding agent runs the full swarm, not a stripped-down version
- Templates shared at root level, not duplicated per app
- This repo name (`copilot-sdk-multi-agent-swarm`) is generic enough to stay
