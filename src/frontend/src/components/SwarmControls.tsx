import { useState, useEffect, useRef } from 'react';
import { TemplateEditor } from './TemplateEditor';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

interface TemplateOption {
  key: string;
  name: string;
  description: string;
}

interface SwarmControlsProps {
  onStart: (swarmId: string) => void;
}

export function SwarmControls({ onStart }: SwarmControlsProps) {
  const [goal, setGoal] = useState('');
  const [templates, setTemplates] = useState<TemplateOption[]>([]);
  const [template, setTemplate] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function fetchTemplates() {
    const apiKey = sessionStorage.getItem('swarm_api_key') ?? '';
    fetch(`${API_BASE}/api/templates`, {
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
    })
      .then((res) => (res.ok ? res.json() : { templates: [] }))
      .then((data) => {
        const fetched: TemplateOption[] = data.templates ?? [];
        setTemplates(fetched);
        if (fetched.length > 0 && !template) {
          setTemplate(fetched[0].key);
        }
      })
      .catch(() => null);
  }

  useEffect(() => {
    fetchTemplates();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function handleDeploy(file: File) {
    setError(null);
    const apiKey = sessionStorage.getItem('swarm_api_key') ?? '';
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch(`${API_BASE}/api/templates/deploy`, {
        method: 'POST',
        headers: apiKey ? { 'X-API-Key': apiKey } : {},
        body: formData,
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.detail || `Deploy failed: ${res.status}`);
      }
      // Refresh template list after successful deploy
      fetchTemplates();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Deploy failed');
    }
  }

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
      <div className="swarm-controls__actions" data-testid="swarm-actions">
        <input
          ref={fileInputRef}
          type="file"
          accept=".zip"
          style={{ display: 'none' }}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleDeploy(file);
            e.target.value = '';
          }}
        />
        <button
          onClick={() => fileInputRef.current?.click()}
          className="te-deploy-btn"
          title="Deploy template pack"
          aria-label="Deploy template pack"
        >
          &#8679;
        </button>
        <select
          value={template}
          onChange={(e) => setTemplate(e.target.value)}
          disabled={loading || templates.length === 0}
          className="template-select"
        >
          {templates.map((t) => (
            <option key={t.key} value={t.key}>
              {t.name}
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
