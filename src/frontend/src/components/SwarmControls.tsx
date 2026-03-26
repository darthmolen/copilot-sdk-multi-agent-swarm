import { useState } from 'react';
import { TemplateEditor } from './TemplateEditor';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

const TEMPLATES = [
  { value: 'deep-research', label: 'Deep Research' },
  { value: 'software-development', label: 'Software Development' },
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
  const [showEditor, setShowEditor] = useState(false);

  async function handleStart() {
    if (!goal.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const apiKey = sessionStorage.getItem('swarm_api_key') ?? '';
      const res = await fetch(`${API_BASE}/api/swarm/start`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(apiKey ? { 'X-API-Key': apiKey } : {}),
        },
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
      <textarea
        placeholder="Enter your goal..."
        value={goal}
        onChange={(e) => setGoal(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleStart();
          }
        }}
        disabled={loading}
        className="goal-input goal-input--textarea"
        rows={3}
      />
      <div className="swarm-controls__actions">
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
        <button
          onClick={() => setShowEditor(true)}
          className="te-edit-btn"
          title="Edit templates"
          aria-label="Edit templates"
        >
          &#9998;
        </button>
        <button onClick={handleStart} disabled={loading || !goal.trim()} className="start-button">
          {loading ? 'Starting...' : 'Start Swarm'}
        </button>
      </div>
      {error && <p className="error-text">{error}</p>}
      {showEditor && <TemplateEditor onClose={() => setShowEditor(false)} />}
    </div>
  );
}
