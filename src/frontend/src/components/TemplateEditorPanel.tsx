import { useState, useEffect, useCallback, useRef } from 'react';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

function getApiKey(): string {
  return sessionStorage.getItem('swarm_api_key') ?? '';
}

function apiHeaders(): Record<string, string> {
  const key = getApiKey();
  return key
    ? { 'X-API-Key': key, 'Content-Type': 'application/json' }
    : { 'Content-Type': 'application/json' };
}

interface TemplateFile {
  filename: string;
  content: string;
}

interface TemplateEditorPanelProps {
  templateKey: string;
  workerName: string;
  onModified: (hasChanges: boolean) => void;
}

export function TemplateEditorPanel({
  templateKey,
  workerName,
  onModified,
}: TemplateEditorPanelProps) {
  const [files, setFiles] = useState<TemplateFile[]>([]);
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [editorContent, setEditorContent] = useState('');
  const [saving, setSaving] = useState(false);
  const [statusMessage, setStatusMessage] = useState('');
  const [originalContents, setOriginalContents] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);

  // Ref to track the last-saved/loaded content for accurate dirty comparison
  const savedContentRef = useRef<Record<string, string>>({});

  // Fetch template files and filter to the relevant worker
  const fetchTemplateFiles = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/templates/${templateKey}`, {
        headers: apiHeaders(),
      });
      if (!res.ok) {
        setFiles([]);
        setLoading(false);
        onModified(false);
        return;
      }
      const data = await res.json();
      const allFiles: TemplateFile[] = data.files ?? [];

      // Filter files relevant to this worker.
      // Match by worker name appearing in the filename (case-insensitive),
      // or show all if no match (so the user still has something to edit).
      const workerLower = workerName.toLowerCase().replace(/[_-]/g, '');
      const workerFiles = allFiles.filter((f) => {
        const nameLower = f.filename.toLowerCase().replace(/[_-]/g, '');
        return nameLower.includes(workerLower);
      });
      const relevantFiles = workerFiles.length > 0 ? workerFiles : allFiles;

      setFiles(relevantFiles);

      // Track original content for dirty detection
      const originals: Record<string, string> = {};
      for (const f of relevantFiles) {
        originals[f.filename] = f.content;
      }
      setOriginalContents(originals);
      savedContentRef.current = { ...originals };

      // Select the first file by default
      if (relevantFiles.length > 0) {
        setSelectedFile(relevantFiles[0].filename);
        setEditorContent(relevantFiles[0].content);
      }

      // Reset dirty state on fresh load
      onModified(false);
    } catch {
      // Network error -- leave files empty
      setFiles([]);
      onModified(false);
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateKey, workerName]);

  useEffect(() => {
    fetchTemplateFiles();
  }, [fetchTemplateFiles]);

  // Reset dirty state when workerName changes (component re-keys in parent,
  // but this guards against prop changes without re-mount)
  useEffect(() => {
    onModified(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workerName]);

  // Select a file tab
  function handleSelectFile(filename: string) {
    // Save current edits in local state before switching
    if (selectedFile) {
      setFiles((prev) =>
        prev.map((f) =>
          f.filename === selectedFile ? { ...f, content: editorContent } : f,
        ),
      );
    }
    setSelectedFile(filename);
    setStatusMessage('');
    const file = files.find((f) => f.filename === filename);
    if (file) {
      // If we've been editing this file, use the latest local content
      setEditorContent(file.content);
    }
  }

  // Handle content change
  function handleContentChange(value: string) {
    setEditorContent(value);

    // Check dirty state: compare current content against saved/loaded content
    const saved = savedContentRef.current;
    const currentDirty = selectedFile
      ? value !== (saved[selectedFile] ?? '')
      : false;

    // Also check other files for unsaved changes
    const otherDirty = files.some((f) => {
      if (f.filename === selectedFile) return false;
      return f.content !== (saved[f.filename] ?? '');
    });

    onModified(currentDirty || otherDirty);
  }

  // Save the current file
  async function handleSave() {
    if (!selectedFile) return;
    setSaving(true);
    setStatusMessage('');

    try {
      const res = await fetch(
        `${API_BASE}/api/templates/${templateKey}/files/${selectedFile}`,
        {
          method: 'PUT',
          headers: apiHeaders(),
          body: JSON.stringify({ content: editorContent }),
        },
      );

      if (res.ok) {
        setStatusMessage('Saved');
        // Update local state and originals
        setFiles((prev) =>
          prev.map((f) =>
            f.filename === selectedFile ? { ...f, content: editorContent } : f,
          ),
        );
        setOriginalContents((prev) => ({
          ...prev,
          [selectedFile]: editorContent,
        }));
        // Update the saved content ref so dirty tracking stays accurate
        savedContentRef.current = {
          ...savedContentRef.current,
          [selectedFile]: editorContent,
        };
        // Recheck dirty state against the now-updated saved content
        const saved = savedContentRef.current;
        const otherDirty = files.some((f) => {
          if (f.filename === selectedFile) return false;
          return f.content !== (saved[f.filename] ?? '');
        });
        onModified(otherDirty);
      } else if (res.status === 422) {
        const data = await res.json();
        const errors = data.detail?.errors ?? data.errors ?? [];
        setStatusMessage(
          `Validation failed: ${errors.map((e: { message: string }) => e.message).join(', ')}`,
        );
      } else {
        setStatusMessage(`Error: ${res.statusText}`);
      }
    } catch {
      setStatusMessage('Network error');
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="tep-panel">
        <div className="tep-loading">Loading template...</div>
      </div>
    );
  }

  if (files.length === 0) {
    return (
      <div className="tep-panel">
        <div className="tep-empty">
          No template files found for worker "{workerName}"
        </div>
      </div>
    );
  }

  return (
    <div className="tep-panel">
      <div className="tep-header">
        <span className="tep-title">Template: {workerName}</span>
      </div>

      {/* File tabs */}
      <div className="te-file-tabs">
        {files.map((f) => (
          <button
            key={f.filename}
            className={`te-file-tab ${f.filename === selectedFile ? 'te-file-tab--active' : ''}`}
            onClick={() => handleSelectFile(f.filename)}
          >
            {f.filename}
            {f.content !== (originalContents[f.filename] ?? '') && (
              <span className="tep-dirty-dot" />
            )}
          </button>
        ))}
      </div>

      {/* Editor area */}
      {selectedFile && (
        <div className="te-editor-area">
          <textarea
            className="te-editor-textarea"
            value={editorContent}
            onChange={(e) => handleContentChange(e.target.value)}
            spellCheck={false}
          />
          <div className="te-editor-actions">
            <button
              onClick={handleSave}
              disabled={saving}
              className="te-btn te-btn--save"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
            {statusMessage && (
              <span
                className={`te-status ${statusMessage.startsWith('Error') || statusMessage.startsWith('Validation') || statusMessage.startsWith('Network') ? 'te-status--error' : 'te-status--success'}`}
              >
                {statusMessage}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
