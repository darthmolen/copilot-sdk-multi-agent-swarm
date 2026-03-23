import { describe, it, expect } from 'vitest';
import { swarmReducer, initialState } from '../hooks/useSwarmState';
import type { SwarmState, SwarmEvent, Task, AgentInfo, InboxMessage } from '../types/swarm';

describe('swarmReducer', () => {
  it('handles swarm.phase_changed', () => {
    const event: SwarmEvent = { type: 'swarm.phase_changed', data: { phase: 'planning' } };
    const result = swarmReducer(initialState, event);
    expect(result.phase).toBe('planning');
  });

  it('handles task.created', () => {
    const task: Task = {
      id: 't1',
      subject: 'Build API',
      description: 'Build the REST API',
      worker_role: 'backend-dev',
      worker_name: 'agent-1',
      status: 'pending',
      blocked_by: [],
      result: '',
    };
    const event: SwarmEvent = { type: 'task.created', data: { task } };
    const result = swarmReducer(initialState, event);
    expect(result.tasks).toHaveLength(1);
    expect(result.tasks[0].id).toBe('t1');
    expect(result.tasks[0].subject).toBe('Build API');
  });

  it('handles task.updated', () => {
    const existingTask: Task = {
      id: 't1',
      subject: 'Build API',
      description: 'Build the REST API',
      worker_role: 'backend-dev',
      worker_name: 'agent-1',
      status: 'pending',
      blocked_by: [],
      result: '',
    };
    const stateWithTask: SwarmState = { ...initialState, tasks: [existingTask] };
    const updatedTask: Task = { ...existingTask, status: 'completed', result: 'Done' };
    const event: SwarmEvent = { type: 'task.updated', data: { task: updatedTask } };
    const result = swarmReducer(stateWithTask, event);
    expect(result.tasks[0].status).toBe('completed');
    expect(result.tasks[0].result).toBe('Done');
  });

  it('handles agent.spawned', () => {
    const agent: AgentInfo = {
      name: 'worker-1',
      role: 'backend-dev',
      display_name: 'Backend Developer',
      status: 'idle',
      tasks_completed: 0,
    };
    const event: SwarmEvent = { type: 'agent.spawned', data: { agent } };
    const result = swarmReducer(initialState, event);
    expect(result.agents).toHaveLength(1);
    expect(result.agents[0].name).toBe('worker-1');
  });

  it('handles agent.status_changed', () => {
    const agent: AgentInfo = {
      name: 'worker-1',
      role: 'backend-dev',
      display_name: 'Backend Developer',
      status: 'idle',
      tasks_completed: 0,
    };
    const stateWithAgent: SwarmState = { ...initialState, agents: [agent] };
    const event: SwarmEvent = {
      type: 'agent.status_changed',
      data: { agent_name: 'worker-1', status: 'working' },
    };
    const result = swarmReducer(stateWithAgent, event);
    expect(result.agents[0].status).toBe('working');
  });

  it('handles agent.message_delta by appending text', () => {
    const event1: SwarmEvent = {
      type: 'agent.message_delta',
      data: { agent_name: 'worker-1', delta: 'Hello ' },
    };
    const state1 = swarmReducer(initialState, event1);
    expect(state1.agentOutputs['worker-1']).toBe('Hello ');

    const event2: SwarmEvent = {
      type: 'agent.message_delta',
      data: { agent_name: 'worker-1', delta: 'World' },
    };
    const state2 = swarmReducer(state1, event2);
    expect(state2.agentOutputs['worker-1']).toBe('Hello World');
  });

  it('handles agent.message by setting final content', () => {
    const stateWithDelta: SwarmState = {
      ...initialState,
      agentOutputs: { 'worker-1': 'partial...' },
    };
    const event: SwarmEvent = {
      type: 'agent.message',
      data: { agent_name: 'worker-1', content: 'Final output' },
    };
    const result = swarmReducer(stateWithDelta, event);
    expect(result.agentOutputs['worker-1']).toBe('Final output');
  });

  it('handles inbox.message', () => {
    const message: InboxMessage = {
      sender: 'leader',
      recipient: 'worker-1',
      content: 'Start working on task t1',
      timestamp: '2026-01-01T00:00:00Z',
    };
    const event: SwarmEvent = { type: 'inbox.message', data: { message } };
    const result = swarmReducer(initialState, event);
    expect(result.messages).toHaveLength(1);
    expect(result.messages[0].sender).toBe('leader');
    expect(result.messages[0].content).toBe('Start working on task t1');
  });

  it('handles leader.plan', () => {
    const event: SwarmEvent = { type: 'leader.plan', data: { content: 'The plan is...' } };
    const result = swarmReducer(initialState, event);
    expect(result.leaderPlan).toBe('The plan is...');
  });

  it('handles leader.report', () => {
    const event: SwarmEvent = { type: 'leader.report', data: { content: 'Final report' } };
    const result = swarmReducer(initialState, event);
    expect(result.leaderReport).toBe('Final report');
  });

  it('handles round.started', () => {
    const event: SwarmEvent = { type: 'round.started', data: { round: 3 } };
    const result = swarmReducer(initialState, event);
    expect(result.roundNumber).toBe(3);
  });

  it('handles swarm.complete', () => {
    const event: SwarmEvent = { type: 'swarm.complete', data: {} };
    const result = swarmReducer(initialState, event);
    expect(result.phase).toBe('complete');
  });

  it('handles swarm.error', () => {
    const event: SwarmEvent = { type: 'swarm.error', data: { message: 'Something broke' } };
    const result = swarmReducer(initialState, event);
    expect(result.error).toBe('Something broke');
  });

  it('returns unchanged state for unknown event types', () => {
    const event: SwarmEvent = { type: 'unknown.event', data: { foo: 'bar' } };
    const result = swarmReducer(initialState, event);
    expect(result).toBe(initialState);
  });
});
