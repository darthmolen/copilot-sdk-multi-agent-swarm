import { useState, useEffect } from 'react';
import { TaskPillBar } from './TaskPillBar';
import { TaskDetailDrawer } from './TaskDetailDrawer';
import { ChatPanel } from './ChatPanel';
import type { Task, ChatEntry } from '../types/swarm';

export interface ReportRightPanelProps {
  swarmId?: string;
  tasks: Task[];
  entries: ChatEntry[];
  streamingMessage: { id: string; content: string } | null;
  sessionStarting: boolean;
  onSend: (message: string) => void;
  chatEnabled: boolean;
}

export function ReportRightPanel({
  swarmId,
  tasks,
  entries,
  streamingMessage,
  sessionStarting,
  onSend,
  chatEnabled,
}: ReportRightPanelProps) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  // Reset selection when swarm changes
  useEffect(() => {
    setSelectedTaskId(null);
  }, [swarmId]);

  const selectedTask = tasks.find((t) => t.id === selectedTaskId) ?? null;

  function handlePillSelect(taskId: string) {
    setSelectedTaskId((prev) => (prev === taskId ? null : taskId));
  }

  return (
    <div className="right-panel">
      <TaskPillBar
        tasks={tasks}
        selectedTaskId={selectedTaskId}
        onSelect={handlePillSelect}
      />
      {selectedTask && (
        <TaskDetailDrawer
          task={selectedTask}
          onClose={() => setSelectedTaskId(null)}
        />
      )}
      <ChatPanel
        entries={entries}
        streamingMessage={streamingMessage}
        sessionStarting={sessionStarting}
        onSend={onSend}
        chatEnabled={chatEnabled}
      />
    </div>
  );
}
