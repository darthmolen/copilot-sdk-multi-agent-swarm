import { describe, it, expect } from 'vitest';
import { swarmReducer, initialState, isThinking, multiSwarmReducer, initialMultiSwarmState } from '../hooks/useSwarmState';
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

  it('handles leader.report_delta by accumulating into leaderReport', () => {
    const e1: SwarmEvent = { type: 'leader.report_delta', data: { delta: 'Hello ' } };
    const s1 = swarmReducer(initialState, e1);
    expect(s1.leaderReport).toBe('Hello ');

    const e2: SwarmEvent = { type: 'leader.report_delta', data: { delta: 'World' } };
    const s2 = swarmReducer(s1, e2);
    expect(s2.leaderReport).toBe('Hello World');
  });

  it('leader.report replaces accumulated deltas', () => {
    const withDeltas: SwarmState = { ...initialState, leaderReport: 'partial...' };
    const event: SwarmEvent = { type: 'leader.report', data: { content: 'Final report' } };
    const result = swarmReducer(withDeltas, event);
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

  it('task.created captures swarm_id from event data', () => {
    const task: Task = {
      id: 't1', subject: 'X', description: 'D', worker_role: 'R',
      worker_name: 'w', status: 'pending', blocked_by: [], result: '',
    };
    const event: SwarmEvent = { type: 'task.created', data: { task, swarm_id: 'swarm-abc' } };
    const result = swarmReducer(initialState, event);
    expect(result.tasks[0].swarm_id).toBe('swarm-abc');
  });

  it('agent.spawned captures swarm_id from event data', () => {
    const agent: AgentInfo = {
      name: 'w1', role: 'R', display_name: 'W1', status: 'idle', tasks_completed: 0,
    };
    const event: SwarmEvent = { type: 'agent.spawned', data: { agent, swarm_id: 'swarm-xyz' } };
    const result = swarmReducer(initialState, event);
    expect(result.agents[0].swarm_id).toBe('swarm-xyz');
  });

  it('inbox.message captures swarm_id from event data', () => {
    const message: InboxMessage = {
      sender: 'a', recipient: 'b', content: 'hi', timestamp: '2026-01-01T00:00:00Z',
    };
    const event: SwarmEvent = { type: 'inbox.message', data: { message, swarm_id: 's1' } };
    const result = swarmReducer(initialState, event);
    expect(result.messages[0].swarm_id).toBe('s1');
  });
});

describe('multiSwarmReducer', () => {
  it('dispatches events to correct swarm only', () => {

    const task: Task = {
      id: 'task-0', subject: 'A', description: 'D', worker_role: 'R',
      worker_name: 'w', status: 'pending', blocked_by: [], result: '',
    };

    let state = multiSwarmReducer(initialMultiSwarmState, {
      type: 'swarm.add', swarmId: 's1',
    });
    state = multiSwarmReducer(state, {
      type: 'swarm.add', swarmId: 's2',
    });
    state = multiSwarmReducer(state, {
      type: 'swarm.event', swarmId: 's1',
      event: { type: 'task.created', data: { task } },
    });

    expect(state.swarms['s1'].tasks).toHaveLength(1);
    expect(state.swarms['s2'].tasks).toHaveLength(0);
  });

  it('two swarms with same task ID stay separate', () => {

    const taskA: Task = {
      id: 'task-0', subject: 'Swarm A task', description: 'D', worker_role: 'R',
      worker_name: 'w', status: 'pending', blocked_by: [], result: '',
    };
    const taskB: Task = {
      id: 'task-0', subject: 'Swarm B task', description: 'D', worker_role: 'R',
      worker_name: 'w', status: 'pending', blocked_by: [], result: '',
    };

    let state = multiSwarmReducer(initialMultiSwarmState, { type: 'swarm.add', swarmId: 's1' });
    state = multiSwarmReducer(state, { type: 'swarm.add', swarmId: 's2' });
    state = multiSwarmReducer(state, {
      type: 'swarm.event', swarmId: 's1',
      event: { type: 'task.created', data: { task: taskA } },
    });
    state = multiSwarmReducer(state, {
      type: 'swarm.event', swarmId: 's2',
      event: { type: 'task.created', data: { task: taskB } },
    });

    expect(state.swarms['s1'].tasks[0].subject).toBe('Swarm A task');
    expect(state.swarms['s2'].tasks[0].subject).toBe('Swarm B task');
  });

  it('completed swarm moves to completedSwarmIds', () => {


    let state = multiSwarmReducer(initialMultiSwarmState, { type: 'swarm.add', swarmId: 's1' });
    state = multiSwarmReducer(state, {
      type: 'swarm.event', swarmId: 's1',
      event: { type: 'swarm.phase_changed', data: { phase: 'complete' } },
    });

    expect(state.activeSwarmIds).not.toContain('s1');
    expect(state.completedSwarmIds).toContain('s1');
    expect(state.swarms['s1']).toBeDefined(); // data still accessible
  });

  it('removeSwarm frees all data', () => {


    let state = multiSwarmReducer(initialMultiSwarmState, { type: 'swarm.add', swarmId: 's1' });
    state = multiSwarmReducer(state, { type: 'swarm.remove', swarmId: 's1' });

    expect(state.swarms['s1']).toBeUndefined();
    expect(state.activeSwarmIds).not.toContain('s1');
    expect(state.completedSwarmIds).not.toContain('s1');
  });

  it('hard cap at 10 swarms auto-dismisses oldest completed', () => {


    let state = initialMultiSwarmState;
    // Add 10 swarms, complete the first 5
    for (let i = 0; i < 10; i++) {
      state = multiSwarmReducer(state, { type: 'swarm.add', swarmId: `s${i}` });
    }
    for (let i = 0; i < 5; i++) {
      state = multiSwarmReducer(state, {
        type: 'swarm.event', swarmId: `s${i}`,
        event: { type: 'swarm.phase_changed', data: { phase: 'complete' } },
      });
    }

    // Add 11th — should evict oldest completed (s0)
    state = multiSwarmReducer(state, { type: 'swarm.add', swarmId: 's10' });
    expect(state.swarms['s0']).toBeUndefined();
    expect(Object.keys(state.swarms)).toHaveLength(10);
  });
});

describe('isThinking', () => {
  it('is true when phase is planning', () => {
    expect(isThinking('planning')).toBe(true);
  });

  it('is true when phase is executing', () => {
    expect(isThinking('executing')).toBe(true);
  });

  it('is true when phase is synthesizing', () => {
    expect(isThinking('synthesizing')).toBe(true);
  });

  it('is false when phase is complete', () => {
    expect(isThinking('complete')).toBe(false);
  });

  it('is false when phase is null', () => {
    expect(isThinking(null)).toBe(false);
  });

  it('is false when phase is cancelled', () => {
    expect(isThinking('cancelled')).toBe(false);
  });
});

describe('activeTools tracking', () => {
  it('agent.tool_call adds a running tool to activeTools', () => {
    const event: SwarmEvent = {
      type: 'agent.tool_call',
      data: { agent_name: 'worker-1', tool_name: 'web_search', tool_call_id: 'tc-1' },
    };
    const result = swarmReducer(initialState, event);
    expect(result.activeTools).toHaveLength(1);
    expect(result.activeTools[0]).toEqual({
      toolCallId: 'tc-1',
      toolName: 'web_search',
      agentName: 'worker-1',
      status: 'running',
    });
  });

  it('agent.tool_result marks tool as complete when success=true', () => {
    const stateWithTool: SwarmState = {
      ...initialState,
      activeTools: [{ toolCallId: 'tc-1', toolName: 'web_search', agentName: 'worker-1', status: 'running' }],
    };
    const event: SwarmEvent = {
      type: 'agent.tool_result',
      data: { agent_name: 'worker-1', tool_call_id: 'tc-1', success: true },
    };
    const result = swarmReducer(stateWithTool, event);
    expect(result.activeTools[0].status).toBe('complete');
  });

  it('agent.tool_result marks tool as failed when success=false', () => {
    const stateWithTool: SwarmState = {
      ...initialState,
      activeTools: [{ toolCallId: 'tc-1', toolName: 'web_search', agentName: 'worker-1', status: 'running' }],
    };
    const event: SwarmEvent = {
      type: 'agent.tool_result',
      data: { agent_name: 'worker-1', tool_call_id: 'tc-1', success: false },
    };
    const result = swarmReducer(stateWithTool, event);
    expect(result.activeTools[0].status).toBe('failed');
  });

  it('multiple tool calls accumulate in activeTools', () => {
    let state = swarmReducer(initialState, {
      type: 'agent.tool_call',
      data: { agent_name: 'worker-1', tool_name: 'web_search', tool_call_id: 'tc-1' },
    });
    state = swarmReducer(state, {
      type: 'agent.tool_call',
      data: { agent_name: 'worker-1', tool_name: 'read_file', tool_call_id: 'tc-2' },
    });
    expect(state.activeTools).toHaveLength(2);
    expect(state.activeTools[0].toolName).toBe('web_search');
    expect(state.activeTools[1].toolName).toBe('read_file');
  });

  it('completing one tool does not affect others', () => {
    const stateWithTools: SwarmState = {
      ...initialState,
      activeTools: [
        { toolCallId: 'tc-1', toolName: 'web_search', agentName: 'worker-1', status: 'running' },
        { toolCallId: 'tc-2', toolName: 'read_file', agentName: 'worker-1', status: 'running' },
      ],
    };
    const event: SwarmEvent = {
      type: 'agent.tool_result',
      data: { agent_name: 'worker-1', tool_call_id: 'tc-1', success: true },
    };
    const result = swarmReducer(stateWithTools, event);
    expect(result.activeTools[0].status).toBe('complete');
    expect(result.activeTools[1].status).toBe('running');
  });

  it('initialState includes empty activeTools array', () => {
    expect(initialState.activeTools).toEqual([]);
  });
});
