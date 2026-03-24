# Tool Usage Through the SDK & Custom Agents

This document explains exactly how tool access is controlled in this extension — both at the session level and at the per-agent level. The two mechanisms are distinct and can be layered.

---

## The Three SDK Parameters That Matter

When calling `createSession` (or `createSessionWithModelFallback`), there are three distinct tool-related parameters:

| Parameter | Type | Purpose |
|-----------|------|---------|
| `tools` | `ToolDefinition[]` | Custom tool **handler implementations** you define. These don't exist in the SDK — you write the code. |
| `availableTools` | `string[]` | **Session-level whitelist.** The SDK refuses to call any tool whose name isn't in this list. Acts as a hard cap. |
| `customAgents` | `CustomAgentConfig[]` | Array of agent definitions, each with their own `tools` array restricting what that agent can call. |

These are independent. `availableTools` restricts the whole session. Each agent's `tools` restricts only that agent. A tool must appear in **both** to be callable by an agent in a restricted session.

---

## `tools` vs `availableTools`: The Critical Distinction

This is the most common point of confusion. They serve completely different purposes and operate at different layers.

### `tools` — Registering Handler Implementations

`tools` is where you **define new tools that don't exist in the SDK**. You provide a name, a JSON schema for parameters, and a handler function:

```typescript
const myTool = defineTool({
    name: 'my_custom_tool',
    description: 'Does something the SDK cannot do natively',
    parameters: {
        type: 'object',
        properties: {
            input: { type: 'string', description: 'The input' }
        },
        required: ['input']
    },
    handler: async ({ input }) => {
        return { textResultForLlm: `Processed: ${input}` };
    }
});

await createSession({ tools: [myTool], ... });
```

Passing a tool in `tools` **registers it** — the SDK knows it exists and knows how to call it. But by itself this does **not** restrict anything. If `availableTools` is not set, all tools (built-in + your custom ones) are callable.

### `availableTools` — Filtering What Can Be Called

`availableTools` is a **name-only whitelist**. The SDK doesn't distinguish between built-in tools and custom tools — it just checks whether the name is in the list. If it isn't, the call is blocked before any handler runs.

**Critically: custom tools must be in `availableTools` too.** If you register a custom tool via `tools` but don't include its name in `availableTools`, the SDK will block it.

```typescript
await createSession({
    tools: [myCustomTool],          // registers the handler
    availableTools: [
        'view',                     // built-in SDK tool ✓
        'grep',                     // built-in SDK tool ✓
        'my_custom_tool',           // your custom tool — must be here too ✓
    ],
});
// Result: model can call view, grep, and my_custom_tool. Nothing else.
```

### `availableTools` Is NOT Only for Built-In Tools

A common misconception: `availableTools` filters built-in SDK tools, and custom tools registered via `tools` are always available. **This is wrong.**

`availableTools` applies to every tool name uniformly — built-in or custom. Think of it as the **guest list at the door**. `tools` introduces new people; `availableTools` decides who gets in.

| | `tools` only | `availableTools` only | Both |
|--|--|--|--|
| Built-in SDK tools | All available | Filtered to whitelist | N/A (no handler needed) |
| Your custom tools | All available (no session cap) | Blocked (no handler registered) | ✅ Correct: registered + whitelisted |

### Blending Built-In and Custom Tools

If you want a session that allows some built-in tools *and* some custom tools, include both in `availableTools`:

```typescript
await createSession({
    tools: [planBashExplore, editPlanFile, updateWorkPlan],  // custom handlers
    availableTools: [
        // Built-in SDK tools you want to allow
        'view',
        'grep',
        'glob',
        'web_fetch',
        // Your custom tools — registered above AND listed here
        'plan_bash_explore',
        'edit_plan_file',
        'update_work_plan',
    ],
});
```

This is exactly the pattern used in plan mode. The 12-item `availableTools` list is a blend: 6 custom tools (with handlers) + 6 built-in SDK tools (no handlers needed — the SDK handles those natively).

---

## Session-Level Tool Restriction (`availableTools`)

`availableTools` is the SDK's hard session whitelist. Any tool call that names a tool not in this array is blocked by the SDK before the handler is invoked.

```typescript
// sdkSessionManager.ts — plan session creation
this.planSession = await this.createSessionWithModelFallback({
    tools: customTools,                                              // handler implementations
    availableTools: this.planModeToolsService.getAvailableToolNames(), // hard whitelist
    customAgents: this.customAgentsService.toSDKAgents(),
    ...
});
```

This is set **once at session creation** and cannot be changed without destroying and recreating the session.

### When to Use `availableTools`

Use `availableTools` when you want a hard cap on what a session can ever do, regardless of which agent is active or what the model requests. Examples:

- A read-only exploration session that must never write files
- A planning session that must never commit or install packages
- A sandboxed session for untrusted input

### Work Session vs. Plan Session

The extension uses two sessions:

```
Work session:   no availableTools set → all SDK tools available
Plan session:   availableTools = [12 specific tools]
```

Switching modes swaps which session is active. No restriction is applied to the work session itself.

---

## Plan Mode: What Is Restricted and Why

The plan session's `availableTools` contains exactly 12 tools:

```typescript
// src/extension/services/planModeToolsService.ts
getAvailableToolNames(): string[] {
    return [
        // Custom tools — implemented in this extension
        'plan_bash_explore',        // bash, but read-only commands only
        'task_agent_type_explore',  // task, but explore-type agents only
        'edit_plan_file',           // edit, but plan.md only
        'create_plan_file',         // create, but plan.md only
        'update_work_plan',         // updates plan content
        'present_plan',             // surfaces plan to user for acceptance

        // Safe SDK tools — no side effects
        'view',
        'grep',
        'glob',
        'web_fetch',
        'fetch_copilot_cli_documentation',
        'report_intent',
    ];
}
```

**What is explicitly excluded:**

- `bash` / `shell` — replaced by `plan_bash_explore` which enforces a command allowlist
- `edit` / `create` / `write` — replaced by `edit_plan_file` / `create_plan_file` which scope writes to `plan.md` only
- `task` — replaced by `task_agent_type_explore` which restricts agent type to `explore`
- Any MCP tools that involve writes, commits, or installs

### Defense in Depth on Custom Tools

The custom plan mode tools enforce restrictions at the **handler level** as well. Even if the SDK allowed a call through, the handler would reject it:

```typescript
// plan_bash_explore handler (simplified)
handler: async ({ command }) => {
    const blockedPatterns = [
        /\bgit\s+commit\b/, /\bgit\s+push\b/,
        /\brm\b/, /\bmv\b/, /\bchmod\b/,
        /\bnpm\s+install\b/, /\bpip\s+install\b/,
        /\bsudo\b/, /\beval\b/, /\bexec\b/,
    ];
    if (blockedPatterns.some(p => p.test(command))) {
        return { textResultForLlm: `Blocked: '${command}' is not allowed in plan mode.` };
    }
    // execute allowed command...
}
```

This is intentional: `availableTools` blocks at the SDK boundary; handler logic blocks at execution. Two layers.

---

## Per-Agent Tool Restriction (`customAgents[n].tools`)

Each custom agent carries its own `tools` array. When an agent is selected via `rpc.agent.select({ name })`, the SDK enforces that agent's tool list for messages sent under that agent.

Agents are registered at **session creation time** via `customAgents`:

```typescript
// sdkSessionManager.ts — work session creation
this.session = await this.createSessionWithModelFallback({
    customAgents: this.customAgentsService.toSDKAgents(),
    ...
});
```

The `toSDKAgents()` call strips runtime-only fields and passes each agent's `name`, `prompt`, `tools`, and `infer` to the SDK.

### Built-In Agent Tool Scopes

| Agent | `tools` | Rationale |
|-------|---------|-----------|
| **planner** | `view`, `grep`, `glob`, `plan_bash_explore`, `update_work_plan`, `present_plan`, `create_plan_file`, `edit_plan_file`, `task_agent_type_explore` | Exploration + plan writing only |
| **implementer** | `null` (all tools) | Full access — it executes the plan |
| **reviewer** | `view`, `grep`, `glob`, `plan_bash_explore` | Read-only + safe bash |

`null` means no restriction — the agent inherits whatever the session allows.

### User-Defined Agents

User agents are defined in Markdown files with YAML frontmatter:

```markdown
---
name: my-agent
tools:
  - view
  - grep
  - glob
---
Your system prompt here.
```

If `tools` is omitted, the agent has no restriction (same as `null`). See `CUSTOM-AGENTS.md` for the full file format.

---

## How the Two Mechanisms Interact

Both restrictions apply simultaneously. The effective tool set for an agent in a restricted session is the **intersection** of the session whitelist and the agent's tools array:

```
effective tools = availableTools ∩ agent.tools
```

```
Example: Plan session (availableTools = 12 tools)
         with planner agent (tools = 9 tools)

Session allows:  plan_bash_explore ✓  view ✓  bash ✗  edit ✗
Planner allows:  plan_bash_explore ✓  view ✓  bash ✗  (not listed)

Result: planner gets plan_bash_explore + view + grep + glob + plan tools
        bash is blocked at session level regardless of agent config
```

In the **work session** (no `availableTools`), only the agent's `tools` array applies.

### Decision Matrix

| Scenario | Use |
|----------|-----|
| Define a new tool with custom logic | `tools: [ToolDefinition]` on `createSession` |
| Restrict what an entire session can ever do | `availableTools` on `createSession` |
| Allow only some built-in SDK tools | Add their names to `availableTools` (no handler needed) |
| Allow only some custom tools | Add their handlers to `tools` AND their names to `availableTools` |
| Blend built-in and custom tools in a restricted session | Mix both in `availableTools`; provide handlers only for custom ones |
| Restrict what a specific agent persona can do | `tools` array on the agent definition |
| Allow an agent to use a custom tool | Add it to **both** session `availableTools` and the agent's `tools` array |
| Give one agent full access, restrict others | Set `tools: null` on the unrestricted agent; set arrays on the rest |
| Custom tool registered but never called | Missing from `availableTools` — add it there |

---

## Agent Selection: Sticky vs. One-Shot

### Sticky (session-wide)

Selecting an agent via the `/agent` command or the 🤖 toolbar button calls:

```typescript
await this.session.rpc.agent.select({ name: agentName });
this._sessionAgent = agentName;
```

The agent persists across all messages until explicitly deselected.

### One-Shot (per-message `@mention`)

When a message is sent with an `@agentname` prefix, the extension temporarily switches agents for that one message and then restores the previous state:

```typescript
// sdkSessionManager.ts
const isOneShot = !!agentName && agentName !== this._sessionAgent;
if (isOneShot) {
    await this.session.rpc.agent.select({ name: agentName });
}
try {
    await this.session.sendAndWait(sendOptions);
} finally {
    if (isOneShot) {
        if (this._sessionAgent) {
            await this.session.rpc.agent.select({ name: this._sessionAgent });
        } else {
            await this.session.rpc.agent.deselect();
        }
    }
}
```

The `finally` block ensures the sticky agent is always restored, even if the message throws.

---

## Common Pitfalls

**Custom tool not available to an agent in plan mode**
The tool name must appear in *both* `availableTools` (session whitelist) and the agent's `tools` array. Missing from either = blocked.

**Custom tool works in work session but not plan session**
The plan session has an explicit `availableTools` whitelist. Add your tool name to `PlanModeToolsService.getAvailableToolNames()`.

**`tools: null` agent is still restricted**
The session itself has `availableTools` set. `null` on the agent means "no per-agent restriction" — but the session whitelist still applies.

**Agent selection has no effect on tool access**
If the session has no `availableTools` set and the agent has `tools: null`, there is effectively no restriction. Both must be configured to restrict.

---

## Related Files

| File | Purpose |
|------|---------|
| `src/sdkSessionManager.ts` | Session creation, agent selection, one-shot logic |
| `src/extension/services/PlanModeToolsService.ts` | Plan mode tool definitions and whitelist |
| `src/extension/services/CustomAgentsService.ts` | Agent loading, built-in agents, `toSDKAgents()` |
| `documentation/CUSTOM-AGENTS.md` | End-user guide: agent file format, usage |
| `research/copilot-sdk/nodejs/src/generated/rpc.ts` | SDK RPC methods including `agent.select` |
