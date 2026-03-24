# Tool Usage — Independent SDK Research

## Research Method

Searched and read the following SDK source files in `research/copilot-sdk/nodejs/src/`:

- `types.ts` — `SessionConfig`, `ResumeSessionConfig`, `CustomAgentConfig`, `Tool`, `defineTool`
- `client.ts` — `createSession()` and `resumeSession()` implementations
- `session.ts` — `CopilotSession`: `_handleBroadcastEvent`, `registerTools`, `_executeToolAndRespond`
- `generated/rpc.ts` — All RPC method definitions including `session.agent.select`, `session.model.switchTo`, `tools.list`
- `generated/session-events.ts` — `subagent.selected`, `external_tool.requested` event shapes
- `nodejs/test/e2e/session.test.ts` — E2E test that directly inspects OpenAI wire traffic

Grep patterns used:
```
grep -rn "availableTools" research/copilot-sdk/ --include="*.ts"
grep -rn "defineTool|ToolDefinition|customTools" research/copilot-sdk/nodejs/src/
grep -rn "external_tool|tool.*filter|allowedTool" research/copilot-sdk/ --include="*.ts"
grep -rn "agent.select|agentName|customAgents|CustomAgent" research/copilot-sdk/nodejs/src/
grep -n "overridesBuiltInTool|tool.*call|toolCall|handler.*tool" research/copilot-sdk/nodejs/src/session.ts
```

---

## Findings by Claim

### Claim 1: `availableTools` blocks before handler is invoked

> "`availableTools` is the SDK's hard session whitelist. Any tool call that names a tool not in this array is blocked by the SDK before the handler is invoked."

**Verdict: PARTIALLY WRONG (mechanically)**

**Evidence:**

The Node.js SDK has zero client-side code that checks `availableTools` before dispatching to a handler. The `_handleBroadcastEvent` method in `session.ts` dispatches `external_tool.requested` events unconditionally — no whitelist check:

```typescript
// session.ts:337-361
private _handleBroadcastEvent(event: SessionEvent): void {
    if (event.type === "external_tool.requested") {
        const { requestId, toolName } = event.data as { ... };
        const handler = this.toolHandlers.get(toolName);
        if (handler) {
            void this._executeToolAndRespond(requestId, toolName, ...);
        }
    }
    ...
}
```

`availableTools` is forwarded to the CLI server during session creation (or resume):

```typescript
// client.ts:606 (createSession)
availableTools: config.availableTools,

// client.ts:705 (resumeSession)
availableTools: config.availableTools,
```

The E2E test confirms the enforcement is done by the CLI server (which controls what tools are presented to the model via the OpenAI API wire format):

```typescript
// session.test.ts:99-112
it("should create a session with availableTools", async () => {
    const session = await client.createSession({
        onPermissionRequest: approveAll,
        availableTools: ["view", "edit"],
    });
    await session.sendAndWait({ prompt: "What is 1+1?" });

    // It only tells the model about the specified tools and no others
    const traffic = await openAiEndpoint.getExchanges();
    expect(traffic[0].request.tools).toMatchObject([
        { function: { name: "view" } },
        { function: { name: "edit" } },
    ]);
});
```

**Notes:** The blocking is real and the behavior described is correct — tools not in `availableTools` are never called. But the *mechanism* is server-side (the CLI backend controls what tools the LLM sees), not "the Node.js SDK blocking before the handler is invoked." The Node.js SDK never even receives an `external_tool.requested` event for a blocked tool because the CLI server never asks the LLM about it. The phrase "blocked by the SDK" is misleading — it is blocked by the CLI backend process.

---

### Claim 2: `availableTools` applies uniformly to built-in and custom tools

> "`availableTools` applies to every tool name uniformly — built-in or custom. Think of it as the guest list at the door."

**Verdict: LIKELY CORRECT but UNVERIFIABLE from Node.js SDK source alone**

**Evidence:**

The Node.js SDK treats both built-in and custom tools as name strings when sending `availableTools` to the server. There is no special handling in the client code:

```typescript
// client.ts:604-606
tools: config.tools?.map((tool) => ({
    name: tool.name, description: tool.description, ...
})),
availableTools: config.availableTools,   // just a string[]
```

The E2E test example uses `["view", "edit"]` (built-in tools) in `availableTools`. The test scenario at `research/copilot-sdk/test/scenarios/tools/tool-filtering/typescript/src/index.ts` uses `availableTools: ["grep", "glob", "view"]` — all built-ins. No test exercises a mix of custom + built-in tools in `availableTools`.

**Notes:** Whether the CLI server applies one uniform check or separate logic for built-in vs. custom tool names is not observable from the Node.js SDK source. Based on the type definition (`availableTools?: string[]` — just names, no type field), uniform treatment is the most likely implementation, but this cannot be confirmed from client code alone.

---

### Claim 3: Custom tool not in `availableTools` is blocked

> "If you register a custom tool via `tools` but don't include its name in `availableTools`, the SDK will block it."

**Verdict: FUNCTIONALLY CORRECT, mechanically imprecise**

**Evidence:**

Same as Claim 1. The Node.js SDK sends both `tools` (handler definitions) and `availableTools` (name whitelist) to the CLI server independently. The CLI server enforces the whitelist when deciding what tools to expose to the LLM. A custom tool not in `availableTools` will not be included in the LLM context, so the LLM will never call it, so the handler will never fire.

```typescript
// client.ts:592-621 — createSession RPC call
const response = await this.connection!.sendRequest("session.create", {
    tools: config.tools?.map((tool) => ({ name: tool.name, ... })),
    availableTools: config.availableTools,   // server enforces this
    ...
});
```

**Notes:** "The SDK will block it" implies Node.js client-side enforcement. What actually happens: the CLI server ignores the tool when building the LLM prompt. The outcome (handler never called) is the same, but the mechanism is different.

---

### Claim 4: Built-in tools are handled natively without custom handlers

> "Built-in SDK tools — no handlers needed — the SDK handles those natively"

**Verdict: CONFIRMED (with clarification)**

**Evidence:**

The `tools.list` RPC returns "available built-in tools with metadata" (rpc.ts:113). Built-in tools like `bash`, `grep`, `view`, `glob`, `str_replace_editor` are executed directly by the CLI backend process. The Node.js SDK never receives an `external_tool.requested` event for built-in tools.

Custom tools, by contrast, trigger `external_tool.requested` events which the Node.js SDK dispatches to registered handlers via `session.ts:_handleBroadcastEvent`. The mechanism is explicit in the event type name — "external" = handled by the Node.js client, not the CLI server.

The `Tool` interface in `types.ts` includes an `overridesBuiltInTool` flag:

```typescript
// types.ts:235-240
/**
 * When true, explicitly indicates this tool is intended to override a built-in tool
 * of the same name. If not set and the name clashes with a built-in tool, the runtime
 * will return an error.
 */
overridesBuiltInTool?: boolean;
```

This confirms that built-in tools have their own separate existence, and clashing names result in a runtime error unless you explicitly opt in with `overridesBuiltInTool: true`.

**Notes:** "The SDK handles those natively" is slightly imprecise. It is the **CLI backend** (the server process) that handles built-in tools natively. The Node.js SDK is only involved for custom (`external`) tools. For the purposes of the docs, this distinction is usually fine.

---

### Claim 5: `availableTools` cannot be changed without destroying and recreating the session

> "`availableTools` is set once at session creation and cannot be changed without destroying and recreating the session."

**Verdict: PARTIALLY WRONG**

**Evidence:**

There is no session-scoped RPC method to update `availableTools` on a live session. Inspecting all methods in `createSessionRpc()` in `rpc.ts`:

```typescript
// rpc.ts:633-697 — complete list of session-scoped RPCs
model.getCurrent, model.switchTo,
mode.get, mode.set,
plan.read, plan.update, plan.delete,
workspace.listFiles, workspace.readFile, workspace.createFile,
fleet.start,
agent.list, agent.getCurrent, agent.select, agent.deselect,
compaction.compact,
tools.handlePendingToolCall,
permissions.handlePendingPermissionRequest,
log, shell.exec, shell.kill
```

None of these updates `availableTools`.

**However**, `ResumeSessionConfig` explicitly includes `availableTools`:

```typescript
// types.ts:852-882
export type ResumeSessionConfig = Pick<
    SessionConfig,
    | "availableTools"
    | "excludedTools"
    | "tools"
    | ...
>;
```

This means `resumeSession(sessionId, { availableTools: [...] })` can update the whitelist on an **existing session** without destroying it. The session's conversation history is preserved. This is a significant operational difference from the claim.

**Notes:** The claim should read: "`availableTools` cannot be changed mid-conversation without a session resume or restart." Destroy+recreate is not the only option — `resumeSession()` is a lighter alternative that preserves history.

---

### Claim 6: Agent tool list is enforced when an agent is selected

> "When an agent is selected via `rpc.agent.select({ name })`, the SDK enforces that agent's tool list for messages sent under that agent."

**Verdict: CORRECT about outcome, enforcement is SERVER-SIDE**

**Evidence:**

The `session.rpc.agent.select()` method sends a single RPC to the CLI server:

```typescript
// rpc.ts:672-673
agent: {
    select: async (params): Promise<SessionAgentSelectResult> =>
        connection.sendRequest("session.agent.select", { sessionId, ...params }),
}
```

The `SessionAgentSelectParams` only takes a `name` — no tools override is sent by the Node.js SDK:

```typescript
// rpc.ts:435-444
export interface SessionAgentSelectParams {
  sessionId: string;
  /** Name of the custom agent to select */
  name: string;
}
```

The CLI server emits a `subagent.selected` event that includes the agent's tool list:

```typescript
// session-events.ts:2198-2215
type: "subagent.selected";
data: {
    agentName: string;
    agentDisplayName: string;
    /** List of tool names available to this agent, or null for all tools */
    tools: string[] | null;
};
```

The agent's `tools` array (defined in `CustomAgentConfig`) is sent to the server at session creation time. The server enforces per-agent tool restrictions when the agent is active.

**Notes:** The claim is functionally correct. The "SDK enforces" phrasing suggests client-side enforcement, but it is the CLI backend that enforces this. The Node.js SDK just calls `session.agent.select` and the server handles the rest.

---

### Claim 7: `null` on agent tools means no per-agent restriction; session whitelist still applies

> "`null` on the agent means 'no per-agent restriction' — but the session whitelist still applies."

**Verdict: CONFIRMED for `null` meaning; "session whitelist still applies" is UNVERIFIABLE from client code**

**Evidence:**

The `CustomAgentConfig` type definition is explicit:

```typescript
// types.ts:643-674
export interface CustomAgentConfig {
    name: string;
    displayName?: string;
    description?: string;
    /**
     * List of tool names the agent can use.
     * Use null or undefined for all tools.
     */
    tools?: string[] | null;
    prompt: string;
    mcpServers?: Record<string, MCPServerConfig>;
    infer?: boolean;
}
```

The `subagent.selected` event reinforces this:

```typescript
// session-events.ts:2212-2214
/** List of tool names available to this agent, or null for all tools */
tools: string[] | null;
```

`null` (or `undefined`) unambiguously means "no per-agent restriction — all tools."

Whether the session-level `availableTools` whitelist is applied on top of a `null`-tools agent is server-side logic not visible in the Node.js SDK source. The claim is reasonable (a higher-layer restriction should always apply), but it cannot be confirmed from this codebase.

---

## Surprises & Corrections

### 1. The Node.js SDK has NO client-side `availableTools` enforcement

The most significant finding: the phrase "blocked by the SDK" is misleading throughout the documentation. The Node.js SDK is a thin RPC wrapper. All enforcement of `availableTools`, agent tool lists, and tool availability happens inside the CLI backend process (the Go/Rust server binary). The Node.js `session.ts` dispatcher (`_handleBroadcastEvent`) has no whitelist checking at all.

The practical consequence: if the CLI server has a bug or is bypassed, the Node.js SDK provides no safety net. The documentation implies a "defense in depth" at the SDK layer that does not exist.

### 2. `resumeSession()` can update `availableTools` without destroying the session

`ResumeSessionConfig` includes `availableTools`, meaning you can resume an existing session with a different tool whitelist. The documentation says destroy+recreate is required, which is incorrect. This matters for operational use cases where you want to change permissions mid-workflow without losing conversation history.

### 3. `overridesBuiltInTool` — unmentioned critical flag

Custom tools that share a name with a built-in tool will cause a **runtime error** unless `overridesBuiltInTool: true` is set. The documentation does not mention this. If someone defines a custom `bash` tool (e.g., to add logging), they will get an opaque runtime error without this flag.

### 4. Agent tool enforcement is fully server-side and opaque to the Node.js SDK

The `session.rpc.agent.select()` call passes only the agent `name`. The server already knows the agent's `tools` array (from session creation). There is no client-side logic in `session.ts` that changes tool routing when an agent is selected.

---

## SDK Type Definitions

### `SessionConfig` (relevant fields only)

```typescript
// types.ts:708-847
export interface SessionConfig {
    tools?: Tool<any>[];           // Custom tool handler implementations
    availableTools?: string[];     // Session-level whitelist (takes precedence over excludedTools)
    excludedTools?: string[];      // Tools to disable (ignored if availableTools is set)
    customAgents?: CustomAgentConfig[];  // Agent definitions
    agent?: string;                // Initial agent to activate
    onPermissionRequest: PermissionHandler;
    // ... model, systemMessage, mcpServers, etc.
}
```

### `ResumeSessionConfig`

```typescript
// types.ts:852-882
export type ResumeSessionConfig = Pick<
    SessionConfig,
    | "availableTools"   // ← CAN be changed on resume
    | "excludedTools"
    | "tools"
    | "customAgents"
    | "agent"
    | "model"
    | "systemMessage"
    | "mcpServers"
    | "streaming"
    | "onPermissionRequest"
    | "onUserInputRequest"
    | "hooks"
    | "workingDirectory"
    | "configDir"
    | "skillDirectories"
    | "disabledSkills"
    | "infiniteSessions"
    | "onEvent"
    | "reasoningEffort"
    | "clientName"
    | "provider"
> & {
    disableResume?: boolean;
};
```

### `CustomAgentConfig`

```typescript
// types.ts:643-674
export interface CustomAgentConfig {
    name: string;
    displayName?: string;
    description?: string;
    tools?: string[] | null;   // null = all tools; string[] = restricted list
    prompt: string;
    mcpServers?: Record<string, MCPServerConfig>;
    infer?: boolean;
}
```

### `Tool<TArgs>`

```typescript
// types.ts:230-245
export interface Tool<TArgs = unknown> {
    name: string;
    description?: string;
    parameters?: ZodSchema<TArgs> | Record<string, unknown>;
    handler: ToolHandler<TArgs>;
    overridesBuiltInTool?: boolean;  // ← REQUIRED if name clashes with built-in
    skipPermission?: boolean;
}
```

---

## Conclusion

The documentation at `TOOL-USAGE-THROUGH-SDK-AND-CUSTOM-AGENTS.md` is **functionally accurate** — the described behavior (what gets blocked, how agents restrict tools, what `null` means) matches the SDK types and tests. However, several mechanical assertions are imprecise or wrong:

| Claim | Accuracy |
|-------|----------|
| `availableTools` "blocked by the SDK before handler" | **Misleading** — blocked server-side by CLI backend; the Node.js SDK has no whitelist enforcement |
| Applies uniformly to built-in and custom tools | **Likely correct** — unverifiable from client code alone |
| Custom tool not in `availableTools` is blocked | **Functionally correct** — mechanism is server-side |
| Built-in tools handled natively without handlers | **Correct** — CLI backend handles them; `external_tool.requested` only fires for custom tools |
| `availableTools` requires destroy+recreate to change | **Wrong** — `resumeSession()` can update `availableTools` without destroying the session |
| Agent tool list enforced after `agent.select` | **Correct about outcome** — enforcement is server-side |
| `null` agent tools = no per-agent restriction | **Confirmed** — explicit in type definitions and event docs |

**What should be updated in the documentation:**

1. Replace "blocked by the SDK" with "blocked by the CLI backend" throughout.
2. Correct Claim 5: `resumeSession()` can change `availableTools` without destroying the session.
3. Add a note about `overridesBuiltInTool: true` being required when a custom tool name clashes with a built-in.
4. Clarify that "session whitelist still applies when agent has null tools" is the expected server behavior, not something verifiable from client code.
