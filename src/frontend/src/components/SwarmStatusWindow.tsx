import { useState } from 'react';
import type { SwarmPhase, Task, AgentInfo } from '../types/swarm';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

interface SwarmStatusWindowProps {
  swarmId: string;
  phase: SwarmPhase;
  tasks: Task[];
  agents: AgentInfo[];
  roundNumber: number;
  suspended?: { remaining_tasks: number; max_rounds: number; reason: string };
  onGoToReport: () => void;
  onClose: () => void;
}

const PHASE_COLORS: Record<string, string> = {
  starting: '#6b7280',
  planning: '#8b5cf6',
  spawning: '#f59e0b',
  executing: '#3b82f6',
  synthesizing: '#06b6d4',
  qa: '#10b981',
  complete: '#22c55e',
  cancelled: '#6b7280',
  failed: '#ef4444',
  suspended: '#f59e0b',
};

function getApiKey(): string {
  return sessionStorage.getItem('swarm_api_key') ?? '';
}

export function SwarmStatusWindow({
  swarmId,
  phase,
  tasks,
  agents,
  roundNumber,
  suspended,
  onGoToReport,
  onClose,
}: SwarmStatusWindowProps) {
  const [loading, setLoading] = useState<'continue' | 'skip' | null>(null);
  const [error, setError] = useState<string | null>(null);

  const completedCount = tasks.filter((t) => t.status === 'completed').length;
  const totalCount = tasks.length;
  const progressPct = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;
  const phaseColor = PHASE_COLORS[phase] ?? '#6b7280';

  const isRunning =
    phase === 'executing' ||
    phase === 'planning' ||
    phase === 'spawning' ||
    phase === 'synthesizing' ||
    phase === 'starting' ||
    phase === 'qa';

  async function handleContinue() {
    setLoading('continue');
    setError(null);
    try {
      const apiKey = getApiKey();
      const res = await fetch(`${API_BASE}/api/swarm/${swarmId}/continue`, {
        method: 'POST',
        headers: apiKey ? { 'X-API-Key': apiKey } : {},
      });
      if (!res.ok) {
        throw new Error(`Failed to continue: ${res.status}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to continue');
    } finally {
      setLoading(null);
    }
  }

  async function handleSkipToSynthesis() {
    setLoading('skip');
    setError(null);
    try {
      const apiKey = getApiKey();
      const res = await fetch(`${API_BASE}/api/swarm/${swarmId}/skip-to-synthesis`, {
        method: 'POST',
        headers: apiKey ? { 'X-API-Key': apiKey } : {},
      });
      if (!res.ok) {
        throw new Error(`Failed to skip to synthesis: ${res.status}`);
      }
      onGoToReport();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to skip to synthesis');
    } finally {
      setLoading(null);
    }
  }

  // Running state
  if (isRunning) {
    return (
      <div className="swarm-status-window swarm-status-window--running">
        <div className="swarm-status-header">
          <span className="swarm-status-phase" style={{ background: phaseColor }}>
            {phase}
          </span>
          <span className="swarm-status-round">Round {roundNumber}</span>
          <span className="swarm-status-agents">{agents.length} agent{agents.length !== 1 ? 's' : ''}</span>
        </div>
        <div className="swarm-status-progress">
          <div className="swarm-status-progress-label">
            {completedCount} / {totalCount} tasks completed
          </div>
          <div className="swarm-status-progress-bar">
            <div
              className="swarm-status-progress-fill"
              style={{ width: `${progressPct}%`, background: phaseColor }}
            />
          </div>
        </div>
      </div>
    );
  }

  // Suspended state
  if (phase === 'suspended') {
    return (
      <div className="swarm-status-window swarm-status-window--suspended">
        <div className="swarm-status-banner swarm-status-banner--warning">
          Execution paused
          {suspended
            ? ` \u2014 ${suspended.remaining_tasks} tasks remain after ${suspended.max_rounds} rounds`
            : ''}
        </div>
        <div className="swarm-status-actions">
          <button
            className="swarm-status-btn swarm-status-btn--continue"
            onClick={handleContinue}
            disabled={loading !== null}
          >
            {loading === 'continue' ? 'Resuming...' : 'Continue'}
          </button>
          <button
            className="swarm-status-btn swarm-status-btn--skip"
            onClick={handleSkipToSynthesis}
            disabled={loading !== null}
          >
            {loading === 'skip' ? 'Skipping...' : 'Go to Report'}
          </button>
        </div>
        {error && <p className="error-text">{error}</p>}
      </div>
    );
  }

  // Complete state
  if (phase === 'complete') {
    return (
      <div className="swarm-status-window swarm-status-window--complete">
        <div className="swarm-status-banner swarm-status-banner--success">
          All tasks completed
        </div>
        <div className="swarm-status-actions">
          <button
            className="swarm-status-btn swarm-status-btn--report"
            onClick={onGoToReport}
          >
            Go to Report
          </button>
          <button
            className="swarm-status-btn swarm-status-btn--close"
            onClick={onClose}
          >
            Close
          </button>
        </div>
      </div>
    );
  }

  // Fallback for other phases (failed, cancelled) — show phase badge only
  return (
    <div className="swarm-status-window">
      <div className="swarm-status-header">
        <span className="swarm-status-phase" style={{ background: phaseColor }}>
          {phase}
        </span>
      </div>
    </div>
  );
}
