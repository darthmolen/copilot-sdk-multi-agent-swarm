import { useState, useEffect, useCallback } from 'react';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

function getApiKey(): string {
  return sessionStorage.getItem('swarm_api_key') ?? '';
}

function apiHeaders(): Record<string, string> {
  const key = getApiKey();
  return key ? { 'X-API-Key': key, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

interface TemplateFile {
  filename: string;
  content: string;
}

interface TemplateMeta {
  key: string;
  name: string;
  description: string;
}

interface ValidationError {
  message: string;
  line: number | null;
}

interface TemplateEditorProps {
  onClose: () => void;
}

export function TemplateEditor({ onClose }: TemplateEditorProps) {
  const [templates, setTemplates] = useState<TemplateMeta[]>([]);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [files, setFiles] = useState<TemplateFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState('');
  const [errors, setErrors] = useState<ValidationError[]>([]);
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');

  // Fetch template list
  const fetchTemplates = useCallback(async () => {
    const res = await fetch(`${API_BASE}/api/templates`, { headers: apiHeaders() });
    if (res.ok) {
      const data = await res.json();
      setTemplates(data.templates.map((t: any) => ({
        key: t.key,
        name: t.name,
        description: t.description ?? '',
      })));
    }
  }, []);

  useEffect(() => { fetchTemplates(); }, [fetchTemplates]);

  // Fetch template details when selected
  async function handleSelectTemplate(key: string) {
    setSelectedKey(key);
    setSelectedFile(null);
    setEditorContent('');
    setErrors([]);
    setStatusMessage('');

    const res = await fetch(`${API_BASE}/api/templates/${key}`, { headers: apiHeaders() });
    if (res.ok) {
      const data = await res.json();
      setFiles(data.files);
      if (data.files.length > 0) {
        setSelectedFile(data.files[0].filename);
        setEditorContent(data.files[0].content);
      }
    }
  }

  // Select file within template
  function handleSelectFile(filename: string) {
    setSelectedFile(filename);
    setErrors([]);
    setStatusMessage('');
    const file = files.find(f => f.filename === filename);
    if (file) setEditorContent(file.content);
  }

  // Save file
  async function handleSave() {
    if (!selectedKey || !selectedFile) return;
    setSaving(true);
    setErrors([]);
    setStatusMessage('');

    const res = await fetch(
      `${API_BASE}/api/templates/${selectedKey}/files/${selectedFile}`,
      {
        method: 'PUT',
        headers: apiHeaders(),
        body: JSON.stringify({ content: editorContent }),
      }
    );

    if (res.ok) {
      setStatusMessage('Saved successfully');
      // Update local state
      setFiles(prev => prev.map(f =>
        f.filename === selectedFile ? { ...f, content: editorContent } : f
      ));
    } else if (res.status === 422) {
      const data = await res.json();
      const errs = data.detail?.errors ?? data.errors ?? [];
      setErrors(errs);
      setStatusMessage('Validation failed');
    } else {
      setStatusMessage(`Error: ${res.statusText}`);
    }
    setSaving(false);
  }

  // Create new template
  async function handleCreate() {
    const key = prompt('Template key (e.g., my-research-team):');
    if (!key) return;
    const name = prompt('Template name:', key.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
    if (!name) return;
    const description = prompt('Description:', '') ?? '';

    const res = await fetch(`${API_BASE}/api/templates`, {
      method: 'POST',
      headers: apiHeaders(),
      body: JSON.stringify({ key, name, description }),
    });

    if (res.ok) {
      await fetchTemplates();
      handleSelectTemplate(key);
    } else {
      const data = await res.json();
      alert(data.detail ?? 'Failed to create template');
    }
  }

  // Delete template
  async function handleDelete() {
    if (!selectedKey) return;
    if (!confirm(`Delete template "${selectedKey}"? This cannot be undone.`)) return;

    const res = await fetch(`${API_BASE}/api/templates/${selectedKey}`, {
      method: 'DELETE',
      headers: apiHeaders(),
    });

    if (res.ok) {
      setSelectedKey(null);
      setFiles([]);
      setSelectedFile(null);
      setEditorContent('');
      await fetchTemplates();
    }
  }

  return (
    <div className="template-editor-overlay">
      <div className="template-editor">
        <div className="template-editor__header">
          <h2>Template Editor</h2>
          <div className="template-editor__actions">
            <button onClick={handleCreate} className="te-btn te-btn--create">+ New Template</button>
            <button onClick={onClose} className="te-btn te-btn--close">Close</button>
          </div>
        </div>

        <div className="template-editor__body">
          {/* Sidebar: template list */}
          <div className="template-editor__sidebar">
            <h3>Templates</h3>
            <ul className="te-template-list">
              {templates.map(t => (
                <li
                  key={t.key}
                  className={`te-template-item ${t.key === selectedKey ? 'te-template-item--active' : ''}`}
                  onClick={() => handleSelectTemplate(t.key)}
                >
                  <span className="te-template-name">{t.name}</span>
                  <span className="te-template-key">{t.key}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Main area */}
          <div className="template-editor__main">
            {selectedKey ? (
              <>
                {/* File tabs */}
                <div className="te-file-tabs">
                  {files.map(f => (
                    <button
                      key={f.filename}
                      className={`te-file-tab ${f.filename === selectedFile ? 'te-file-tab--active' : ''}`}
                      onClick={() => handleSelectFile(f.filename)}
                    >
                      {f.filename}
                    </button>
                  ))}
                </div>

                {/* Editor */}
                {selectedFile && (
                  <div className="te-editor-area">
                    <textarea
                      className="te-editor-textarea"
                      value={editorContent}
                      onChange={e => setEditorContent(e.target.value)}
                      spellCheck={false}
                    />

                    {/* Validation errors */}
                    {errors.length > 0 && (
                      <div className="te-errors">
                        {errors.map((err, i) => (
                          <div key={i} className="te-error">
                            {err.line != null && <span className="te-error-line">Line {err.line}:</span>}
                            <span className="te-error-msg">{err.message}</span>
                          </div>
                        ))}
                      </div>
                    )}

                    {/* Actions */}
                    <div className="te-editor-actions">
                      <button
                        onClick={handleSave}
                        disabled={saving}
                        className="te-btn te-btn--save"
                      >
                        {saving ? 'Saving...' : 'Save'}
                      </button>
                      <button
                        onClick={handleDelete}
                        className="te-btn te-btn--delete"
                      >
                        Delete Template
                      </button>
                      {statusMessage && (
                        <span className={`te-status ${errors.length > 0 ? 'te-status--error' : 'te-status--success'}`}>
                          {statusMessage}
                        </span>
                      )}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="te-empty">
                <p>Select a template from the sidebar to edit, or create a new one.</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
