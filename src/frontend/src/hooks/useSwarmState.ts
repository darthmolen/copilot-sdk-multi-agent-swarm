import { useReducer } from 'react';
import type { SwarmState, SwarmEvent, Task, AgentInfo } from '../types/swarm';

export const initialState: SwarmState = {
  phase: null,
  tasks: [],
  agents: [],
  messages: [],
  leaderPlan: '',
  leaderReport: '',
  agentOutputs: {},
  roundNumber: 0,
  error: null,
};

export function swarmReducer(state: SwarmState, event: SwarmEvent): SwarmState {
  switch (event.type) {
    case 'swarm.phase_changed':
      return { ...state, phase: event.data.phase as SwarmState['phase'] };

    case 'task.created':
      return { ...state, tasks: [...state.tasks, event.data.task as Task] };

    case 'task.updated': {
      const updated = event.data.task as Task;
      return {
        ...state,
        tasks: state.tasks.map((t) => (t.id === updated.id ? { ...t, ...updated } : t)),
      };
    }

    case 'agent.spawned':
      return { ...state, agents: [...state.agents, event.data.agent as AgentInfo] };

    case 'agent.status_changed': {
      const { agent_name, status } = event.data as { agent_name: string; status: AgentInfo['status'] };
      return {
        ...state,
        agents: state.agents.map((a) =>
          a.name === agent_name ? { ...a, status } : a,
        ),
      };
    }

    case 'agent.message_delta': {
      const { agent_name, delta } = event.data as { agent_name: string; delta: string };
      return {
        ...state,
        agentOutputs: {
          ...state.agentOutputs,
          [agent_name]: (state.agentOutputs[agent_name] ?? '') + delta,
        },
      };
    }

    case 'agent.message': {
      const { agent_name, content } = event.data as { agent_name: string; content: string };
      return {
        ...state,
        agentOutputs: {
          ...state.agentOutputs,
          [agent_name]: content,
        },
      };
    }

    case 'inbox.message':
      return {
        ...state,
        messages: [
          ...state.messages,
          event.data.message as SwarmState['messages'][number],
        ],
      };

    case 'leader.plan':
      return { ...state, leaderPlan: event.data.content as string };

    case 'leader.report':
      return { ...state, leaderReport: event.data.content as string };

    case 'round.started':
      return { ...state, roundNumber: event.data.round as number };

    case 'swarm.complete':
      return { ...state, phase: 'complete' };

    case 'swarm.error':
      return { ...state, error: event.data.message as string };

    default:
      return state;
  }
}

export function useSwarmState() {
  const [state, dispatch] = useReducer(swarmReducer, initialState);
  return { state, dispatch };
}
