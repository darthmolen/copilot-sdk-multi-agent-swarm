# Template Creation Guide

This guide explains how to create custom swarm templates. A template defines a team of specialized agents, how the leader decomposes goals, how workers execute tasks, and how results are synthesized into a final report.

## How the Orchestrator Works

Before diving into templates, it helps to understand the static workflow that your template plugs into. The orchestrator runs a **four-phase lifecycle** that is the same for every swarm, regardless of template:

```
Phase 1: PLAN          Phase 2: SPAWN         Phase 3: EXECUTE        Phase 4: SYNTHESIZE
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ Leader receives  │    │ Orchestrator    │    │ Round-based     │    │ Synthesis agent  │
│ the goal + your  │───▶│ creates worker  │───▶│ concurrent      │───▶│ receives all     │
│ leader.md prompt │    │ sessions from   │    │ execution with  │    │ task results +   │
│                  │    │ worker-*.md     │    │ dependency      │    │ work dir files   │
│ Calls            │    │ definitions     │    │ resolution      │    │                  │
│ create_plan tool │    │                 │    │                 │    │ Produces final   │
│ with task JSON   │    │ Each gets:      │    │ Each round:     │    │ report using     │
│                  │    │ • system prompt │    │ • Find runnable │    │ synthesis.md     │
│                  │    │ • swarm tools   │    │ • Execute ||    │    │ template         │
│                  │    │ • work dir      │    │ • Emit events   │    │                  │
└─────────────────┘    └─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Phase 1: Planning

The orchestrator creates a session with your `leader.md` prompt as the system message and a single tool: `create_plan`. The user's goal (expanded through your `goal_template`) is sent as the user message. The leader must call `create_plan` with a JSON plan containing tasks, worker assignments, and dependency relationships.

### Phase 2: Spawning

For each unique `worker_name` in the plan, the orchestrator creates a worker session. The worker's system prompt is assembled in layers:

1. **System preamble** (`system-prompt.md`) -- coordination protocol, mandatory for all workers
2. **Work directory directive** -- tells the agent where to write files
3. **Template prompt** (the markdown body of `worker-*.md`) -- domain expertise, with `{display_name}` and `{role}` expanded

The worker also receives the four swarm coordination tools (`task_update`, `inbox_send`, `inbox_receive`, `task_list`).

### Phase 3: Execution

The orchestrator runs rounds. Each round:
1. Queries the task board for **runnable tasks** (tasks whose dependencies are all completed)
2. Assigns one task per worker (each worker handles one task per round)
3. Executes all assigned tasks concurrently via `asyncio.gather`
4. Emits events for frontend updates

Rounds continue until all tasks are completed (or `max_rounds` is reached).

### Phase 4: Synthesis

The orchestrator collects all task results and any `.md` files from the work directory, then sends them to a synthesis session using your `synthesis.md` template. The synthesis prompt receives two variables: `{goal}` (the original user goal) and `{task_results}` (formatted results from all workers, plus work directory file contents).

## What the Leader Receives

Understanding exactly what the leader agent sees is critical for writing effective `leader.md` prompts. Here is what gets assembled:

| Component | Source | Purpose |
|---|---|---|
| **System message** | `leader.md` body (after frontmatter) | Domain-specific decomposition guidance |
| **Available tool** | `create_plan` (auto-injected by orchestrator) | Structured output capture -- the leader calls this to submit its plan |
| **User message** | `goal_template` with `{user_input}` replaced by the user's goal | The actual work request |

The leader does **not** receive the system preamble (`system-prompt.md`) -- that is only for workers. The leader also does **not** receive the swarm coordination tools (`task_update`, `inbox_send`, etc.) -- it only has `create_plan`.

The leader's job is simple: read the goal, decompose it into tasks, and call `create_plan` with a JSON object matching this schema:

```json
{
  "team_description": "Brief description of what this team does",
  "tasks": [
    {
      "subject": "Short task title",
      "description": "Detailed instructions for the worker",
      "worker_role": "Specialist role needed",
      "worker_name": "snake_case_name",
      "blocked_by_indices": [0, 1]
    }
  ]
}
```

The `worker_name` values in the plan are matched against your `worker-*.md` file names. If the leader creates a task with `"worker_name": "primary_researcher"`, the orchestrator looks for a worker definition with `name: primary-researcher` in its frontmatter.

## Template Directory Structure

Each template lives in its own directory under `src/templates/`:

```
src/templates/
  system-prompt.md              # Shared across ALL templates (not user-editable per template)
  my-custom-template/
    _template.yaml              # Template metadata and goal framing
    leader.md                   # Leader agent prompt
    worker-analyst.md           # Worker agent definition
    worker-writer.md            # Worker agent definition
    ...                         # Additional worker-*.md files
    synthesis.md                # Synthesis report template
```

## Template Artifacts

### `_template.yaml` -- Template Metadata

The metadata file defines your template's identity and how user input gets framed as a goal for the leader.

```yaml
key: my-custom-template
name: My Custom Team
description: A team that does X with specialists for Y and Z
goal_template: |
  Assemble a team to: {user_input}

  Create specialists for: analysis, writing, and review.
  Analysis and writing can run in parallel.
  Review should be blocked by both analysis and writing.
```

| Field | Required | Description |
|---|---|---|
| `key` | Yes | URL-safe identifier, must match the directory name |
| `name` | Yes | Human-readable team name shown in the UI dropdown |
| `description` | Yes | Brief description shown in the UI |
| `goal_template` | Yes | Template string that wraps the user's input into a structured goal. Must contain `{user_input}`. |
| `maxRetries` | No | Default retry count for all workers (default: 2). Individual workers can override via their own `maxRetries` frontmatter. |

The `goal_template` is your primary mechanism for **steering the leader's decomposition**. It is the user message sent to the leader. Use it to:
- Suggest which specialist roles to create
- Hint at dependency relationships between tasks
- Set the overall framing and scope

The leader is not forced to follow these hints exactly -- it uses them as guidance when calling `create_plan`.

### `leader.md` -- Leader Agent Prompt

The leader prompt is the system message for the planning phase. It tells the leader who its team members are, how to decompose goals, and what dependency patterns to use.

```markdown
---
name: leader
displayName: Team Leader
description: Decomposes goals into tasks and synthesizes results
---

# My Custom Team Leader

You are the leader of a custom team. Your responsibility is to take a goal
and decompose it into actionable tasks for your specialists.

## Your Team

You have three specialists available:

- **Analyst** -- Investigates and produces findings
- **Writer** -- Produces written deliverables
- **Reviewer** -- Reviews and critiques outputs

## Task Decomposition Strategy

When creating tasks:
1. Analysis and writing can run in parallel
2. Review is blocked by both analysis and writing
...
```

**Frontmatter fields** (between the `---` delimiters):

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Always `leader` |
| `displayName` | Yes | Display name for UI |
| `description` | Yes | Role description |

**Body content**: Free-form markdown that becomes the leader's system prompt. This is where you describe the team composition, decomposition strategy, and task creation guidelines. The more specific your instructions, the more predictable the leader's plans will be.

### `worker-*.md` -- Worker Agent Definitions

Each worker file defines a specialist agent. The filename must follow the pattern `worker-<name>.md`.

```markdown
---
name: analyst
displayName: Research Analyst
description: Investigates topics and produces evidence-based findings
tools:
  - task_update
  - inbox_send
  - inbox_receive
  - task_list
infer: false
---

# {display_name} -- {role}

You are a senior research analyst responsible for thorough investigation.

## Core Expertise

- Primary source research
- Evidence evaluation
- Gap identification

## Deliverables

Your output should include:
1. Key findings with source attribution
2. Evidence quality assessment
3. Knowledge gaps identified

## Standard Workflow

1. Call **task_list** to see your assigned tasks
2. Call **task_update** to set status to `in_progress`
3. Do your work
4. Call **task_update** with status `completed` and your result
5. Call **inbox_send** to notify the leader
```

**Frontmatter fields**:

| Field | Required | Default | Description |
|---|---|---|---|
| `name` | Yes | file stem | Snake-case identifier matching `worker_name` in plans |
| `displayName` | Yes | same as `name` | Human-readable name for UI |
| `description` | Yes | `""` | Role description, also used as `{role}` in prompt expansion |
| `tools` | No | `null` (all tools) | Whitelist of allowed tools. `null` means all tools are available. List specific tool names to restrict. Includes both swarm tools (`task_update`, `inbox_send`, etc.) and SDK built-in tools (`bash`, `write`, etc.). |
| `infer` | No | `false` | Reserved for future use |
| `maxInstances` | No | `1` | Max concurrent tasks this worker can handle per round. Values > 1 enable ephemeral agent sessions for parallel execution. |
| `maxRetries` | No | `null` (use template default) | Max automatic retries on task failure. Retries use session resume to preserve conversation history. `null` inherits from `_template.yaml` default (2). |
| `skills` | No | `null` (all skills) | List of skill directory names this worker can use. `["*"]` = all, `[]` = none. |

**Body content**: The markdown body becomes the worker's domain-specific prompt. It is combined with the system preamble and work directory directive to form the full system message. See [Replacement Variables](replacement-variables.md) for available template variables.

### `synthesis.md` -- Synthesis Report Template

The synthesis template defines the format and structure of the final report. It receives the completed task results and the original goal.

```markdown
# Final Report

You are synthesizing results from a team that worked on:

**Goal:** {goal}

## Task Results

{task_results}

## Synthesis Instructions

Produce a report with these sections:

### Executive Summary
Summarize the key findings in 3-5 sentences.

### Detailed Findings
Present each specialist's contributions organized by theme.

### Recommendations
Provide actionable next steps based on the findings.
```

**No frontmatter required.** The entire file content is used as the synthesis prompt template.

| Variable | Description |
|---|---|
| `{goal}` | The original user goal (after `goal_template` expansion) |
| `{task_results}` | Formatted results from all workers, plus any `.md` files from the work directory |

The `{task_results}` variable includes both the structured task results (subject, worker name, status, result text) and the full content of any markdown files workers wrote to the work directory. This means workers can produce detailed research files, and the synthesis agent will see everything.

### `system-prompt.md` -- System Coordination Protocol

This file is **shared across all templates** and is **not part of your template directory**. It lives at `src/templates/system-prompt.md` and is automatically prepended to every worker's system prompt.

It defines:
- The required coordination tool call sequence (task_update, inbox_send, inbox_receive, task_list)
- Anti-polling instructions (call inbox_receive once, then stop)
- The stop condition (after completing steps 1-5, stop working)

You generally do not need to modify this file. It ensures all workers follow the same coordination protocol regardless of template.

## Designing Task Relationships

Task dependencies are expressed via `blocked_by_indices` in the leader's plan. These are **non-deterministic** -- the leader decides them at runtime based on your guidance in `leader.md` and `goal_template`. You cannot hardcode dependencies in the template; you can only influence the leader's choices.

Here are prompt patterns that reliably produce different relationship topologies:

### All Parallel (Fan-out)

All tasks run simultaneously with no dependencies.

**goal_template example:**
```yaml
goal_template: |
  Assemble an analysis team to: {user_input}

  Create three independent analysts. All three analysis tasks can run
  in parallel since they examine the topic from independent angles.
  No task depends on any other task.
```

**leader.md guidance:**
```markdown
## Task Decomposition Strategy

All three tracks run in parallel. Each specialist brings an independent
perspective -- they should not wait for each other.
```

### Linear Chain (Sequential Pipeline)

Each task depends on the previous one.

**goal_template example:**
```yaml
goal_template: |
  Assemble a content pipeline team to: {user_input}

  Create specialists for: research, writing, and editing.
  The writer must wait for the researcher to finish (needs research findings).
  The editor must wait for the writer to finish (needs a draft to edit).
```

**leader.md guidance:**
```markdown
## Task Decomposition Strategy

Tasks must execute in strict sequence:
1. **Research** runs first -- produces the factual foundation
2. **Writing** is blocked by research -- needs findings to write from
3. **Editing** is blocked by writing -- needs a complete draft to edit
```

### Fan-in (Multiple Tasks Feed One)

Several parallel tasks converge into a final task that depends on all of them.

**goal_template example:**
```yaml
goal_template: |
  Assemble a strategy team to: {user_input}

  Create specialists for: market analysis, competitive analysis,
  technical assessment, and strategic planning.
  Market, competitive, and technical analysis can all run in parallel.
  Strategic planning should be blocked by all three analysis tasks.
```

**leader.md guidance:**
```markdown
## Task Decomposition Strategy

1. **Market analysis**, **competitive analysis**, and **technical assessment**
   all run in parallel -- they draw on different data sources.
2. **Strategic planning** is blocked by all three analysis tasks -- the
   planner needs findings from every analyst before creating the strategy.
```

### Diamond (Parallel Middle with Shared Start and End)

One task feeds two parallel tasks, which both feed a final task.

**goal_template example:**
```yaml
goal_template: |
  Assemble a product team to: {user_input}

  Create specialists for: requirements gathering, UX design,
  technical design, and integration planning.
  Requirements gathering runs first.
  UX design and technical design both depend on requirements and can run
  in parallel with each other.
  Integration planning is blocked by both UX and technical design.
```

**leader.md guidance:**
```markdown
## Task Decomposition Strategy

1. **Requirements** runs first -- defines what we're building
2. **UX design** and **technical design** are both blocked by requirements,
   but can run in parallel with each other
3. **Integration planning** is blocked by both UX and technical design --
   needs both perspectives to plan integration
```

### Partial Dependencies (Mixed)

Some tasks are parallel, some are sequential, some fan-in -- a realistic mix.

**goal_template example:**
```yaml
goal_template: |
  Assemble a software development team to: {user_input}

  Create specialists for: architecture/design, implementation, testing,
  and documentation.
  The implementation task should be blocked by the design task.
  The testing task should be blocked by the implementation task.
  Documentation can run in parallel with testing.
```

**leader.md guidance:**
```markdown
## Task Decomposition Strategy

1. **Architecture/Design** comes first
2. **Implementation** is blocked by design
3. **Testing** is blocked by implementation
4. **Documentation** can run in parallel with testing -- the documenter
   can work from the architect's design and the implementer's code
```

## Step-by-Step: Creating a New Template

1. **Create the directory**: `src/templates/my-template/`

2. **Write `_template.yaml`**: Define the key, name, description, and goal_template. The goal_template is your best lever for steering the leader's behavior.

3. **Write `leader.md`**: Describe the team, decomposition strategy, and task creation guidelines. Be specific about which roles exist and what dependency patterns to use.

4. **Write `worker-*.md` files**: One file per specialist role. Include domain expertise, deliverable expectations, and the standard workflow section. Use `{display_name}` and `{role}` placeholders in the body.

5. **Write `synthesis.md`**: Define the report structure. Use `{goal}` and `{task_results}` placeholders.

6. **Test with the validator**: The template editor in the UI validates files in real-time, or you can check programmatically using `validate_template_file()`.

## Validation Rules

The template validator (`template_validator.py`) enforces:

| File | Rule |
|---|---|
| `_template.yaml` | Must have `key`, `name`, `description`, `goal_template` fields. `goal_template` must contain `{user_input}`. |
| `worker-*.md` | Frontmatter must have `name`, `displayName`, `description`. |
| `leader.md` | Must have non-empty body after frontmatter. |
| `synthesis.md` | Must have non-empty body after frontmatter. |
| Any file with `tools` | Tools list can only contain known swarm tools (`task_update`, `inbox_send`, `inbox_receive`, `task_list`) and/or SDK built-in tools (`bash`, `write`, etc.). |

## Execution Features

### Automatic Retry

When a task fails (circuit breaker, tool errors, or timeout), the orchestrator automatically retries it if the worker has retry budget remaining. Retries use `session.resume()` to preserve the agent's full conversation history, then send a nudge message explaining the failure. Configure via:

- `maxRetries` in `_template.yaml` — swarm-wide default (default: 2)
- `maxRetries` in `worker-*.md` frontmatter — per-worker override

### Multi-Instance Workers

Workers with `maxInstances > 1` can handle multiple tasks per round via ephemeral agent sessions. The base agent handles the first task; additional tasks get their own temporary sessions. Useful for workers with many similar tasks (e.g., an `iac-developer` writing 7 Bicep modules).

### Suspend and Resume

If the swarm exhausts all execution rounds with tasks still pending, it pauses and waits for user input (Continue, Skip to synthesis, or auto-suspend after 30 minutes). Suspended swarms persist to Postgres and can resume across process restarts.

### MCP Server Access

All agent sessions (leader, workers, synthesis) receive the swarm-state MCP server, giving them 9 tools to query swarm status, read task results, list artifacts, and resume failed peers. This enables agents to self-coordinate beyond the basic inbox system.

### Skills

Templates can include a `skills/` subdirectory with per-worker skill definitions. Workers declare which skills they can use via the `skills` frontmatter field. The orchestrator computes `disabled_skills` from the skill map and restricts each worker accordingly.

## Tips for Effective Templates

- **Be specific in leader.md**: Vague instructions produce unpredictable plans. Name your specialists explicitly and describe exact dependency rules.
- **Repeat dependency hints**: State the desired task relationships in both `goal_template` and `leader.md`. The leader sees both, and redundancy improves compliance.
- **Design worker prompts for autonomy**: Workers have no context beyond their system prompt and task description. Include everything they need to know -- methodology, deliverable format, quality standards.
- **Use the synthesis template to control report quality**: The synthesis agent produces the user-facing output. A detailed synthesis template with specific section headings produces better reports than a vague "summarize the results" instruction.
- **Keep worker tool lists explicit**: Listing tools in frontmatter (even if it's all four coordination tools) makes the template self-documenting and prevents accidental access to unintended built-in tools.
- **Add file-write tools when workers produce artifacts**: Workers that need to create files in the work directory should have `bash` and `write` in their tools list. Without these, output goes into task results only.
- **Set maxInstances for high-volume workers**: If a worker type handles many independent tasks (e.g., writing individual modules), increase `maxInstances` to enable parallel execution within a single round.
- **Use maxRetries for unreliable tasks**: Tasks that depend on external tools or complex reasoning benefit from retry budget. The agent keeps its conversation history on retry, so it can learn from its mistakes.
