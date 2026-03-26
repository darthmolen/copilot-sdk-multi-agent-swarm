# Tool Usage Rejoinder: Empirical Findings vs. Documentation Claims

**Date:** 2026-03-24
**Context:** The vscode extension's `TOOL-USAGE-THROUGH-SDK-AND-CUSTOM-AGENTS.md` makes claims about how `availableTools` and `customAgents[n].tools` interact. We ran empirical spikes to test these claims.

---

## The Claims Under Test

From the extension doc:

> **effective tools = availableTools ∩ agent.tools**
> A tool must appear in **both** to be callable by an agent in a restricted session.

And:

> `customAgents[n].tools` applies at the **per-agent level** and is a further restriction

---

## Spike Results

### Spike 1: availableTools=[grep], agent.tools=None

**Prompt:** "Search the web for dad jokes" (requires web_fetch)

**Result:** Agent responded: *"I don't have web search or web fetch tools available... my tools are limited to code search (grep)"*

**Conclusion:** `availableTools` DOES restrict the session. ✅ Confirmed.

### Spike 2: availableTools=[grep,web_fetch], agent.tools=[grep]

**Prompt:** "List ALL tools you have access to"

**Result:** Agent listed **both `web_fetch` AND `grep`**.

**Expected if intersection:** Agent should only see `grep` (web_fetch not in agent.tools)
**Actual:** Agent sees both.

**Conclusion:** `customAgents[n].tools` does NOT further restrict beyond `availableTools`. ❌ Intersection theory **disproved**.

### Spike 3: availableTools=None, agent.tools=[grep,view]

**Prompt:** "List ALL tools you have access to"

**Result:** Agent listed **everything** — bash, write_bash, view, create, edit, grep, glob, web_fetch, and more.

**Expected if agent.tools restricts:** Agent should only see grep and view
**Actual:** Agent sees all tools. `agent.tools=["grep","view"]` had zero effect.

**Conclusion:** `customAgents[n].tools` has **no enforcement effect** on tool access. ❌ Per-agent restriction **disproved**.

---

## Revised Understanding

| Parameter | Documented Behavior | Empirical Behavior |
|-----------|--------------------|--------------------|
| `availableTools` | Session-level whitelist | ✅ **Confirmed** — blocks tools not in list |
| `excludedTools` | Session-level blacklist | Not tested (assumed working) |
| `customAgents[n].tools` | Per-agent restriction | ❌ **No enforcement** — agent sees all session tools regardless |

### What `customAgents[n].tools` Actually Does

Based on empirical evidence, `customAgents[n].tools` appears to be:
- **Metadata only** — included in the agent's context/prompt but NOT enforced server-side
- The model MAY voluntarily limit itself based on seeing the list in its context
- But the SDK/CLI does NOT block tool calls that fall outside this list

### The Only Enforcement Point

**`availableTools` on `create_session` is the ONLY hard enforcement.** Everything else is advisory.

---

## Implications for Our Swarm

1. **To restrict workers to only swarm tools:** Use `availableTools=["task_update", "inbox_send", "inbox_receive", "task_list"]` on the session — but these are custom tool names, not built-in names. Need to test if `availableTools` works for custom tool names too.

2. **To let workers use built-in tools + swarm tools:** Set `availableTools` to include both built-in and custom tool names, OR don't set it at all (no restriction) and rely on prompt engineering.

3. **`customAgents[n].tools` is not a security boundary** — it's a hint. Don't rely on it for access control.

---

## Research Sub-Agent Findings (Source Code Analysis)

A parallel research agent analyzed the SDK source code and docs. Key findings:

1. **No test exists combining both `availableTools` and `customAgents[n].tools`** — the SDK test scenarios test each independently, never together
2. The docs describe a "cascading" model: `availableTools` gates session, then `agent.tools` further restricts
3. The proposed formula: `effective = agent.tools ∩ (availableTools ∩ builtInTools)`

### Contradiction: Docs vs. Empirical Reality

The research agent's "cascading" model is **also disproved** by our spikes:

| Scenario | Cascading predicts | Spike shows |
|----------|-------------------|-------------|
| session=[grep,web_fetch], agent=[grep] | grep only | grep AND web_fetch |
| session=None, agent=[grep,view] | grep and view only | ALL tools |

**Conclusion:** The filtering happens server-side in the copilot-cli binary. The client SDKs pass all parameters but the CLI may not enforce `customAgents[n].tools` at all — it may only use it as context for the LLM's system prompt (telling the model what tools it "should" use), not as a hard gate.

This is consistent with what we observe: the model sometimes respects its tool list (when prompted well) and sometimes ignores it (when its coding-agent instincts override).

## Definitive Findings

1. **`availableTools` = hard enforcement** (server-side, proven by spike)
2. **`customAgents[n].tools` = soft/advisory** (not enforced, proven by spike)
3. **`tools=` (custom tool registration) = always available** (separate namespace)
4. **The extension doc's intersection claim is wrong** in practice, even if conceptually intended

## ROOT CAUSE FOUND (2026-03-24, late)

**The Python SDK's `agent=` parameter in `create_session` does NOT auto-select the agent.** The agent is registered but `getCurrent()` returns `None`. When no agent is selected, `customAgents[n].tools` is not enforced.

**Fix:** Explicitly call `session.rpc.agent.select(SessionAgentSelectParams(name=...))` after `create_session`. After this call:
- `getCurrent()` returns the selected agent
- `customAgents[n].tools` IS enforced (intersection with `availableTools`)
- Agent sees only the tools in its `tools` array (within the session whitelist)

**Spike proof:** With `availableTools=["grep","web_fetch"]` and `agent.tools=["grep"]`:
- Without select: agent sees both grep AND web_fetch
- With select: agent sees ONLY grep ✅

**The extension doc's intersection claim IS correct** — it just requires the agent to be explicitly selected first. Our earlier spikes never called `agent.select()`.

## Revised Definitive Findings

1. **`availableTools` = hard enforcement** (session-level, always works)
2. **`customAgents[n].tools` = hard enforcement ONLY when agent is selected via `rpc.agent.select()`**
3. **`agent=` in create_session = registers agent but does NOT select it** (possible SDK bug or missing documentation)
4. **Effective tools = `availableTools ∩ agent.tools`** — confirmed, but only after explicit select

## Practical Guidance for Our Swarm

To restrict workers:
- Register custom agents with specific `tools` lists
- Call `session.rpc.agent.select()` after session creation
- Use `availableTools` as the session-level cap
- Effective restriction = intersection of both

To give workers full freedom:
- Set `agent.tools = null` (no per-agent restriction)
- Don't set `availableTools` (no session restriction)

---

## Spike Scripts

- `planning/spikes/spike_custom_agent_tools.py` — Tests availableTools vs custom agent tools
- `planning/spikes/spike_intersection_theory.py` — Tests the intersection theory with 3 scenarios
