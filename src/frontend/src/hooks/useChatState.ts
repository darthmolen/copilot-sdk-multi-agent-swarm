import type { ChatMessage, ChatState, ChatStore, ChatEntry, ActiveTool } from '../types/swarm';

const emptyChatState: ChatState = {
  entries: [],
  streamingMessage: null,
  sessionStarting: false,
};

export const initialChatStore: ChatStore = {
  chats: {},
  activeSwarmId: null,
};

export type ChatAction =
  | { type: 'chat.delta'; swarmId: string; delta: string; messageId: string }
  | { type: 'chat.message'; swarmId: string; content: string; messageId: string }
  | { type: 'chat.user_send'; swarmId: string; message: ChatMessage }
  | { type: 'chat.select_swarm'; swarmId: string }
  | { type: 'chat.clear'; swarmId: string }
  | { type: 'chat.tool_start'; swarmId: string; toolName: string; toolCallId: string; input?: string }
  | { type: 'chat.tool_result'; swarmId: string; toolCallId: string; success: boolean; output?: string; error?: string };

function getChatState(store: ChatStore, swarmId: string): ChatState {
  return store.chats[swarmId] ?? emptyChatState;
}

function setChatState(store: ChatStore, swarmId: string, chat: ChatState): ChatStore {
  return { ...store, chats: { ...store.chats, [swarmId]: chat } };
}

/**
 * Update a tool inside any tool_group entry that contains the given toolCallId.
 * Returns a new entries array with the tool updated immutably.
 */
function updateToolInEntries(
  entries: ChatEntry[],
  toolCallId: string,
  updater: (tool: ActiveTool) => ActiveTool,
): ChatEntry[] {
  return entries.map((entry) => {
    if (entry.type !== 'tool_group') return entry;
    const hasTarget = entry.tools.some((t) => t.toolCallId === toolCallId);
    if (!hasTarget) return entry;
    return {
      ...entry,
      tools: entry.tools.map((t) =>
        t.toolCallId === toolCallId ? updater(t) : t,
      ),
    };
  });
}

export function chatReducer(state: ChatStore, action: ChatAction): ChatStore {
  switch (action.type) {
    case 'chat.delta': {
      const chat = getChatState(state, action.swarmId);
      const streaming = chat.streamingMessage;
      return setChatState(state, action.swarmId, {
        ...chat,
        sessionStarting: false,
        streamingMessage: {
          id: streaming?.id ?? action.messageId,
          content: (streaming?.content ?? '') + action.delta,
        },
      });
    }

    case 'chat.message': {
      const chat = getChatState(state, action.swarmId);
      const msg: ChatMessage = {
        id: action.messageId,
        role: 'assistant',
        content: action.content,
      };
      const messageEntry: ChatEntry = { type: 'message', message: msg };
      return setChatState(state, action.swarmId, {
        ...chat,
        sessionStarting: false,
        entries: [...chat.entries, messageEntry],
        streamingMessage: null,
      });
    }

    case 'chat.user_send': {
      const chat = getChatState(state, action.swarmId);
      const messageEntry: ChatEntry = { type: 'message', message: action.message };
      return setChatState(state, action.swarmId, {
        ...chat,
        sessionStarting: true,
        entries: [...chat.entries, messageEntry],
      });
    }

    case 'chat.select_swarm':
      return { ...state, activeSwarmId: action.swarmId };

    case 'chat.clear': {
      return setChatState(state, action.swarmId, { ...emptyChatState });
    }

    case 'chat.tool_start': {
      const chat = getChatState(state, action.swarmId);
      const newTool: ActiveTool = {
        toolCallId: action.toolCallId,
        toolName: action.toolName,
        status: 'running',
        input: action.input,
        startedAt: Date.now(),
      };

      const lastEntry = chat.entries[chat.entries.length - 1];

      // If last entry is already a tool_group, append to it
      if (lastEntry && lastEntry.type === 'tool_group') {
        const updatedEntries = [...chat.entries];
        updatedEntries[updatedEntries.length - 1] = {
          ...lastEntry,
          tools: [...lastEntry.tools, newTool],
        };
        return setChatState(state, action.swarmId, {
          ...chat,
          entries: updatedEntries,
        });
      }

      // Otherwise create a new tool_group entry
      return setChatState(state, action.swarmId, {
        ...chat,
        entries: [...chat.entries, { type: 'tool_group', tools: [newTool] }],
      });
    }

    case 'chat.tool_result': {
      const chat = getChatState(state, action.swarmId);
      const updatedEntries = updateToolInEntries(
        chat.entries,
        action.toolCallId,
        (tool) => ({
          ...tool,
          status: action.success ? 'complete' as const : 'failed' as const,
          output: action.output,
          error: action.error,
          completedAt: Date.now(),
        }),
      );
      return setChatState(state, action.swarmId, {
        ...chat,
        entries: updatedEntries,
      });
    }

    default:
      return state;
  }
}

