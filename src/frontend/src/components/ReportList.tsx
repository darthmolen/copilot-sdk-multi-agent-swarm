import type { ReportListItem } from '../utils/buildReportList';

interface ReportListProps {
  items: ReportListItem[];
  activeId: string | null;
  onSelect: (swarmId: string) => void;
}

export function ReportList({ items, activeId, onSelect }: ReportListProps) {
  return (
    <div className="report-list">
      {items.length === 0 ? (
        <div className="report-list-empty">No sessions yet</div>
      ) : (
        items.map((item) => (
          <button
            key={item.swarmId}
            className={[
              'report-list-item',
              `report-list-item--${item.status}`,
              item.swarmId === activeId ? 'report-list-item--active' : '',
            ].filter(Boolean).join(' ')}
            onClick={() => onSelect(item.swarmId)}
          >
            <span className={`report-status-dot report-status-dot--${item.status}`} />
            <span className="report-list-title">{item.title}</span>
            <span className="report-list-meta">
              {item.swarmId.slice(0, 8)} · {new Date(item.timestamp).toLocaleDateString()}
            </span>
          </button>
        ))
      )}
    </div>
  );
}
