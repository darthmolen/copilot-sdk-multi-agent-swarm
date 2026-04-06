export type TaskStatus = 'blocked' | 'pending' | 'in_progress' | 'completed' | 'failed' | 'timeout';
export type AgentStatus = 'idle' | 'thinking' | 'working' | 'ready' | 'failed';
export type SwarmPhase = 'starting' | 'planning' | 'spawning' | 'executing' | 'synthesizing' | 'qa' | 'complete' | 'cancelled' | 'failed' | 'suspended';

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

export interface ActiveTool {
  toolCallId: string;
  toolName: string;
  agentName?: string;
  status: 'running' | 'complete' | 'failed';
  input?: string;
  output?: string;
  error?: string;
  startedAt?: number;
  completedAt?: number;
}

export interface SwarmState {
  phase: SwarmPhase | null;
  tasks: Task[];
  agents: AgentInfo[];
  messages: InboxMessage[];
  leaderPlan: string;
  leaderReport: string;
  agentOutputs: Record<string, string>;
  activeTools: ActiveTool[];
  roundNumber: number;
  error: string | null;
  suspended?: { remaining_tasks: number; max_rounds: number; reason: string };
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export type ChatEntry =
  | { type: 'message'; message: ChatMessage }
  | { type: 'tool_group'; tools: ActiveTool[] }
  | { type: 'streaming'; content: string; id: string };

export interface ChatState {
  entries: ChatEntry[];
  streamingMessage: { id: string; content: string } | null;
  sessionStarting: boolean;
}

export interface ChatStore {
  chats: Record<string, ChatState>;
  activeSwarmId: string | null;
}

export interface FileInfo {
  name: string;
  path: string;
  size: number;
}

export interface SavedReport {
  swarmId: string;
  title: string;
  timestamp: number;
  report: string;
  phase: SwarmPhase;
}

export interface SwarmEvent {
  type: string;
  data: Record<string, unknown>;
}
