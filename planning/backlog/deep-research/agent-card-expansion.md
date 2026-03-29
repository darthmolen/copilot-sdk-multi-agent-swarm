# Agent Card Expansion — Stream of Consciousness View

## Problem

Agent cards in the frontend show only name, role, status, and last 200 chars of output. Users can't see what each agent is actually doing: tool calls, reasoning, messages, errors.

## Requirements

Expandable agent cards with tabs showing:
- **Overview**: name, role, status, tasks completed (current view)
- **Tools**: history of tool calls with args and results
- **Reasoning**: extended thinking blocks (chain-of-thought)
- **Output**: full message stream (not just last 200 chars)

## Backend Changes Needed

The orchestrator currently emits only `sdk_event` (which is skipped by the WS forwarder because it contains non-serializable SDK objects). Need to bridge specific SDK event types to frontend-facing events:

- `TOOL_EXECUTION_START` → `agent.tool_call` with `{agent_name, tool_name, arguments}`
- `TOOL_EXECUTION_COMPLETE` → `agent.tool_result` with `{agent_name, tool_name, success, result}`
- `ASSISTANT_REASONING` / `ASSISTANT_REASONING_DELTA` → `agent.reasoning` / `agent.reasoning_delta`
- `ASSISTANT_MESSAGE` / `ASSISTANT_MESSAGE_DELTA` → `agent.message` / `agent.message_delta`

This requires the `SwarmAgent._on_event` callback to parse real SDK events and emit serializable frontend events instead of raw `sdk_event`.

## Frontend Changes

### New types

```typescript
interface ToolCall {
  tool: string;
  args: Record<string, unknown>;
  result?: string;
  success?: boolean;
  timestamp: string;
}

interface AgentDetail {
  toolCalls: ToolCall[];
  reasoning: string[];
  messages: string[];
}

// Add to SwarmState:
agentDetails: Record<string, AgentDetail>;
```

### New reducer cases

- `agent.tool_call` → append to agentDetails[name].toolCalls
- `agent.tool_result` → update last toolCall with result
- `agent.reasoning` → append to agentDetails[name].reasoning
- `agent.message` → append to agentDetails[name].messages

### Component changes

- `AgentRoster.tsx` → `AgentCard` becomes expandable (click to expand/collapse)
- Expanded view has tab navigation: Overview | Tools | Reasoning | Output
- Tools tab: scrollable list of tool calls with args/results
- Reasoning tab: collapsible reasoning blocks
- Output tab: full message stream with copy button

## Estimate

Backend: 1-2 hours (bridge SDK events → frontend events in SwarmAgent._on_event)
Frontend: 2-3 hours (new types, reducer cases, expandable card component)
Tests: 1-2 hours (TDD for new events + reducer + component)
