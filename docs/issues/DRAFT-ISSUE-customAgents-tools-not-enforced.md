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

---

## COPILOT rejoinder

**Date:** 2026-03-24  
**Spike:** (separate project) `../vscode-copilot-cli-extension/planning/spikes/tool-intersection-enforcement/spike_node_intersection.mjs`

After the above was written, equivalent tests were run against the **Node.js SDK** (`@github/copilot-sdk`) using the same CLI binary. Results diverge from the Python findings.

### Node.js T2: `availableTools=["grep","web_fetch"]`, `agent.tools=["grep"]`

**Python result:** Agent listed both `grep` and `web_fetch` — `agent.tools` had no effect.

**Node.js result:**
```
I have access to exactly 1 tool:
1. grep — Fast code search using ripgrep...
```

`agent.tools` **was enforced** — the agent saw only the intersection. `web_fetch` was absent despite being in `availableTools`.

### Node.js T3: `availableTools=null`, `agent.tools=["grep","view"]`

**Python result:** Agent listed all tools — bash, create, edit, web_fetch, and more.

**Node.js result:**
```
Here are all tools available to me:
1. grep
2. view
3. skill
4. report_intent
```

`agent.tools` **was partially enforced** — bash, create, edit, web_fetch etc. were absent. The only extras (`skill`, `report_intent`) are CLI-injected runtime tools that bypass both restriction mechanisms.

### Interpretation

`customAgents[n].tools` does appear to be enforced by the CLI backend — at least in the Node.js SDK context. The Python findings may reflect:

- A **CLI version difference** between the two test dates
- A **protocol negotiation difference** between the Python and Node.js SDKs
- A **bug in the Python SDK's session creation payload** that silently drops or misformats `customAgents[n].tools`

The issue is still worth filing. The ask should be:
1. Confirm whether `customAgents[n].tools` enforcement is **intentional and stable**
2. Explain why the Python SDK may not be receiving enforcement
3. Document the CLI-injected tools (`skill`, `report_intent`) that bypass both `availableTools` and `agent.tools`

The workaround (`availableTools` as the only reliable mechanism) remains valid for the Python SDK until the divergence is explained.

### Node.js Spike Source

```javascript
/**
 * Spike: Node.js equivalent of spike_intersection_theory.py
 *
 * Tests whether customAgents[n].tools enforces per-agent tool restriction,
 * or whether only availableTools provides hard enforcement.
 *
 * Mirror of the Python spike in spike_intersection_theory.py, written for
 * the Node.js SDK used by this extension.
 *
 * Run with: node --experimental-vm-modules spike_node_intersection.mjs
 * Requires: @github/copilot-sdk installed, copilot CLI on PATH
 *
 * Expected results based on Python SDK empirical findings:
 *   Test 1 (availableTools=[grep,web_fetch], agent.tools=null):
 *     → agent sees grep + web_fetch  (availableTools enforced)
 *   Test 2 (availableTools=[grep,web_fetch], agent.tools=["grep"]):
 *     → if intersection:  agent sees grep only
 *     → if advisory only: agent sees grep + web_fetch  ← Python spike result
 *   Test 3 (availableTools=null, agent.tools=["grep","view"]):
 *     → if agent.tools enforces: agent sees grep + view only
 *     → if advisory only:        agent sees ALL tools   ← Python spike result
 */

import { writeFileSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROMPT = 'List ALL tools you have access to. Be exhaustive — name every single tool.';

let CopilotClient, approveAll;
async function loadSDK() {
    const sdk = await import('@github/copilot-sdk');
    CopilotClient = sdk.CopilotClient;
    approveAll = sdk.approveAll;
}

function collectUntilIdle(session, timeoutMs = 120_000) {
    return new Promise((resolve) => {
        const events = [];
        const messages = [];
        let settled = false;

        const cleanup = session.on((event) => {
            const type = typeof event.type === 'string' ? event.type : (event.type?.value ?? String(event.type));
            events.push({ type, data: event.data });

            if (type === 'assistant.message' && event.data?.content) {
                messages.push(event.data.content);
            }
            if (type === 'session.idle' && !settled) {
                settled = true;
                cleanup();
                clearTimeout(timer);
                resolve({ events, messages });
            }
        });

        const timer = setTimeout(() => {
            if (!settled) { settled = true; cleanup(); resolve({ events, messages }); }
        }, timeoutMs);
    });
}

async function runTest(label, { availableTools, agentTools }) {
    console.log('\n' + '='.repeat(60));
    console.log(`TEST: ${label}`);
    console.log(`  session availableTools = ${JSON.stringify(availableTools)}`);
    console.log(`  agent.tools            = ${JSON.stringify(agentTools)}`);
    console.log('='.repeat(60));

    const client = new CopilotClient({
        cwd: process.cwd(),
        autoStart: true,
        cliArgs: ['--no-auto-update'],
    });

    const sessionConfig = {
        onPermissionRequest: approveAll,
        clientName: 'spike-intersection',
        customAgents: [{
            name: 'tester',
            displayName: 'Tool Tester',
            description: 'Lists available tools',
            prompt: 'You are a tool testing agent. When asked, list ALL tools available to you.',
            tools: agentTools,
            infer: false,
        }],
    };

    if (availableTools !== null) {
        sessionConfig.availableTools = availableTools;
    }

    const session = await client.createSession(sessionConfig);
    console.log(`  Session created: ${session.sessionId}`);

    try {
        const agentList = await session.rpc.agent.list();
        console.log(`  rpc.agent.list(): ${JSON.stringify(agentList)}`);
    } catch (e) {
        console.log(`  rpc.agent.list() error: ${e.message}`);
    }

    try {
        await session.rpc.agent.select({ name: 'tester' });
        console.log(`  agent selected: tester`);
    } catch (e) {
        console.log(`  [warn] agent.select failed: ${e.message}`);
    }

    const collectPromise = collectUntilIdle(session);
    await session.sendAndWait({ prompt: PROMPT }, 90_000);
    const { events, messages } = await collectPromise;

    const toolEvents = events.filter(e => e.type.includes('tool'));
    console.log(`\n  Tool-related events: ${toolEvents.map(e => e.type).join(', ') || '(none)'}`);
    if (messages.length) {
        console.log(`  Agent response (first 800 chars):\n${messages[messages.length - 1].slice(0, 800)}`);
    } else {
        console.log(`  Agent response: (none — check events)`);
        console.log(`  All event types: ${[...new Set(events.map(e => e.type))].join(', ')}`);
    }

    await session.destroy();
    return { events, messages };
}

async function main() {
    await loadSDK();
    const results = {};

    const t1 = await runTest('T1: availableTools=[grep,web_fetch], agent.tools=null', {
        availableTools: ['grep', 'web_fetch'],
        agentTools: null,
    });
    results.test1 = { label: 'availableTools=[grep,web_fetch], agent.tools=null', messages: t1.messages };

    // INTERSECTION TEST — does agent.tools=["grep"] further restrict beyond availableTools=[grep,web_fetch]?
    // If intersection: agent sees grep only
    // If advisory:     agent sees grep + web_fetch  ← Python spike result
    const t2 = await runTest('T2: availableTools=[grep,web_fetch], agent.tools=["grep"]', {
        availableTools: ['grep', 'web_fetch'],
        agentTools: ['grep'],
    });
    results.test2 = { label: 'availableTools=[grep,web_fetch], agent.tools=["grep"]', messages: t2.messages };

    // Does agent.tools restrict when no availableTools is set?
    // If agent.tools enforces: agent sees grep + view only
    // If advisory:             agent sees ALL tools  ← Python spike result
    const t3 = await runTest('T3: availableTools=null, agent.tools=["grep","view"]', {
        availableTools: null,
        agentTools: ['grep', 'view'],
    });
    results.test3 = { label: 'availableTools=null, agent.tools=["grep","view"]', messages: t3.messages };

    const outPath = join(__dirname, 'spike_node_results.json');
    writeFileSync(outPath, JSON.stringify(results, null, 2));
    console.log(`\nResults saved to: ${outPath}`);
}

main().catch(console.error);
```
