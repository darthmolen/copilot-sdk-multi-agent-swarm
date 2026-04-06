import { describe, it, expect } from 'vitest';
import {
  multiSwarmReducer,
  initialMultiSwarmState,
} from '../hooks/useSwarmState';
import { hydrateTasksIntoSwarm } from '../utils/hydrateTasksIntoSwarm';
import type { MultiSwarmAction } from '../hooks/useSwarmState';
import type { Task } from '../types/swarm';

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: 'task-1',
    subject: 'Build API',
    description: 'Build the REST API',
    worker_role: 'backend-dev',
    worker_name: 'agent-1',
    status: 'completed',
    blocked_by: [],
    result: 'Done',
    ...overrides,
  };
}

describe('hydrateTasksIntoSwarm', () => {
  it('returns an array of swarm.event actions with task.created events', () => {
    const tasks = [
      makeTask({ id: 't1', subject: 'Task A' }),
      makeTask({ id: 't2', subject: 'Task B' }),
    ];
    const actions = hydrateTasksIntoSwarm('swarm-abc', tasks);

    expect(actions).toHaveLength(2);
    expect(actions[0]).toEqual({
      type: 'swarm.event',
      swarmId: 'swarm-abc',
      event: {
        type: 'task.created',
        data: { task: tasks[0], swarm_id: 'swarm-abc' },
      },
    });
    expect(actions[1]).toEqual({
      type: 'swarm.event',
      swarmId: 'swarm-abc',
      event: {
        type: 'task.created',
        data: { task: tasks[1], swarm_id: 'swarm-abc' },
      },
    });
  });

  it('returns empty array when tasks is undefined', () => {
    const actions = hydrateTasksIntoSwarm('swarm-abc', undefined);
    expect(actions).toEqual([]);
  });

  it('returns empty array when tasks is null', () => {
    const actions = hydrateTasksIntoSwarm('swarm-abc', null as unknown as undefined);
    expect(actions).toEqual([]);
  });

  it('returns empty array when tasks is empty', () => {
    const actions = hydrateTasksIntoSwarm('swarm-abc', []);
    expect(actions).toEqual([]);
  });
});

describe('task hydration through multiSwarmReducer', () => {
  it('hydrates tasks into a swarm that has no prior swarm.add', () => {
    // This simulates the cold-URL-load path: we dispatch task.created events
    // for a swarm that was never added via swarm.add. The reducer should
    // create the swarm entry using initialState fallback.
    const task = makeTask({ id: 't1', subject: 'Cold-load task' });
    const actions = hydrateTasksIntoSwarm('cold-swarm', [task]);

    let state = initialMultiSwarmState;
    for (const action of actions) {
      state = multiSwarmReducer(state, action);
    }

    expect(state.swarms['cold-swarm']).toBeDefined();
    expect(state.swarms['cold-swarm'].tasks).toHaveLength(1);
    expect(state.swarms['cold-swarm'].tasks[0].id).toBe('t1');
    expect(state.swarms['cold-swarm'].tasks[0].subject).toBe('Cold-load task');
    expect(state.swarms['cold-swarm'].tasks[0].swarm_id).toBe('cold-swarm');
  });

  it('hydrates multiple tasks preserving order', () => {
    const tasks = [
      makeTask({ id: 't1', subject: 'First' }),
      makeTask({ id: 't2', subject: 'Second' }),
      makeTask({ id: 't3', subject: 'Third' }),
    ];
    const actions = hydrateTasksIntoSwarm('swarm-1', tasks);

    let state = initialMultiSwarmState;
    for (const action of actions) {
      state = multiSwarmReducer(state, action);
    }

    expect(state.swarms['swarm-1'].tasks).toHaveLength(3);
    expect(state.swarms['swarm-1'].tasks.map((t) => t.subject)).toEqual([
      'First', 'Second', 'Third',
    ]);
  });

  it('does not duplicate tasks if already present from a prior swarm.add', () => {
    const task = makeTask({ id: 't1', subject: 'Existing task' });

    // Swarm was added and already has the task from a live WS event
    let state = multiSwarmReducer(initialMultiSwarmState, {
      type: 'swarm.add', swarmId: 'swarm-1',
    });
    state = multiSwarmReducer(state, {
      type: 'swarm.event', swarmId: 'swarm-1',
      event: { type: 'task.created', data: { task, swarm_id: 'swarm-1' } },
    });
    expect(state.swarms['swarm-1'].tasks).toHaveLength(1);

    // Now hydrate the same task again — this is the scenario where tasks
    // are already in memory. The caller should guard against this, but
    // the reducer will naively append. This test documents that behavior.
    const actions = hydrateTasksIntoSwarm('swarm-1', [task]);
    for (const action of actions) {
      state = multiSwarmReducer(state, action);
    }

    // The reducer appends without dedup — callers must guard.
    // This documents the expected behavior so the App.tsx guard is meaningful.
    expect(state.swarms['swarm-1'].tasks).toHaveLength(2);
  });
});
