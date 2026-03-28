# Replacement Variables Reference

Template files use Python `str.format()` style replacement variables (`{variable_name}`). These are expanded at runtime by the orchestrator before being sent to the LLM.

## Variables by File

### `_template.yaml` -- `goal_template` field

| Variable | Type | Source | Description |
|---|---|---|---|
| `{user_input}` | string | User's goal text from the UI or API | The raw goal the user entered. Inserted into the goal_template to produce the full goal string sent to the leader. |

**Example:**
```yaml
goal_template: |
  Assemble a research team to: {user_input}

  Create specialists for primary research and critical analysis.
```

If the user enters "investigate the impact of remote work on productivity", the leader receives:
```
Assemble a research team to: investigate the impact of remote work on productivity

Create specialists for primary research and critical analysis.
```

### `worker-*.md` -- Markdown body

| Variable | Type | Source | Description |
|---|---|---|---|
| `{display_name}` | string | `displayName` field from the worker's YAML frontmatter | Human-readable name of the agent (e.g., "Primary Researcher", "Data Analyst") |
| `{role}` | string | `description` field from the worker's YAML frontmatter, or the `worker_role` from the leader's plan | The specialist role description |

**Example:**
```markdown
---
name: analyst
displayName: Research Analyst
description: Investigates topics and produces evidence-based findings
---

# {display_name} -- {role}

You are the {display_name}, a specialist in {role}.
```

Expands to:
```markdown
# Research Analyst -- Investigates topics and produces evidence-based findings

You are the Research Analyst, a specialist in Investigates topics and produces evidence-based findings.
```

**Fallback behavior**: If the template body contains `{display_name}` or `{role}` but expansion fails (e.g., a `KeyError` from an unrecognized placeholder), the raw template body is used as-is without any expansion.

### `synthesis.md` -- Full file content

| Variable | Type | Source | Description |
|---|---|---|---|
| `{goal}` | string | The expanded goal (after `goal_template` + `{user_input}` substitution) | The full goal string that was originally sent to the leader |
| `{task_results}` | string | Orchestrator-assembled from task board + work directory | Formatted results from all completed tasks, plus the full content of any `.md` files from the swarm's work directory |

**Example:**
```markdown
# Report

**Goal:** {goal}

## Task Results

{task_results}

## Instructions

Synthesize the above into a final report.
```

The `{task_results}` value is assembled by the orchestrator as:
```
## Task Subject (by worker_name)
Status: completed
Result: <the worker's result text>

## Another Task (by another_worker)
Status: completed
Result: <result text>

---

# Research Files from Work Directory

### File: analysis.md

<full file content>

---

### File: findings.md

<full file content>
```

### `leader.md` -- Markdown body

The leader prompt body does **not** have any built-in replacement variables. It is used as-is as the system message for the planning session.

### `system-prompt.md` -- Markdown body

The system preamble does **not** have any built-in replacement variables. It is prepended to every worker's system prompt without modification.

## Variable Expansion Order

The orchestrator expands variables at different points in the lifecycle:

```
1. Swarm start
   goal_template.format(user_input=<user goal>)  -->  expanded goal

2. Worker session creation (per worker)
   worker_body.format(display_name=<displayName>, role=<description>)  -->  expanded worker prompt

3. Synthesis (after all tasks complete)
   synthesis_template.format(goal=<expanded goal>, task_results=<assembled results>)  -->  synthesis prompt
```

## Escaping Literal Braces

Since templates use Python's `str.format()`, literal curly braces in your content must be doubled:

```markdown
The JSON schema uses the format: {{  "key": "value" }}
```

This produces: `The JSON schema uses the format: { "key": "value" }`

If you need to include JSON examples in a worker prompt, escape the braces or place them in a code fence (code fences do not protect against `str.format()` -- you still need to double the braces).
