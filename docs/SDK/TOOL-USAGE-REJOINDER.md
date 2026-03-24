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

## Open Questions

1. Does `availableTools` recognize custom tool names registered via `tools=`? Or only built-in SDK tool names?
2. Is the lack of enforcement on `customAgents[n].tools` a bug or by design?
3. Does the Node.js SDK behave differently from the Python SDK?

---

## Spike Scripts

- `planning/spikes/spike_custom_agent_tools.py` — Tests availableTools vs custom agent tools
- `planning/spikes/spike_intersection_theory.py` — Tests the intersection theory with 3 scenarios
