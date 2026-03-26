import type { ChatMessage, ChatState, ChatStore } from '../types/swarm';

const emptyChatState: ChatState = {
  messages: [],
  streamingMessage: null,
  activeTools: [],
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
  | { type: 'chat.tool_start'; swarmId: string; toolName: string; toolCallId: string }
  | { type: 'chat.tool_result'; swarmId: string; toolCallId: string; success: boolean };

function getChatState(store: ChatStore, swarmId: string): ChatState {
  return store.chats[swarmId] ?? emptyChatState;
}

function setChatState(store: ChatStore, swarmId: string, chat: ChatState): ChatStore {
  return { ...store, chats: { ...store.chats, [swarmId]: chat } };
}

export function chatReducer(state: ChatStore, action: ChatAction): ChatStore {
  switch (action.type) {
    case 'chat.delta': {
      const chat = getChatState(state, action.swarmId);
      const streaming = chat.streamingMessage;
      return setChatState(state, action.swarmId, {
        ...chat,
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
      return setChatState(state, action.swarmId, {
        ...chat,
        messages: [...chat.messages, msg],
        streamingMessage: null,
      });
    }

    case 'chat.user_send': {
      const chat = getChatState(state, action.swarmId);
      return setChatState(state, action.swarmId, {
        ...chat,
        messages: [...chat.messages, action.message],
      });
    }

    case 'chat.select_swarm':
      return { ...state, activeSwarmId: action.swarmId };

    case 'chat.clear': {
      return setChatState(state, action.swarmId, { ...emptyChatState });
    }

    case 'chat.tool_start': {
      const chat = getChatState(state, action.swarmId);
      return setChatState(state, action.swarmId, {
        ...chat,
        activeTools: [
          ...chat.activeTools,
          { toolCallId: action.toolCallId, toolName: action.toolName, status: 'running' },
        ],
      });
    }

    case 'chat.tool_result': {
      const chat = getChatState(state, action.swarmId);
      return setChatState(state, action.swarmId, {
        ...chat,
        activeTools: chat.activeTools.map((t) =>
          t.toolCallId === action.toolCallId
            ? { ...t, status: action.success ? 'complete' as const : 'failed' as const }
            : t,
        ),
      });
    }

    default:
      return state;
  }
}
