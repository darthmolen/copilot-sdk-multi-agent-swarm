import type { FileInfo } from '../types/swarm';

interface ArtifactListProps {
  files: FileInfo[];
  activeFile: string | null;
  onSelect: (path: string) => void;
}

export function ArtifactList({ files, activeFile, onSelect }: ArtifactListProps) {
  if (files.length === 0) return null;

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
    </div>
  );
}
