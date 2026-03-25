import type { AgentInfo } from '../types/swarm';

interface AgentRosterProps {
  agents: AgentInfo[];
  outputs: Record<string, string>;
}

const STATUS_COLORS: Record<string, string> = {
  idle: '#9ca3af',
  thinking: '#f59e0b',
  working: '#3b82f6',
  ready: '#10b981',
  failed: '#ef4444',
};

function AgentCard({
  agent,
  output,
}: {
  agent: AgentInfo;
  output: string | undefined;
}) {
  return (
    <div className={`agent-card agent-${agent.status}`}>
      <div className="agent-header">
        <span
          className={`status-dot agent-status-dot${agent.status === 'thinking' || agent.status === 'working' ? ' active' : ''}`}
          style={{ backgroundColor: STATUS_COLORS[agent.status] ?? '#9ca3af' }}
        />
        <strong>{agent.display_name || agent.name}</strong>
        {agent.swarm_id && <span className="swarm-id-label">{agent.swarm_id.slice(0, 8)}</span>}
      </div>
      <p className="agent-role">{agent.role}</p>
      <p className="agent-tasks">Tasks completed: {agent.tasks_completed}</p>
      {output && (
        <pre className="agent-output">{output.slice(-200)}</pre>
      )}
    </div>
  );
}

export function AgentRoster({ agents, outputs }: AgentRosterProps) {
  return (
    <div className="agent-roster">
      <h2>Agents</h2>
      <div className="agent-grid">
        {agents.map((agent) => (
          <AgentCard
            key={`${agent.swarm_id ?? 'x'}-${agent.name}`}
            agent={agent}
            output={outputs[agent.name]}
          />
        ))}
        {agents.length === 0 && (
          <p className="empty-text">No agents spawned yet</p>
        )}
      </div>
    </div>
  );
}
