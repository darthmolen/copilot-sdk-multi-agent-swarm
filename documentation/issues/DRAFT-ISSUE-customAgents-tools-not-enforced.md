# Issue Reference: customAgents[n].tools not enforced when agent pre-selected

## Existing Issue

**github/copilot-sdk#859** — "AI: CustomAgentConfig.Tools not enforced when agent pre-selected via SessionConfig.Agent"

Status: `open`, `needs-investigation`
Filed: 2026-03-14
Affects: Python SDK, .NET SDK (confirmed by us and the issue author)

## Our Findings

We independently discovered and verified the same bug through empirical spikes:

1. `agent=` in `create_session` registers the agent but does NOT activate it
2. `agent.getCurrent()` returns `None` after creation with `agent=`
3. `customAgents[n].tools` is only enforced when agent is explicitly selected via `rpc.agent.select()`
4. `availableTools` (session-level) works correctly regardless

## Our Workaround

In `src/backend/swarm/agent.py`, we call `session.rpc.agent.select()` explicitly after `create_session`:

```python
await self.session.rpc.agent.select(SessionAgentSelectParams(name=self.name))
```

This correctly activates the agent and enforces `customAgents[n].tools` via intersection with `availableTools`.

## Spike Evidence

- `planning/spikes/spike_intersection_theory.py` — 3-scenario test proving agent.tools not enforced without select
- `planning/spikes/spike_wire_dump.py` — wire format dump showing correct payload
- `planning/spikes/spike_wire_dump_with_rpc.py` — proves getCurrent()=None after create_session with agent=

## Action

Consider adding our Python SDK reproduction as a comment on issue #859 to help the investigation.
