# Agents

## Overview

The swarm uses three agent roles — **Leader**, **Worker**, and **Synthesis** — each backed by a headless Copilot CLI session. All agents are configured with `system_message: {mode: "replace"}` rather than `customAgents`, which empirically suppresses custom tool compliance across models.

## Agent Roles

### Leader Agent

The leader manages the swarm lifecycle through multiple session phases:

| Phase | Session | Tools | Purpose |
| --- | --- | --- | --- |
| Q&A | `qa_session` | `begin_swarm` | Interview user to refine goal. Calls `begin_swarm` when ready. |
| Planning | New session | `create_plan` | Decompose refined goal into tasks with dependency graph (SwarmPlan schema). |
| Synthesis | New session | `submit_report` | Consolidate worker results + work directory files into final report. |
| Refinement | Resumed synthesis session | (all tools) | User-driven chat to refine the report. |

The leader's system prompt comes from the template's `leader_prompt` field. During Q&A, the leader also receives the template's MCP servers and skill directories.

### Worker Agents

Each worker is a `SwarmAgent` instance wrapping a single Copilot CLI session. Workers execute tasks concurrently, one task at a time, across execution rounds.

**Session configuration:**

```python
SwarmAgent(
    name="worker-name",
    role="worker-role",
    display_name="Display Name",
    model="gemini-3-pro-preview",     # configurable per-template
    work_dir=Path("workdir/{swarm_id}/"),
    swarm_id="...",
    mcp_servers={...},                 # from template
    skill_directories=["..."],         # from template
    disabled_skills=["skill-a", ...],  # computed from allowlist
)
```

**Task execution** is event-driven:
1. `session.send()` with task ID and description
2. Subscribe to events via `session.on(handler)`
3. Handler sets `asyncio.Event` on `session.idle` (not `turn_end` — agents do multiple turns per task)
4. Capture text from `assistant.message` events as result
5. Circuit breaker: 5 consecutive tool failures → abort task

**SDK events** are forwarded to the EventBus via `_on_event()` with `swarm_id` attached. The unified `bridge_raw_sdk_event()` in `main.py` converts these to WebSocket events for the frontend.

### Synthesis Agent

Created during the synthesis phase. Receives:
- All task results (subject, status, worker, result text)
- All `.md` files from the work directory (`workdir/{swarm_id}/`)
- The original goal

Calls `submit_report` tool with the final report. The session is preserved for refinement chat.

## System Prompt Architecture

Worker prompts are assembled from three layers by `assemble_worker_prompt()`:

1. **System preamble** (`src/templates/system-prompt.md`) — Mandatory coordination protocol with tool usage instructions. YAML frontmatter declares the 4 coordination tools. Includes anti-polling instruction for `inbox_receive`.
2. **Work directory directive** — Injected when `work_dir` is set: "Your work directory is: `/path/`. Write ALL output files here."
3. **Template prompt** — Domain expertise from the worker's `.md` file in the template directory. `{display_name}` and `{role}` placeholders are expanded.
4. **Fallback** — If no template prompt exists, a generic role description is generated.

This separation ensures template authors cannot accidentally remove coordination tool mandates.

## Coordination Tools

Workers receive four closure-captured tools created by `create_swarm_tools()`:

| Tool | Required Args | Description |
| --- | --- | --- |
| `task_update` | `task_id`, `status` | Update task status and result. Validates fields, emits `task.updated`. |
| `inbox_send` | `to`, `message` | Send message to another agent. Includes ISO timestamp. |
| `inbox_receive` | (none) | Destructive read of pending messages. Call once, not in a loop. |
| `task_list` | (none) | List all tasks. Optional `owner` filter. |

All handlers wrap in try/except and return `ToolResult` with `result_type="error"` instead of raising — the SDK returns opaque "Tool execution failed" for unhandled exceptions, which agents can't act on.

## Template Configuration

Templates control agent behavior through `template.yaml`:

```yaml
agents:
  architect:
    role: Solutions Architect
    display_name: Architecture Designer
    model: gemini-3-pro-preview      # optional model override
    max_retries: 2                    # retry failed tasks
    skills:                           # allowlist → others disabled
      - azure-bicep
      - networking
  developer:
    role: IaC Developer
    # ...
```

**Skills handling:** If a worker defines a `skills` allowlist, all skills NOT in the list are computed as `disabled_skills` and passed to `create_session()`. This prevents workers from using skills outside their domain.

**MCP servers:** Template-level MCP servers are merged with the swarm-state MCP server (always available) and passed to every agent session.

## Agent Lifecycle

```
create_session() → session.send(task) → session.on(handler) → session.idle → done
                                              ↑                      ↓
                                        SDK events forwarded    result captured
                                        to EventBus             from assistant.message
```

**Resume flow:** On cold-start resume from Postgres, `_rebuild_agents()` recreates `SwarmAgent` instances from DB state. `_configure_agent()` applies template config (max_retries, disabled_skills, mcp_servers). Workers resume their sessions via `session.resume()` with a nudge message.

**Timeout:** Tasks have a configurable timeout (default 1800s). Late completions after timeout are monitored in the background and logged.
