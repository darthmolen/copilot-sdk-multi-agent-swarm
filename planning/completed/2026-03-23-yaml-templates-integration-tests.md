# YAML Template System + Integration Tests

## Context

Swarm templates are currently hardcoded Python dataclasses with only a `goal_template` string. The leader, worker, and synthesis prompts are generic and identical across all templates. We need:

1. **YAML-based templates** — portable `.md` files with YAML frontmatter (matching the Claude/Copilot agent definition pattern). Each template defines its own leader prompt, worker agent definitions, and synthesis prompt. The markdown body IS the prompt content.
2. **Loader system** — parse YAML frontmatter + markdown body, build `SwarmTemplate` objects
3. **Integration tests** — test the full pipeline against real copilot-cli

## Phase 0: YAML Template System (TDD)

### Template File Format

Each template is a directory under `templates/` containing multiple `.md` files:

```
templates/
  software-development/
    _template.yaml          # Template metadata + goal_template + dependency graph
    leader.md               # Leader system prompt (YAML frontmatter + markdown body)
    worker-architect.md     # Worker agent definition
    worker-implementer.md
    worker-tester.md
    worker-documenter.md
    synthesis.md            # Synthesis prompt template
  deep-research/
    _template.yaml
    leader.md
    worker-primary-researcher.md
    worker-skeptic.md
    worker-data-analyst.md
    synthesis.md
  warehouse-optimizer/
    _template.yaml
    leader.md
    worker-inventory-analyst.md
    worker-layout-optimizer.md
    worker-demand-forecaster.md
    worker-planner.md
    synthesis.md
```

### `_template.yaml` — Template metadata

```yaml
key: software-development
name: Software Development Team
description: A team of software engineers that designs, implements, tests, and documents
goal_template: |
  Assemble a software development team to: {user_input}

  Create specialists for: architecture/design, implementation, testing, and documentation.
  The implementation task should be blocked by the design task.
  The testing task should be blocked by the implementation task.
  Documentation can run in parallel with testing.
```

### Agent `.md` files — YAML frontmatter + markdown body

```markdown
---
name: architect
displayName: Software Architect
description: Designs system architecture, interfaces, and data models
tools: null
infer: false
---

You are {display_name}, a specialist in {role}.

You are part of a software development swarm team. Your job is to design
the system architecture before implementation begins.

## Your Coordination Tools

You have 4 tools for coordinating with the team:
- **task_update**: Mark your task as in_progress, completed, or failed.
- **inbox_send**: Send a message to another agent or the leader.
- **inbox_receive**: Check your inbox for messages from other agents.
- **task_list**: View all team tasks and their current status.

## Your Expertise
- System design and API contracts
- Data modeling and schema design
- Dependency analysis and component boundaries
- Design documents with clear interfaces

## Your Workflow
1. Call `task_list` to see your assigned task
2. Call `task_update` to mark your task as `in_progress`
3. Produce a detailed design document
4. Call `task_update` with status `completed` and include your design
5. Send a summary to the leader via `inbox_send`
```

### `synthesis.md` — Synthesis prompt (no frontmatter, just markdown)

```markdown
You are the Leader Agent. All worker tasks have completed. Here are the results:

{task_results}

Synthesize these results into a comprehensive technical report that addresses:
{goal}

Structure your report as:
1. Executive Summary
2. Architecture Decisions
3. Implementation Details
4. Test Coverage
5. Documentation Status
6. Recommendations
```

### Loader Implementation

**File: `src/backend/swarm/template_loader.py`**

```python
@dataclass
class AgentDefinition:
    """Parsed from a worker .md file."""
    name: str
    display_name: str
    description: str
    tools: list[str] | None  # None = all tools
    infer: bool
    prompt_template: str  # markdown body with {display_name}, {role} placeholders

@dataclass
class LoadedTemplate:
    """Full template loaded from YAML directory."""
    key: str
    name: str
    description: str
    goal_template: str
    leader_prompt: str           # from leader.md body
    agents: list[AgentDefinition]  # from worker-*.md files
    synthesis_prompt: str        # from synthesis.md body

class TemplateLoader:
    def __init__(self, templates_dir: str | Path):
        self.templates_dir = Path(templates_dir)

    def load(self, template_key: str) -> LoadedTemplate:
        """Load a template by key from its directory."""

    def load_all(self) -> dict[str, LoadedTemplate]:
        """Load all templates from the templates directory."""

    def list_available(self) -> list[dict]:
        """Return summary dicts for API."""

    @staticmethod
    def parse_agent_file(path: Path) -> AgentDefinition:
        """Parse YAML frontmatter + markdown body from an agent .md file."""

    @staticmethod
    def parse_frontmatter(content: str) -> tuple[dict, str]:
        """Split YAML frontmatter from markdown body. Returns (metadata, body)."""
```

### Wire Into Orchestrator

**File: `src/backend/swarm/orchestrator.py`**

```python
class SwarmOrchestrator:
    def __init__(self, client, event_bus, config=None, template: LoadedTemplate | None = None):
        self.template = template
        # ...

    async def _plan(self, goal):
        leader_prompt = self.template.leader_prompt if self.template else LEADER_SYSTEM_PROMPT
        session = await self.client.create_session(system_prompt=leader_prompt)
        # ...

    async def _spawn(self, plan):
        # Match worker_name from plan to template agent definitions
        # Use agent-specific prompt from template, or generic fallback
```

**File: `src/backend/api/rest.py`**

```python
async def start_swarm(request, background_tasks):
    template = loader.load(request.template) if request.template else None
    goal = template.goal_template.format(user_input=request.goal) if template else request.goal
    # Pass template to orchestrator
```

### TDD Steps

**`tests/unit/test_template_loader.py`**

1. RED: `parse_frontmatter` splits YAML from body correctly
2. GREEN: Implement regex/split for `---` delimiters
3. RED: `parse_agent_file` returns AgentDefinition with correct fields from .md file
4. GREEN: Combine parse_frontmatter + field extraction
5. RED: `load("software-development")` returns LoadedTemplate with leader_prompt, 4 agents, synthesis_prompt
6. GREEN: Implement directory scanning + file loading
7. RED: `load_all()` returns 3 templates
8. GREEN: Iterate subdirectories
9. RED: `list_available()` returns summary dicts with key/name/description
10. GREEN: Extract metadata from _template.yaml
11. RED: Agent prompt_template contains `{display_name}` and `{role}` placeholders
12. GREEN: Validate during parse
13. RED: Missing `_template.yaml` raises `FileNotFoundError`
14. GREEN: Add validation
15. RED: Template with no worker files raises `ValueError`
16. GREEN: Add validation

### Files to Create/Modify

New files:
- `src/backend/swarm/template_loader.py` — loader implementation
- `tests/unit/test_template_loader.py` — loader tests
- `templates/software-development/_template.yaml`
- `templates/software-development/leader.md`
- `templates/software-development/worker-architect.md`
- `templates/software-development/worker-implementer.md`
- `templates/software-development/worker-tester.md`
- `templates/software-development/worker-documenter.md`
- `templates/software-development/synthesis.md`
- `templates/deep-research/_template.yaml` + agent files
- `templates/warehouse-optimizer/_template.yaml` + agent files

Modified files:
- `src/backend/swarm/orchestrator.py` — accept LoadedTemplate
- `src/backend/api/rest.py` — use TemplateLoader instead of hardcoded templates
- `src/backend/swarm/templates.py` — deprecate or remove (replaced by template_loader)

### Dependencies

Add `pyyaml` to pyproject.toml dependencies.

## Phase 1: Integration Tests

### Prerequisites

- copilot-cli installed and authenticated
- `pip install -e research/copilot-sdk/python/` for real SDK
- YAML templates loaded from `templates/` directory

### Shared Fixtures (`tests/integration/conftest.py`)

```python
@pytest.fixture(scope="module")
async def copilot_client():
    from copilot import CopilotClient, SubprocessConfig
    client = CopilotClient(SubprocessConfig(use_stdio=True))
    await client.start()
    yield client
    await client.stop()

@pytest.fixture
def template_loader():
    return TemplateLoader(Path("templates"))

@pytest.fixture
def event_collector(event_bus):
    events = []
    event_bus.subscribe(lambda t, d: events.append((t, d)))
    return events
```

### Test Files

**`tests/integration/test_session_basics.py`** (4 tests)
- Create session, send "say hello", get response
- Subscribe to events, verify turn_start/turn_end fire
- Custom agent selection works
- Session disconnect is clean

**`tests/integration/test_swarm_tools_live.py`** (3 tests)
- task_update tool mutates real TaskBoard through real SDK session
- inbox_send tool delivers message through real SDK
- task_list tool returns real task data

**`tests/integration/test_event_bridge_live.py`** (2 tests)
- Real SDK events map through bridge_sdk_event correctly
- tool_requests one-step-off pattern occurs with real tool calls

**`tests/integration/test_orchestrator_live.py`** (4 tests)
- Full lifecycle with software-development template
- Full lifecycle with deep-research template
- Full lifecycle with warehouse-optimizer template
- Cancellation stops execution

**`tests/integration/test_api_live.py`** (2 tests)
- POST /swarm/start → poll status → complete
- WebSocket receives streaming events

### Timeout Strategy

- Per-test: `@pytest.mark.timeout(300)` (5 min generous timeout)
- On timeout: test fails, logs last events for debugging
- All tests: `@pytest.mark.integration` — skipped by default

## Execution Order

1. **Phase 0a**: Create template YAML files (3 templates × ~6 files each)
2. **Phase 0b**: TDD TemplateLoader (parse_frontmatter, parse_agent_file, load, load_all)
3. **Phase 0c**: Wire orchestrator + API to use LoadedTemplate
4. **Phase 1**: Integration tests (requires copilot-cli)

Phases 0a-0c can be parallelized (YAML files are independent of loader code during TDD).

## Verification

1. `pytest tests/unit/test_template_loader.py -v` — all loader tests green
2. `pytest tests/unit/ -v` — all 101+ unit tests still green
3. `pyright src/ tests/` — 0 errors
4. `pytest tests/integration/ -m integration -v` — requires live copilot-cli
