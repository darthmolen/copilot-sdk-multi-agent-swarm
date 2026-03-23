import { useState } from 'react';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

const TEMPLATES = [
  { value: 'software-development', label: 'Software Development' },
  { value: 'deep-research', label: 'Deep Research' },
  { value: 'warehouse-optimizer', label: 'Warehouse Optimizer' },
];

interface SwarmControlsProps {
  onStart: (swarmId: string) => void;
}

export function SwarmControls({ onStart }: SwarmControlsProps) {
  const [goal, setGoal] = useState('');
  const [template, setTemplate] = useState(TEMPLATES[0].value);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleStart() {
    if (!goal.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/api/swarm/start`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ goal: goal.trim(), template }),
      });
      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }
      const data = await res.json();
      onStart(data.swarm_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start swarm');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="swarm-controls">
      <h2>Swarm Controls</h2>
      <div className="controls-row">
        <input
          type="text"
          placeholder="Enter your goal..."
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleStart()}
          disabled={loading}
          className="goal-input"
        />
        <select
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          disabled={loading}
          className="template-select"
        >
          {TEMPLATES.map((t) => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </select>
        <button onClick={handleStart} disabled={loading || !goal.trim()} className="start-button">
          {loading ? 'Starting...' : 'Start Swarm'}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
    </div>
  );
}
