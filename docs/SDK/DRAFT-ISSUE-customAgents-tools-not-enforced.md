# Draft Issue: `customAgents[n].tools` is not enforced — agent has access to all session tools regardless of tool restriction

## Description

When creating a session with `customAgents` that have explicit `tools` arrays, the agent is **not restricted** to the listed tools. The agent can access and use all tools available at the session level, even when `tools` is set to a specific subset.

The `availableTools` parameter on `create_session` **does** correctly restrict tools. But the per-agent `tools` field within `customAgents` has no observable enforcement effect.

## Expected Behavior

Per the SDK documentation (`docs/features/custom-agents.md`):

> Use the `tools` property to restrict which tools an agent can access.

And per the TypeScript type definition:

```typescript
export interface CustomAgentConfig {
    /**
     * List of tool names the agent can use.
     * Use null or undefined for all tools.
     */
    tools?: string[] | null;
}
```

When `customAgents[0].tools = ["grep"]`, the agent should only have access to `grep`. Other tools (bash, edit, web_fetch, etc.) should be blocked.

## Actual Behavior

The agent has access to **all session-level tools** regardless of what `customAgents[n].tools` is set to. The `tools` field appears to be advisory/metadata only — not enforced by the CLI.

## Reproduction

### Environment

- `github-copilot-sdk` Python package v0.1.0 (installed from source)
- Copilot CLI: `/home/smolen/.nvm/versions/node/v24.13.1/bin/copilot`
- Python 3.12.3
- pytest-asyncio 1.3.0

### Test Script

```python
"""Reproduction: customAgents[n].tools is not enforced."""

import asyncio
import shutil

PROMPT = "List ALL tools you have access to. Be exhaustive — name every single tool."

async def test_agent_tools_not_enforced():
    from copilot import CopilotClient, SubprocessConfig
    from copilot.session import PermissionHandler

    cli_path = shutil.which("copilot")
    client = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client.start()

    # TEST 1: availableTools restricts session to [grep, web_fetch]
    #         agent.tools further restricts to [grep] only
    #
    # Expected: agent sees ONLY grep
    # Actual:   agent sees BOTH grep AND web_fetch

    session = await client.create_session(
        on_permission_request=PermissionHandler.approve_all,
        custom_agents=[{
            "name": "researcher",
            "displayName": "Researcher",
            "description": "Web researcher",
            "prompt": "You are a web researcher.",
            "tools": ["grep"],       # <-- Should restrict to grep only
            "infer": False,
        }],
        agent="researcher",
        available_tools=["grep", "web_fetch"],
    )

    messages = []
    def handler(event):
        et = getattr(getattr(event, "type", ""), "value", "")
        if et == "assistant.message":
            content = getattr(getattr(event, "data", None), "content", None)
            if content:
                messages.append(content)

    session.on(handler)
    await session.send(PROMPT)
    await asyncio.sleep(15)

    print("TEST 1: available_tools=[grep,web_fetch], agent.tools=[grep]")
    print(f"Agent response: {messages[-1][:500] if messages else '(none)'}")
    # Agent will list BOTH grep AND web_fetch, despite agent.tools=["grep"]

    await client.stop()

    # TEST 2: No availableTools restriction
    #         agent.tools restricts to [grep, view]
    #
    # Expected: agent sees ONLY grep and view
    # Actual:   agent sees ALL tools (bash, edit, create, glob, web_fetch, etc.)

    client2 = CopilotClient(SubprocessConfig(cli_path=cli_path, use_stdio=True))
    await client2.start()

    session2 = await client2.create_session(
        on_permission_request=PermissionHandler.approve_all,
        custom_agents=[{
            "name": "tester",
            "displayName": "Tool Tester",
            "description": "Lists tools",
            "prompt": "You are a tool testing agent.",
            "tools": ["grep", "view"],   # <-- Should restrict to grep + view
            "infer": False,
        }],
        agent="tester",
        # No available_tools set = no session restriction
    )

    messages2 = []
    def handler2(event):
        et = getattr(getattr(event, "type", ""), "value", "")
        if et == "assistant.message":
            content = getattr(getattr(event, "data", None), "content", None)
            if content:
                messages2.append(content)

    session2.on(handler2)
    await session2.send(PROMPT)
    await asyncio.sleep(15)

    print("\nTEST 2: available_tools=None, agent.tools=[grep,view]")
    print(f"Agent response: {messages2[-1][:500] if messages2 else '(none)'}")
    # Agent will list ALL tools, ignoring agent.tools restriction

    await client2.stop()


asyncio.run(test_agent_tools_not_enforced())
```

### Output

**Test 1** (`available_tools=["grep","web_fetch"]`, `agent.tools=["grep"]`):

```
Agent response: Here are all the tools I have access to:

1. **`web_fetch`** — Fetches a URL and returns content as markdown or raw HTML
2. **`grep`** — Searches file contents using ripgrep patterns

Those are the only two tools available to me in this session.
```

Agent sees `web_fetch` even though `agent.tools=["grep"]` should have excluded it.

**Test 2** (`available_tools=None`, `agent.tools=["grep","view"]`):

```
Agent response: Here is every tool I have access to:

### Core Tools
1. **bash** – Run shell commands
2. **write_bash** – Send input to an async bash session
3. **read_bash** – Read output from an async bash session
4. **stop_bash** – Terminate a bash session
5. **list_bash** – List all active bash sessions

### File Tools
6. **view** – View file contents or directory listings
7. **create** – Create new files
8. **edit** – Make string replacements in existing files

### Search Tools
9. **grep** – Search file contents
10. **glob** – Find files by pattern
...
```

Agent sees **all tools** despite `agent.tools=["grep","view"]`.

### Control: availableTools DOES work

For comparison, `availableTools` correctly restricts:

```python
session = await client.create_session(
    on_permission_request=PermissionHandler.approve_all,
    custom_agents=[{
        "name": "researcher",
        "tools": None,   # No per-agent restriction
        ...
    }],
    available_tools=["grep"],  # Session-level restriction
)
# Agent responds: "my tools are limited to code search (grep)"
```

This confirms `availableTools` is enforced server-side, but `customAgents[n].tools` is not.

## Impact

- Per-agent tool scoping (`customAgents[n].tools`) does not work as documented
- The only way to restrict tools is the session-level `availableTools` parameter
- This means you cannot have two custom agents with different tool access in the same session — both get whatever the session allows
- Security-sensitive use cases (sandboxed agents, read-only agents) cannot rely on `customAgents[n].tools`

## Workaround

Use `availableTools` on `create_session` as the only restriction mechanism. Create separate sessions for agents that need different tool access levels.

## Versions

- Python SDK: `github-copilot-sdk 0.1.0`
- CLI: latest as of 2026-03-24
- OS: Linux (WSL2) 6.6.87.2-microsoft-standard-WSL2
