# Guardrails: Turn Budgets, Tool Rate Limits, and Agent Caps

## Context

Dr. Aria Chen burned 83 turns polling an empty inbox (74 `inbox_receive` calls) in a single task. Non-deterministic agents can't be trusted to follow prompt instructions reliably. In production this would eat a token budget silently. Prompt-level fixes help but aren't sufficient — need hard enforcement.

## Requirements

All limits should be **configurable** — per-template, per-agent, or globally via swarm config. Defaults should be sane but overridable.

## Features

### 1. Turn Budget per Agent Task

- Count `turn_start` events per `execute_task` invocation
- Hard-stop the agent when it exceeds `max_turns_per_task` (default: 15)
- Emit `agent.turn_limit_reached` event so frontend can show it
- Mark task as `failed` with reason "Turn limit exceeded"

### 2. Custom Tool Rate Limits

- Per-tool call counter per task execution (e.g., `inbox_receive` max 3 calls per task)
- Return error ToolResult when limit hit: "Rate limited — max N calls reached for this task"
- Configurable per-tool in template YAML or system-prompt frontmatter
- Default limits: `inbox_receive: 3`, others: unlimited

### 3. Token Budget per Agent

- Track cumulative tokens via `session.usage_info` SDK events
- Hard cap per agent per task (e.g., 50k tokens)
- Hard cap per swarm run (e.g., 500k tokens total)
- Emit `agent.token_limit_reached` / `swarm.token_limit_reached`

### 4. Swarm-Level Caps

- Max total turns across all agents per swarm run
- Max wall-clock time per swarm (already have timeout, but make it configurable per-template)
- Max concurrent agents

## Configuration Shape (draft)

```yaml
# In _template.yaml or swarm config
guardrails:
  max_turns_per_task: 15
  max_tokens_per_task: 50000
  max_tokens_per_swarm: 500000
  tool_rate_limits:
    inbox_receive: 3
    task_list: 5
```

## Security Considerations

- These guardrails are cost/stability controls, not security controls
- Security layer (auth, sandboxing, tool permissions) is a separate concern — not yet implemented
- Rate limits prevent accidental token burn but don't prevent malicious tool use

## Priority

Medium — prompted by real incident but mitigated short-term by prompt changes. Should implement before any multi-tenant or paid usage.
