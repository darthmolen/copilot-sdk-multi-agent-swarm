# Chat UX Parity + After-Action Report Upgrade

Full plan at: `.claude/plans/tender-brewing-backus.md`

## Summary

Two phases to bring the web chat UX to parity with the VSCode extension (`research/vscode-extension-copilot-cli/`).

### Phase 1: Chat Fix
- Expand `ActiveTool` with input/output/error/duration
- `ChatEntry` union type for timeline: message | tool_group | streaming
- `ToolGroup` component with collapse/expand (mirrors extension's ToolExecution.js)
- Backend forwards richer tool events (input, output, error)
- Fix message ordering, duplicate divs, tool grouping

### Phase 2: After-Action Report
- Task pills in report view (worker:TaskName, colored by status)
- TaskDetailDrawer (collapsible, shows result)
- React architecture refactor: SwarmContext provider, ViewRouter, extracted views

### Architecture
- 3 explicit view components (QA, Report, Intervention) + Dashboard
- SwarmContext provider replaces God Component
- ChatPanel stays pure props (no context access)
- RightPanel slot-props stacker for views needing tasks + chat
- Implementation: 9 incremental steps, each independently deployable
