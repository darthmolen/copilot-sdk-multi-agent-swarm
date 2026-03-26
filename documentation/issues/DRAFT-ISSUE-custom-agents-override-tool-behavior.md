# Draft Issue: `customAgents` suppresses custom tool compliance — agents default to coding behavior regardless of model

## Description

When using `customAgents` with custom tools registered via the `tools` parameter, agents overwhelmingly ignore custom tool instructions and fall back to built-in coding behavior (bash, edit, view, etc.). Removing `customAgents` and using only `system_message: mode:"replace"` with the same tools significantly improves custom tool compliance.

This was tested across 8 models. The `customAgents` framework appears to inject a coding-agent identity layer that overrides both `system_message` instructions and per-agent `prompt` content, making non-coding custom tool usage effectively impossible.

## Environment

- `github-copilot-sdk` Python 0.1.0 (installed from source)
- Copilot CLI via `shutil.which("copilot")`
- Python 3.12.3, Linux (WSL2)

## Setup

4 custom tools registered (non-coding coordination tools):
- `task_update` — update task status and attach result
- `inbox_send` — send message to another agent
- `inbox_receive` — check inbox
- `task_list` — list tasks

Session configured with:
- `available_tools=["task_update", "inbox_send", "inbox_receive", "task_list"]` (whitelist ONLY our tools)
- `system_message: mode:"replace"` with explicit instructions: "You MUST call task_update then inbox_send"
- `agent.select()` called after session creation (per workaround for #859)

Prompt: "Research what RAG means in 2 sentences. Then call task_update and inbox_send as instructed."

## Results: WITH customAgents

| Model | task_update | inbox_send | Score |
|-------|------------|------------|-------|
| gemini-3-pro-preview | 1 | 0 | ⚠️ |
| claude-sonnet-4.6 | 1 | 0 | ⚠️ |
| claude-haiku-4.5 | 0 | 0 | ❌ |
| claude-sonnet-4.5 | 0 | 0 | ❌ |
| gpt-5.2 | 0 | 0 | ❌ |
| gpt-5.1 | 0 | 0 | ❌ |
| gpt-5-mini | 0 | 0 | ❌ |
| gpt-4.1 | 0 | 0 | ❌ |

**0 out of 8 models achieved full compliance (both task_update + inbox_send).**

## Results: WITHOUT customAgents (same tools, same prompt)

| Model | task_update | inbox_send | Score |
|-------|------------|------------|-------|
| gemini-3-pro-preview | 2 | 1 | ✅ |
| claude-haiku-4.5 | 1 | 0 | ⚠️ |
| claude-sonnet-4.6 | 0 | 0 | ❌ |
| gpt-5.2 | 0 | 0 | ❌ |
| gpt-5.1 | 0 | 0 | ❌ |
| gpt-5-mini | 0 | 0 | ❌ |
| gpt-4.1 | 0 | 0 | ❌ |

**1 out of 7 models achieved full compliance — but only without customAgents.**

## Key Finding

Gemini 3 Pro went from **⚠️ (1 tool call)** with `customAgents` to **✅ (3 tool calls — task_update×2 + inbox_send×1)** without `customAgents`. Same model, same tools, same prompt, same `available_tools`. The only difference: presence of `customAgents` config.

This suggests `customAgents` injects or reinforces a coding-agent identity that:
1. Suppresses custom tool calling behavior
2. Causes models to prefer text responses or built-in tool patterns
3. Cannot be overridden by `system_message: mode:"replace"` or the agent's `prompt` field

## Reproduction

### With customAgents (tools suppressed)

```python
session = await client.create_session(
    on_permission_request=PermissionHandler.approve_all,
    model="gemini-3-pro-preview",
    system_message={"mode": "replace", "content": "You MUST call task_update then inbox_send."},
    tools=custom_tools,
    available_tools=["task_update", "inbox_send", "inbox_receive", "task_list"],
    custom_agents=[{
        "name": "worker",
        "prompt": "You MUST call task_update then inbox_send.",
        "tools": ["task_update", "inbox_send", "inbox_receive", "task_list"],
        "infer": False,
    }],
    agent="worker",
)
await session.rpc.agent.select(SessionAgentSelectParams(name="worker"))
# Result: 1 task_update, 0 inbox_send
```

### Without customAgents (tools work)

```python
session = await client.create_session(
    on_permission_request=PermissionHandler.approve_all,
    model="gemini-3-pro-preview",
    system_message={"mode": "replace", "content": "You MUST call task_update then inbox_send."},
    tools=custom_tools,
    available_tools=["task_update", "inbox_send", "inbox_receive", "task_list"],
    # No customAgents — no agent framework
)
# Result: 2 task_update, 1 inbox_send ✅
```

## Impact

- Multi-agent systems that rely on custom coordination tools (task management, messaging, state updates) cannot use `customAgents` effectively
- The `customAgents` feature is designed for tool-scoping but paradoxically suppresses custom tool usage
- Workaround: don't use `customAgents` — use separate sessions with `system_message: mode:"replace"` instead
- This limits the SDK's multi-agent capabilities to coding-only workflows

## Expected Behavior

`customAgents` should not alter the model's willingness to call custom tools. If a session has custom tools registered and `available_tools` restricts to only those tools, the model should call them regardless of whether `customAgents` is configured.

## Workaround

Use `system_message: mode:"replace"` with `tools` and `available_tools` — no `customAgents`. Create separate sessions per agent role. This restores custom tool compliance (at least for Gemini 3 Pro).

## Related

- #859 — `customAgents[n].tools` not enforced when agent pre-selected via `SessionConfig.Agent`
