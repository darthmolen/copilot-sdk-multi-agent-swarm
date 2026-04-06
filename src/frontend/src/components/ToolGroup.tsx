import { useState } from 'react';
import type { ActiveTool } from '../types/swarm';

interface ToolGroupProps {
  tools: ActiveTool[];
}

function statusIcon(status: ActiveTool['status']): string {
  switch (status) {
    case 'running': return '\u23F3';
    case 'complete': return '\u2705';
    case 'failed': return '\u274C';
  }
}

function formatDuration(startedAt?: number, completedAt?: number): string | null {
  if (startedAt == null || completedAt == null) return null;
  const seconds = (completedAt - startedAt) / 1000;
  return `${seconds.toFixed(1)}s`;
}

function truncateInput(input: string, maxLen = 60): string {
  if (input.length <= maxLen) return input;
  return input.slice(0, maxLen) + '...';
}

function ToolItem({ tool }: { tool: ActiveTool }) {
  const [detailOpen, setDetailOpen] = useState(false);
  const duration = formatDuration(tool.startedAt, tool.completedAt);
  const hasExpandableOutput = !!tool.output;

  return (
    <div
      className={`tool-group__item tool-group__item--${tool.status}`}
      data-testid="tool-group-item"
      onClick={hasExpandableOutput ? () => setDetailOpen((prev) => !prev) : undefined}
      style={hasExpandableOutput ? { cursor: 'pointer' } : undefined}
    >
      <div className="tool-group__item-row">
        <span className="tool-group__icon">{statusIcon(tool.status)}</span>
        <span className="tool-group__name">{tool.toolName}</span>
        {tool.input && (
          <span className="tool-group__input" data-testid="tool-input-preview">
            {truncateInput(tool.input)}
          </span>
        )}
        {duration && (
          <span className="tool-group__duration">{duration}</span>
        )}
      </div>
      {tool.status === 'failed' && tool.error && (
        <div className="tool-group__error">{tool.error}</div>
      )}
      {detailOpen && tool.output && (
        <div className="tool-group__detail">{tool.output}</div>
      )}
    </div>
  );
}

export function ToolGroup({ tools }: ToolGroupProps) {
  const allComplete = tools.every(
    (t) => t.status === 'complete' || t.status === 'failed',
  );
  const isMulti = tools.length >= 2;
  const shouldCollapse = isMulti && allComplete;

  const [manualExpanded, setManualExpanded] = useState<boolean | null>(null);

  // Determine effective collapsed state
  const isCollapsed =
    manualExpanded !== null ? !manualExpanded : shouldCollapse;

  // Single tool: always expanded, no header
  if (!isMulti) {
    return (
      <div className="tool-group">
        {tools.map((tool) => (
          <ToolItem key={tool.toolCallId} tool={tool} />
        ))}
      </div>
    );
  }

  // Multi-tool group
  const completedTools = tools.filter(
    (t) => t.status === 'complete' || t.status === 'failed',
  );
  const runningTools = tools.filter((t) => t.status === 'running');
  const completedCount = completedTools.length;
  const toolNames = tools.map((t) => t.toolName).join(', ');

  return (
    <div className="tool-group">
      <div
        className="tool-group__header"
        data-testid="tool-group-header"
        onClick={() => setManualExpanded((prev) => {
          if (prev === null) return shouldCollapse;
          return !prev;
        })}
      >
        <span className="tool-group__collapse">
          {isCollapsed ? '\u25B6' : '\u25BC'}
        </span>
        <span className="tool-group__summary">
          {tools.length} tools {allComplete ? '\u2713' : `(${completedCount}/${tools.length})`}
        </span>
        {isCollapsed && (
          <span className="tool-group__names">{toolNames}</span>
        )}
      </div>
      {!isCollapsed &&
        tools.map((tool) => (
          <ToolItem key={tool.toolCallId} tool={tool} />
        ))}
      {isCollapsed &&
        runningTools.map((tool) => (
          <ToolItem key={tool.toolCallId} tool={tool} />
        ))}
    </div>
  );
}
