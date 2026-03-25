export type TaskStatus = 'blocked' | 'pending' | 'in_progress' | 'completed' | 'failed' | 'timeout';
export type AgentStatus = 'idle' | 'thinking' | 'working' | 'ready' | 'failed';
export type SwarmPhase = 'starting' | 'planning' | 'spawning' | 'executing' | 'synthesizing' | 'complete' | 'cancelled';

export interface Task {
  id: string;
  subject: string;
  description: string;
  worker_role: string;
  worker_name: string;
  status: TaskStatus;
  blocked_by: string[];
  result: string;
  swarm_id?: string;
}

export interface AgentInfo {
  name: string;
  role: string;
  display_name: string;
  status: AgentStatus;
  tasks_completed: number;
  swarm_id?: string;
}

export interface InboxMessage {
  sender: string;
  recipient: string;
  content: string;
  timestamp: string;
  swarm_id?: string;
}

export interface SwarmState {
  phase: SwarmPhase | null;
  tasks: Task[];
  agents: AgentInfo[];
  messages: InboxMessage[];
  leaderPlan: string;
  leaderReport: string;
  agentOutputs: Record<string, string>;
  roundNumber: number;
  error: string | null;
}

export interface SwarmEvent {
  type: string;
  data: Record<string, unknown>;
}
