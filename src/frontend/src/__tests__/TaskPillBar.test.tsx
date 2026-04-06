import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TaskPillBar } from '../components/TaskPillBar';
import type { Task } from '../types/swarm';

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    subject: 'Deploy API',
    description: 'Deploy the REST API to staging',
    worker_role: 'devops',
    worker_name: 'infra-agent',
    status: 'pending',
    blocked_by: [],
    result: '',
    ...overrides,
  };
}

describe('TaskPillBar', () => {
  // 1. renders pill for each task with worker_name:subject format
  it('renders pill for each task with worker_name:subject format', () => {
    const tasks: Task[] = [
      makeTask({ id: 'task-1', worker_name: 'infra-agent', subject: 'Deploy API' }),
      makeTask({ id: 'task-2', worker_name: 'qa-agent', subject: 'Run Tests' }),
    ];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);

    expect(screen.getByText('infra-agent:Deploy API')).toBeTruthy();
    expect(screen.getByText('qa-agent:Run Tests')).toBeTruthy();
  });

  // 2. truncates long pill text to ~30 chars
  it('truncates long pill text to ~30 chars', () => {
    const tasks: Task[] = [
      makeTask({
        id: 'task-1',
        worker_name: 'infrastructure-deployment-agent',
        subject: 'Deploy the entire microservices stack',
      }),
    ];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);

    const pill = screen.getByTestId('task-pill-task-1');
    expect(pill.textContent!.length).toBeLessThanOrEqual(33); // 30 + "..."
    expect(pill.textContent).toContain('...');
  });

  // 3. applies correct color class for completed status
  it('applies correct color class for completed status', () => {
    const tasks: Task[] = [
      makeTask({ id: 'task-1', status: 'completed' }),
    ];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);

    const pill = screen.getByTestId('task-pill-task-1');
    expect(pill.className).toContain('task-pill--completed');
  });

  // 4. applies correct color class for failed status
  it('applies correct color class for failed status', () => {
    const tasks: Task[] = [
      makeTask({ id: 'task-1', status: 'failed' }),
    ];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);

    const pill = screen.getByTestId('task-pill-task-1');
    expect(pill.className).toContain('task-pill--failed');
  });

  // 5. calls onSelect when pill clicked
  it('calls onSelect when pill clicked', () => {
    const onSelect = vi.fn();
    const tasks: Task[] = [
      makeTask({ id: 'task-42' }),
    ];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={onSelect} />);

    fireEvent.click(screen.getByTestId('task-pill-task-42'));
    expect(onSelect).toHaveBeenCalledWith('task-42');
  });

  // 6. renders nothing when tasks array is empty
  it('renders nothing when tasks array is empty', () => {
    const { container } = render(
      <TaskPillBar tasks={[]} selectedTaskId={null} onSelect={() => {}} />,
    );

    expect(container.innerHTML).toBe('');
  });

  // 7. selected pill has selected class
  it('selected pill has selected class', () => {
    const tasks: Task[] = [
      makeTask({ id: 'task-1' }),
      makeTask({ id: 'task-2' }),
    ];
    render(<TaskPillBar tasks={tasks} selectedTaskId="task-1" onSelect={() => {}} />);

    const selected = screen.getByTestId('task-pill-task-1');
    const unselected = screen.getByTestId('task-pill-task-2');
    expect(selected.className).toContain('task-pill--selected');
    expect(unselected.className).not.toContain('task-pill--selected');
  });

  // 8. applies correct color classes for all status variants
  it('applies correct color class for pending status', () => {
    const tasks: Task[] = [makeTask({ id: 'task-1', status: 'pending' })];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);
    expect(screen.getByTestId('task-pill-task-1').className).toContain('task-pill--pending');
  });

  it('applies correct color class for in_progress status', () => {
    const tasks: Task[] = [makeTask({ id: 'task-1', status: 'in_progress' })];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);
    expect(screen.getByTestId('task-pill-task-1').className).toContain('task-pill--in_progress');
  });

  it('applies correct color class for timeout status', () => {
    const tasks: Task[] = [makeTask({ id: 'task-1', status: 'timeout' })];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);
    expect(screen.getByTestId('task-pill-task-1').className).toContain('task-pill--timeout');
  });

  it('applies correct color class for blocked status', () => {
    const tasks: Task[] = [makeTask({ id: 'task-1', status: 'blocked' })];
    render(<TaskPillBar tasks={tasks} selectedTaskId={null} onSelect={() => {}} />);
    expect(screen.getByTestId('task-pill-task-1').className).toContain('task-pill--blocked');
  });
});
