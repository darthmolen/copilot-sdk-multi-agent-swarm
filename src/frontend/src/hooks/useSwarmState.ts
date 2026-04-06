import { useReducer } from 'react';
import type { SwarmState, SwarmPhase, SwarmEvent, Task, AgentInfo, ActiveTool } from '../types/swarm';

export const initialState: SwarmState = {
  phase: null,
  tasks: [],
  agents: [],
  messages: [],
  leaderPlan: '',
  leaderReport: '',
  agentOutputs: {},
  activeTools: [],
  roundNumber: 0,
  error: null,
};

export function swarmReducer(state: SwarmState, event: SwarmEvent): SwarmState {
  switch (event.type) {
    case 'swarm.phase_changed':
      return { ...state, phase: event.data.phase as SwarmState['phase'] };

    case 'task.created': {
      const newTask = { ...(event.data.task as Task) };
      if (event.data.swarm_id) newTask.swarm_id = event.data.swarm_id as string;
      return { ...state, tasks: [...state.tasks, newTask] };
    }

    case 'task.updated': {
      const updated = event.data.task as Task;
      return {
        ...state,
        tasks: state.tasks.map((t) => (t.id === updated.id ? { ...t, ...updated } : t)),
      };
    }

    case 'agent.spawned': {
      const newAgent = { ...(event.data.agent as AgentInfo) };
      if (event.data.swarm_id) newAgent.swarm_id = event.data.swarm_id as string;
      return { ...state, agents: [...state.agents, newAgent] };
    }

    case 'agent.status_changed': {
      const name = (event.data.name ?? event.data.agent_name) as string;
      const status = event.data.status as AgentInfo['status'];
      const tasksCompleted = event.data.tasks_completed as number | undefined;
      return {
        ...state,
        agents: state.agents.map((a) =>
          a.name === name
            ? { ...a, status, ...(tasksCompleted !== undefined ? { tasks_completed: tasksCompleted } : {}) }
            : a,
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

    case 'inbox.message': {
      // Handle both shapes: {message: {...}} (nested) and {sender, recipient, content} (flat)
      const msg = { ...((event.data.message ?? event.data) as SwarmState['messages'][number]) };
      if (!msg || !msg.sender) return state;
      if (event.data.swarm_id) msg.swarm_id = event.data.swarm_id as string;
      return {
        ...state,
        messages: [
          ...state.messages,
          msg,
        ],
      };
    }

    case 'leader.plan':
      return { ...state, leaderPlan: event.data.content as string };

    case 'leader.report_delta':
      return { ...state, leaderReport: state.leaderReport + (event.data.delta as string) };

    case 'leader.report':
      return { ...state, leaderReport: event.data.content as string };

    case 'round.started':
    case 'swarm.round_start':
      return { ...state, roundNumber: event.data.round as number };

    case 'swarm.complete':
      return { ...state, phase: 'complete' };

    case 'swarm.error':
      return { ...state, error: event.data.message as string };

    case 'agent.tool_call': {
      const tool: ActiveTool = {
        toolCallId: event.data.tool_call_id as string,
        toolName: event.data.tool_name as string,
        agentName: event.data.agent_name as string,
        status: 'running',
        input: event.data.input as string | undefined,
        startedAt: Date.now(),
      };
      return { ...state, activeTools: [...state.activeTools, tool] };
    }

    case 'agent.tool_result': {
      const callId = event.data.tool_call_id as string;
      const success = event.data.success as boolean;
      return {
        ...state,
        activeTools: state.activeTools.map((t) =>
          t.toolCallId === callId
            ? {
                ...t,
                status: success ? 'complete' as const : 'failed' as const,
                output: event.data.output as string | undefined,
                error: event.data.error as string | undefined,
                completedAt: Date.now(),
              }
            : t,
        ),
      };
    }

    case 'swarm.suspended':
      return {
        ...state,
        phase: 'suspended' as SwarmPhase,
        suspended: event.data as unknown as SwarmState['suspended'],
      };

    default:
      return state;
  }
}

export function isThinking(phase: SwarmState['phase']): boolean {
  return phase !== null && phase !== 'complete' && phase !== 'cancelled' && phase !== 'failed' && phase !== 'suspended';
}

export function shouldShowReportView(
  reportSwarmId: string | null,
  currentReport: string | null,
  phase: SwarmState['phase'],
): boolean {
  if (!reportSwarmId) return false;
  if (currentReport) return true;
  return phase === 'qa';
}

export function useSwarmState() {
  const [state, dispatch] = useReducer(swarmReducer, initialState);
  return { state, dispatch };
}

// ---------------------------------------------------------------------------
// Multi-swarm state management
// ---------------------------------------------------------------------------

const MAX_SWARMS = 10;

export interface MultiSwarmStore {
  swarms: Record<string, SwarmState>;
  activeSwarmIds: string[];
  completedSwarmIds: string[];
}

export type MultiSwarmAction =
  | { type: 'swarm.add'; swarmId: string }
  | { type: 'swarm.remove'; swarmId: string }
  | { type: 'swarm.event'; swarmId: string; event: SwarmEvent };

export const initialMultiSwarmState: MultiSwarmStore = {
  swarms: {},
  activeSwarmIds: [],
  completedSwarmIds: [],
};

export function multiSwarmReducer(
  state: MultiSwarmStore,
  action: MultiSwarmAction,
): MultiSwarmStore {
  switch (action.type) {
    case 'swarm.add': {
      let next = {
        ...state,
        swarms: { ...state.swarms, [action.swarmId]: initialState },
        activeSwarmIds: [...state.activeSwarmIds, action.swarmId],
      };
      // Hard cap: evict oldest completed if over limit
      const total = next.activeSwarmIds.length + next.completedSwarmIds.length;
      if (total > MAX_SWARMS && next.completedSwarmIds.length > 0) {
        const evictId = next.completedSwarmIds[0];
        const { [evictId]: _, ...rest } = next.swarms;
        next = {
          ...next,
          swarms: rest,
          completedSwarmIds: next.completedSwarmIds.slice(1),
        };
      }
      return next;
    }

    case 'swarm.remove': {
      const { [action.swarmId]: _, ...rest } = state.swarms;
      return {
        swarms: rest,
        activeSwarmIds: state.activeSwarmIds.filter((id) => id !== action.swarmId),
        completedSwarmIds: state.completedSwarmIds.filter((id) => id !== action.swarmId),
      };
    }

    case 'swarm.event': {
      const current = state.swarms[action.swarmId] ?? initialState;
      const updated = swarmReducer(current, action.event);

      let { activeSwarmIds, completedSwarmIds } = state;

      // Auto-transition: active → completed when phase is complete/cancelled/failed
      if (
        (updated.phase === 'complete' || updated.phase === 'cancelled' || updated.phase === 'failed') &&
        activeSwarmIds.includes(action.swarmId)
      ) {
        activeSwarmIds = activeSwarmIds.filter((id) => id !== action.swarmId);
        completedSwarmIds = [...completedSwarmIds, action.swarmId];
      }

      return {
        swarms: { ...state.swarms, [action.swarmId]: updated },
        activeSwarmIds,
        completedSwarmIds,
      };
    }

    default:
      return state;
  }
}
