import type { Task, TaskStatus } from '../types/swarm';

interface TaskBoardProps {
  tasks: Task[];
}

const COLUMNS: { key: TaskStatus; label: string }[] = [
  { key: 'blocked', label: 'Blocked' },
  { key: 'pending', label: 'Pending' },
  { key: 'in_progress', label: 'In Progress' },
  { key: 'completed', label: 'Completed' },
  { key: 'failed', label: 'Failed' },
  { key: 'timeout', label: 'Timeout' },
];

function TaskCard({ task }: { task: Task }) {
  return (
    <div className={`task-card task-${task.status}`}>
      <h4 className="task-subject">{task.subject}</h4>
      <p className="task-worker">{task.worker_name || task.worker_role}</p>
      <span className="task-status-badge">{task.status}</span>
    </div>
  );
}

export function TaskBoard({ tasks }: TaskBoardProps) {
  return (
    <div className="task-board">
      <h2>Task Board</h2>
      <div className="kanban">
        {COLUMNS.map((col) => {
          const colTasks = tasks.filter((t) => t.status === col.key);
          return (
            <div key={col.key} className="kanban-column">
              <h3>
                {col.label} <span className="count">({colTasks.length})</span>
              </h3>
              <div className="kanban-cards">
                {colTasks.map((task) => (
                  <TaskCard key={task.id} task={task} />
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
