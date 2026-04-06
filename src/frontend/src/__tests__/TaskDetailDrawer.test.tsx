import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TaskDetailDrawer } from '../components/TaskDetailDrawer';
import type { Task } from '../types/swarm';

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    subject: 'Deploy API',
    description: 'Deploy the REST API to staging environment',
    worker_role: 'devops',
    worker_name: 'infra-agent',
    status: 'completed',
    blocked_by: [],
    result: 'Deployment successful. API is live at https://staging.example.com',
    ...overrides,
  };
}

describe('TaskDetailDrawer', () => {
  // 1. shows task subject and description
  it('shows task subject and description', () => {
    render(<TaskDetailDrawer task={makeTask()} onClose={() => {}} />);

    expect(screen.getByText('Deploy API')).toBeTruthy();
    expect(screen.getByText('Deploy the REST API to staging environment')).toBeTruthy();
  });

  // 2. shows worker name and role
  it('shows worker name and role', () => {
    render(
      <TaskDetailDrawer
        task={makeTask({ worker_name: 'infra-agent', worker_role: 'devops' })}
        onClose={() => {}}
      />,
    );

    expect(screen.getByText(/infra-agent/)).toBeTruthy();
    expect(screen.getByText(/devops/)).toBeTruthy();
  });

  // 3. shows result in monospace block
  it('shows result in monospace block', () => {
    render(
      <TaskDetailDrawer
        task={makeTask({ result: 'Deployment successful. API is live.' })}
        onClose={() => {}}
      />,
    );

    const resultBlock = screen.getByTestId('task-detail-result');
    expect(resultBlock.textContent).toContain('Deployment successful. API is live.');
    expect(resultBlock.tagName.toLowerCase()).toBe('pre');
  });

  // 4. calls onClose when close button clicked
  it('calls onClose when close button clicked', () => {
    const onClose = vi.fn();
    render(<TaskDetailDrawer task={makeTask()} onClose={onClose} />);

    fireEvent.click(screen.getByTestId('task-detail-close'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  // 5. shows status badge with correct color class
  it('shows status badge with correct color class', () => {
    render(
      <TaskDetailDrawer task={makeTask({ status: 'completed' })} onClose={() => {}} />,
    );

    const badge = screen.getByTestId('task-detail-status');
    expect(badge.className).toContain('task-detail-drawer__status--completed');
    expect(badge.textContent).toBe('completed');
  });

  it('shows failed status badge with correct color class', () => {
    render(
      <TaskDetailDrawer task={makeTask({ status: 'failed' })} onClose={() => {}} />,
    );

    const badge = screen.getByTestId('task-detail-status');
    expect(badge.className).toContain('task-detail-drawer__status--failed');
    expect(badge.textContent).toBe('failed');
  });

  // 6. handles empty result gracefully
  it('handles empty result gracefully', () => {
    render(
      <TaskDetailDrawer task={makeTask({ result: '' })} onClose={() => {}} />,
    );

    // Should not render the result block when result is empty
    expect(screen.queryByTestId('task-detail-result')).toBeNull();
  });
});
