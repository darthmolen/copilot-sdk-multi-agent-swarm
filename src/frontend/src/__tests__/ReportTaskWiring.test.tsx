import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ReportRightPanel } from '../components/ReportRightPanel';
import type { Task, ChatEntry } from '../types/swarm';

// Mock marked to return raw text (avoids markdown parsing complexity in tests)
vi.mock('marked', () => ({
  marked: {
    parse: (md: string) => md,
  },
}));

// Mock DOMPurify to passthrough
vi.mock('dompurify', () => ({
  default: {
    sanitize: (html: string) => html,
  },
}));

// Mock hooks that interact with DOM/mermaid
vi.mock('../hooks/useAutoScroll', () => ({
  useAutoScroll: vi.fn(),
}));
vi.mock('../hooks/useMermaid', () => ({
  useMermaid: vi.fn(),
}));

// Mock StreamingMarkdown to render content directly
vi.mock('../components/StreamingMarkdown', () => ({
  StreamingMarkdown: ({ content }: { content: string }) => (
    <div data-testid="streaming-markdown">{content}</div>
  ),
}));

// Mock ChatInput to render a simple placeholder
vi.mock('../components/ChatInput', () => ({
  ChatInput: ({ onSend, disabled }: { onSend: (msg: string) => void; disabled: boolean }) => (
    <div data-testid="chat-input" data-disabled={disabled}>
      <button onClick={() => onSend('test')}>Send</button>
    </div>
  ),
}));

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    subject: 'Deploy API',
    description: 'Deploy the REST API to staging environment',
    worker_role: 'devops',
    worker_name: 'infra-agent',
    status: 'completed',
    blocked_by: [],
    result: 'Deployment successful',
    ...overrides,
  };
}

const defaultProps = {
  swarmId: 'swarm-1',
  tasks: [] as Task[],
  entries: [] as ChatEntry[],
  streamingMessage: null as { id: string; content: string } | null,
  sessionStarting: false,
  onSend: vi.fn(),
  chatEnabled: true,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ReportRightPanel — TaskPillBar + TaskDetailDrawer wiring', () => {
  // 1. TaskPillBar renders when tasks are present
  it('renders TaskPillBar when tasks are present', () => {
    const tasks = [
      makeTask({ id: 'task-1', worker_name: 'agent-a', subject: 'Do stuff' }),
      makeTask({ id: 'task-2', worker_name: 'agent-b', subject: 'Other stuff' }),
    ];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} />);

    expect(screen.getByTestId('task-pill-task-1')).toBeInTheDocument();
    expect(screen.getByTestId('task-pill-task-2')).toBeInTheDocument();
  });

  // 2. TaskPillBar does not render when tasks are empty
  it('does not render TaskPillBar when tasks are empty', () => {
    render(<ReportRightPanel {...defaultProps} tasks={[]} />);

    expect(screen.queryByTestId('task-pill-task-1')).not.toBeInTheDocument();
    // The pill bar container itself should not be present
    expect(document.querySelector('.task-pill-bar')).toBeNull();
  });

  // 3. Clicking a pill shows TaskDetailDrawer for that task
  it('shows TaskDetailDrawer when a pill is clicked', () => {
    const tasks = [
      makeTask({ id: 'task-1', subject: 'Deploy API', description: 'Deploy the REST API' }),
    ];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} />);

    // Initially no drawer
    expect(screen.queryByText('Deploy the REST API')).not.toBeInTheDocument();

    // Click the pill
    fireEvent.click(screen.getByTestId('task-pill-task-1'));

    // Drawer should appear with the task description
    expect(screen.getByText('Deploy the REST API')).toBeInTheDocument();
  });

  // 4. Clicking the same pill again closes the drawer (toggle behavior)
  it('closes TaskDetailDrawer when the same pill is clicked again', () => {
    const tasks = [
      makeTask({ id: 'task-1', subject: 'Deploy API', description: 'Deploy the REST API' }),
    ];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} />);

    // Click pill to open
    fireEvent.click(screen.getByTestId('task-pill-task-1'));
    expect(screen.getByText('Deploy the REST API')).toBeInTheDocument();

    // Click same pill to close
    fireEvent.click(screen.getByTestId('task-pill-task-1'));
    expect(screen.queryByText('Deploy the REST API')).not.toBeInTheDocument();
  });

  // 5. TaskDetailDrawer shows correct task details
  it('shows the correct task details in the drawer', () => {
    const tasks = [
      makeTask({
        id: 'task-1',
        subject: 'Deploy API',
        description: 'Deploy the REST API',
        worker_name: 'infra-agent',
        worker_role: 'devops',
        status: 'completed',
        result: 'Deployment successful',
      }),
    ];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} />);

    fireEvent.click(screen.getByTestId('task-pill-task-1'));

    // Subject is shown in the drawer header
    expect(screen.getByRole('heading', { name: 'Deploy API' })).toBeInTheDocument();
    // Worker info shown inside the drawer meta section
    const workerSpan = document.querySelector('.task-detail-drawer__worker');
    expect(workerSpan).not.toBeNull();
    expect(workerSpan!.textContent).toContain('infra-agent');
    expect(workerSpan!.textContent).toContain('devops');
    // Status
    expect(screen.getByTestId('task-detail-status')).toHaveTextContent('completed');
    // Result
    expect(screen.getByTestId('task-detail-result')).toHaveTextContent('Deployment successful');
  });

  // 6. ChatPanel remains visible when drawer is open
  it('keeps ChatPanel visible when TaskDetailDrawer is open', () => {
    const tasks = [makeTask({ id: 'task-1' })];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} chatEnabled={true} />);

    // ChatPanel present before opening drawer
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();

    // Open drawer
    fireEvent.click(screen.getByTestId('task-pill-task-1'));

    // ChatPanel still present
    expect(screen.getByTestId('chat-input')).toBeInTheDocument();
  });

  // 7. Clicking a different pill switches the drawer to that task
  it('switches drawer to different task when different pill is clicked', () => {
    const tasks = [
      makeTask({ id: 'task-1', subject: 'Deploy API', description: 'Deploy description' }),
      makeTask({ id: 'task-2', subject: 'Run Tests', description: 'Test description' }),
    ];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} />);

    // Click first task
    fireEvent.click(screen.getByTestId('task-pill-task-1'));
    expect(screen.getByText('Deploy description')).toBeInTheDocument();
    expect(screen.queryByText('Test description')).not.toBeInTheDocument();

    // Click second task
    fireEvent.click(screen.getByTestId('task-pill-task-2'));
    expect(screen.getByText('Test description')).toBeInTheDocument();
    expect(screen.queryByText('Deploy description')).not.toBeInTheDocument();
  });

  // 8. Close button on drawer closes it
  it('closes drawer when close button is clicked', () => {
    const tasks = [
      makeTask({ id: 'task-1', description: 'Deploy description' }),
    ];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} />);

    fireEvent.click(screen.getByTestId('task-pill-task-1'));
    expect(screen.getByText('Deploy description')).toBeInTheDocument();

    // Click close button on the drawer
    fireEvent.click(screen.getByTestId('task-detail-close'));
    expect(screen.queryByText('Deploy description')).not.toBeInTheDocument();
  });

  // 9. Selected pill has selected class
  it('applies selected class to the active pill', () => {
    const tasks = [
      makeTask({ id: 'task-1' }),
      makeTask({ id: 'task-2' }),
    ];
    render(<ReportRightPanel {...defaultProps} tasks={tasks} />);

    fireEvent.click(screen.getByTestId('task-pill-task-1'));

    expect(screen.getByTestId('task-pill-task-1').className).toContain('task-pill--selected');
    expect(screen.getByTestId('task-pill-task-2').className).not.toContain('task-pill--selected');
  });
});
