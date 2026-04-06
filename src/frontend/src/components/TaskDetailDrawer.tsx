import type { Task } from '../types/swarm';
import { statusColorClass } from './TaskPillBar';

export interface TaskDetailDrawerProps {
  task: Task;
  onClose: () => void;
}

export function TaskDetailDrawer({ task, onClose }: TaskDetailDrawerProps) {
  return (
    <div className="task-detail-drawer">
      <div className="task-detail-drawer__header">
        <h3 className="task-detail-drawer__subject">{task.subject}</h3>
        <div className="task-detail-drawer__meta">
          <span className="task-detail-drawer__worker">
            {task.worker_name} ({task.worker_role})
          </span>
          <span
            className={`task-detail-drawer__status task-detail-drawer__status${statusColorClass(task.status)}`}
            data-testid="task-detail-status"
          >
            {task.status}
          </span>
        </div>
        <button
          className="task-detail-drawer__close"
          data-testid="task-detail-close"
          onClick={onClose}
          aria-label="Close task detail"
        >
          ×
        </button>
      </div>

      <h4 className="task-detail-drawer__section-label">Prompt</h4>
      <div className="task-detail-drawer__prompt">
        {task.description}
      </div>

      {task.result && (
        <>
          <h4 className="task-detail-drawer__section-label">Result</h4>
          <pre className="task-detail-drawer__result" data-testid="task-detail-result">
            {task.result}
          </pre>
        </>
      )}
    </div>
  );
}
