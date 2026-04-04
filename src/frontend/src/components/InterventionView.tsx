import { useState, useRef, useCallback } from 'react';
import { TemplateEditorPanel } from './TemplateEditorPanel';
import { ChatPanel } from './ChatPanel';
import type { Task } from '../types/swarm';

/**
 * Simple vertical split layout used as a fallback when ResizableLayout
 * does not yet support direction="vertical". Once the vertical mode is
 * merged, this can be replaced with ResizableLayout direction="vertical".
 */
function VerticalSplitLayout({
  top,
  bottom,
  defaultTopPercent = 50,
}: {
  top: React.ReactNode;
  bottom: React.ReactNode;
  defaultTopPercent?: number;
}) {
  const [topPercent, setTopPercent] = useState(defaultTopPercent);
  const containerRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const handleMouseDown = useCallback(() => {
    dragging.current = true;
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';

    const handleMouseMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const pct = ((e.clientY - rect.top) / rect.height) * 100;
      setTopPercent(Math.min(80, Math.max(20, pct)));
    };

    const handleMouseUp = () => {
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };

    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
  }, []);

  return (
    <div ref={containerRef} className="vertical-split-layout">
      <div
        className="vertical-split-layout__top"
        style={{ flexBasis: `${topPercent}%` }}
      >
        {top}
      </div>
      <div
        className="vertical-split-layout__divider"
        onMouseDown={handleMouseDown}
      />
      <div
        className="vertical-split-layout__bottom"
        style={{ flexBasis: `${100 - topPercent}%` }}
      >
        {bottom}
      </div>
    </div>
  );
}

function statusColor(status: string): string {
  switch (status) {
    case 'failed':
      return '#ef4444';
    case 'timeout':
      return '#f59e0b';
    default:
      return '#6b7280';
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'failed':
      return 'FAILED';
    case 'timeout':
      return 'TIMEOUT';
    default:
      return status.toUpperCase();
  }
}

interface InterventionViewProps {
  swarmId: string;
  templateKey: string;
  tasks: Task[];
  selectedTaskId: string;
  onSelectTask: (taskId: string) => void;
  agentOutputs: Record<string, string>;
  onBack: () => void;
  onSaveAndRetry: () => void;
}

export function InterventionView({
  swarmId,
  templateKey,
  tasks,
  selectedTaskId,
  onSelectTask,
  agentOutputs,
  onBack,
  onSaveAndRetry,
}: InterventionViewProps) {
  const [hasModifications, setHasModifications] = useState(false);

  const selectedTask = tasks.find((t) => t.id === selectedTaskId) ?? tasks[0];
  const taskOutput = selectedTask
    ? agentOutputs[selectedTask.worker_name] ?? ''
    : '';

  // Extract error lines from task output for highlighting
  const outputLines = taskOutput.split('\n');

  // Scroll ref for task logs
  const logsRef = useRef<HTMLDivElement>(null);

  return (
    <div className="intervention-view">
      {/* Header */}
      <header className="intervention-header">
        <button className="back-button" onClick={onBack}>
          &larr; Dashboard
        </button>
        <span className="intervention-swarm-label">
          Intervention -- {swarmId.slice(0, 8)}
        </span>
        <div className="intervention-task-pills">
          {tasks.map((task) => (
            <button
              key={task.id}
              className={`intervention-pill ${task.id === selectedTaskId ? 'intervention-pill--active' : ''}`}
              style={
                task.id === selectedTaskId
                  ? { borderColor: '#3b82f6', background: '#1e3a5f' }
                  : { borderColor: statusColor(task.status) }
              }
              onClick={() => onSelectTask(task.id)}
              title={`${task.subject} (${task.status})`}
            >
              <span
                className="intervention-pill__dot"
                style={{ background: statusColor(task.status) }}
              />
              <span className="intervention-pill__label">
                {task.worker_name}
              </span>
              <span className="intervention-pill__status">
                {statusLabel(task.status)}
              </span>
            </button>
          ))}
        </div>
      </header>

      {/* Body: two-column layout */}
      <div className="intervention-body">
        {/* Left column: Template editor panel (45%) */}
        <div className="intervention-left">
          {selectedTask && (
            <TemplateEditorPanel
              key={`${templateKey}-${selectedTask.worker_name}`}
              templateKey={templateKey}
              workerName={selectedTask.worker_name}
              onModified={setHasModifications}
            />
          )}
        </div>

        {/* Right column: Logs + Chat (55%) */}
        <div className="intervention-right">
          <VerticalSplitLayout
            top={
              <div className="intervention-logs" ref={logsRef}>
                <div className="intervention-logs__header">
                  <h3>
                    Task Logs{' '}
                    {selectedTask && (
                      <span className="intervention-logs__task-name">
                        -- {selectedTask.subject}
                      </span>
                    )}
                  </h3>
                </div>
                <div className="intervention-logs__content">
                  {outputLines.length === 0 ||
                  (outputLines.length === 1 && outputLines[0] === '') ? (
                    <p className="empty-text">
                      No agent output recorded for this task.
                    </p>
                  ) : (
                    outputLines.map((line, i) => {
                      const isError =
                        /error|exception|traceback|failed|fatal/i.test(line);
                      return (
                        <div
                          key={i}
                          className={`intervention-log-line ${isError ? 'intervention-log-line--error' : ''}`}
                        >
                          {line}
                        </div>
                      );
                    })
                  )}
                </div>
              </div>
            }
            bottom={
              <ChatPanel
                messages={[]}
                streamingMessage={null}
                sessionStarting={false}
                activeTools={[]}
                onSend={() => {
                  /* Chat disabled for now -- will be wired to intervention endpoint later */
                }}
                chatEnabled={false}
              />
            }
            defaultTopPercent={55}
          />
        </div>
      </div>

      {/* Footer */}
      <footer className="intervention-footer">
        <button
          className="intervention-save-retry-btn"
          onClick={onSaveAndRetry}
          disabled={!hasModifications}
          title={
            hasModifications
              ? 'Save all modified templates and retry failed tasks'
              : 'No modifications to save'
          }
        >
          Save All &amp; Retry
        </button>
      </footer>
    </div>
  );
}
