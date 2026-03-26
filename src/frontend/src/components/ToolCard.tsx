import { useState } from 'react';
import type { ActiveTool } from '../types/swarm';

interface ToolCardProps {
  tool: ActiveTool;
}

function statusIcon(status: ActiveTool['status']): string {
  switch (status) {
    case 'running': return '\u23F3';
    case 'complete': return '\u2705';
    case 'failed': return '\u274C';
  }
}

function ToolCard({ tool }: ToolCardProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`tool-card tool-card--${tool.status}`}>
      <div className="tool-card__header" onClick={() => setExpanded(!expanded)}>
        <span className="tool-card__collapse">{expanded ? '\u25BC' : '\u25B6'}</span>
        <span className="tool-card__icon">{statusIcon(tool.status)}</span>
        <span className="tool-card__name">{tool.toolName}</span>
        {tool.status === 'running' && <span className="tool-card__spinner" />}
      </div>
      {expanded && (
        <div className="tool-card__content">
          <span className="tool-card__id">ID: {tool.toolCallId}</span>
          <span className="tool-card__agent">Agent: {tool.agentName}</span>
        </div>
      )}
    </div>
  );
}

interface ToolCardListProps {
  tools: ActiveTool[];
}

export function ToolCardList({ tools }: ToolCardListProps) {
  if (tools.length === 0) return null;
  return (
    <div className="tool-card-list">
      {tools.map((tool) => (
        <ToolCard key={tool.toolCallId} tool={tool} />
      ))}
    </div>
  );
}
