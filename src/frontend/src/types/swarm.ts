export type TaskStatus = 'blocked' | 'pending' | 'in_progress' | 'completed' | 'failed' | 'timeout';
export type AgentStatus = 'idle' | 'thinking' | 'working' | 'ready' | 'failed';
export type SwarmPhase = 'planning' | 'spawning' | 'executing' | 'synthesizing' | 'complete';

export interface Task {
  id: string;
  subject: string;
  description: string;
  worker_role: string;
  worker_name: string;
  status: TaskStatus;
  blocked_by: string[];
  result: string;
}

export interface AgentInfo {
  name: string;
  role: string;
  display_name: string;
  status: AgentStatus;
  tasks_completed: number;
}

export interface InboxMessage {
  sender: string;
  recipient: string;
  content: string;
  timestamp: string;
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
