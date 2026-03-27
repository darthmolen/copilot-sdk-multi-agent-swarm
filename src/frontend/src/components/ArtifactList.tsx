import type { FileInfo } from '../types/swarm';
import { getApiKey } from '../App';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

interface ArtifactListProps {
  files: FileInfo[];
  activeFile: string | null;
  onSelect: (path: string) => void;
  swarmId?: string;
}

export function ArtifactList({ files, activeFile, onSelect, swarmId }: ArtifactListProps) {
  if (files.length === 0) return null;

  function handleDownloadZip() {
    if (!swarmId) return;
    const apiKey = getApiKey();
    fetch(`${API_BASE}/api/swarm/${swarmId}/files/download-zip`, {
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
    })
      .then((res) => res.blob())
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${swarmId}.zip`;
        a.click();
        URL.revokeObjectURL(url);
      })
      .catch(() => null);
  }

  return (
    <div className="artifact-list">
      {files.map((f) => (
        <button
          key={f.path}
          className={`artifact-item ${f.path === activeFile ? 'artifact-item--active' : ''}`}
          onClick={() => onSelect(f.path)}
          title={f.path}
        >
          <span className="artifact-icon">{f.name.endsWith('.md') ? '📄' : '📎'}</span>
          <span className="artifact-name">{f.name}</span>
        </button>
      ))}
      {swarmId && (
        <button className="artifact-item" onClick={handleDownloadZip} title="Download all files as ZIP">
          <span className="artifact-icon">📦</span>
          <span className="artifact-name">Download ZIP</span>
        </button>
      )}
    </div>
  );
}
