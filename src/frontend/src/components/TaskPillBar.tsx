import type { Task, TaskStatus } from '../types/swarm';

export interface TaskPillBarProps {
  tasks: Task[];
  selectedTaskId: string | null;
  onSelect: (taskId: string) => void;
}

export function statusColorClass(status: TaskStatus): string {
  return `--${status}`;
}

function truncatePillText(text: string, maxLen = 30): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}

export function TaskPillBar({ tasks, selectedTaskId, onSelect }: TaskPillBarProps) {
  if (tasks.length === 0) return null;

  return (
    <div className="task-pill-bar">
      {tasks.map((task) => {
        const label = `${task.worker_name}:${task.subject}`;
        const truncated = truncatePillText(label);
        const isSelected = task.id === selectedTaskId;

        const classes = [
          'task-pill',
          `task-pill${statusColorClass(task.status)}`,
          isSelected ? 'task-pill--selected' : '',
        ]
          .filter(Boolean)
          .join(' ');

        return (
          <button
            key={task.id}
            className={classes}
            data-testid={`task-pill-${task.id}`}
            onClick={() => onSelect(task.id)}
          >
            {truncated}
          </button>
        );
      })}
    </div>
  );
}
