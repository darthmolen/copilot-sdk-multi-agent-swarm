import { describe, it, expect } from 'vitest';
import { chatReducer, initialChatStore } from '../hooks/useChatState';
import type { ChatMessage } from '../types/swarm';

describe('chatReducer', () => {
  it('chat.delta creates streaming message for new swarm', () => {
    const state = chatReducer(initialChatStore, {
      type: 'chat.delta',
      swarmId: 's1',
      delta: 'Hello',
      messageId: 'msg-1',
    });
    expect(state.chats['s1'].streamingMessage).toEqual({ id: 'msg-1', content: 'Hello' });
  });

  it('chat.delta appends to existing streaming message', () => {
    const withStreaming = chatReducer(initialChatStore, {
      type: 'chat.delta', swarmId: 's1', delta: 'Hello ', messageId: 'msg-1',
    });
    const state = chatReducer(withStreaming, {
      type: 'chat.delta', swarmId: 's1', delta: 'World', messageId: 'msg-1',
    });
    expect(state.chats['s1'].streamingMessage?.content).toBe('Hello World');
  });

  it('chat.message finalizes to messages and clears streaming', () => {
    const withStreaming = chatReducer(initialChatStore, {
      type: 'chat.delta', swarmId: 's1', delta: 'partial', messageId: 'msg-1',
    });
    const state = chatReducer(withStreaming, {
      type: 'chat.message', swarmId: 's1', content: 'Full response', messageId: 'msg-1',
    });
    expect(state.chats['s1'].streamingMessage).toBeNull();
    expect(state.chats['s1'].messages).toHaveLength(1);
    expect(state.chats['s1'].messages[0]).toEqual({
      id: 'msg-1', role: 'assistant', content: 'Full response',
    });
  });

  it('chat.user_send appends user message', () => {
    const msg: ChatMessage = { id: 'u1', role: 'user', content: 'Make it shorter' };
    const state = chatReducer(initialChatStore, {
      type: 'chat.user_send', swarmId: 's1', message: msg,
    });
    expect(state.chats['s1'].messages).toHaveLength(1);
    expect(state.chats['s1'].messages[0].role).toBe('user');
    expect(state.chats['s1'].messages[0].content).toBe('Make it shorter');
  });

  it('chat.select_swarm sets activeSwarmId', () => {
    const state = chatReducer(initialChatStore, {
      type: 'chat.select_swarm', swarmId: 's2',
    });
    expect(state.activeSwarmId).toBe('s2');
  });

  it('chat.clear removes chat history for swarm', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.user_send', swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'Hi' },
    });
    state = chatReducer(state, { type: 'chat.clear', swarmId: 's1' });
    expect(state.chats['s1'].messages).toHaveLength(0);
    expect(state.chats['s1'].streamingMessage).toBeNull();
  });

  it('chats are isolated per swarm_id', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.user_send', swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'For swarm 1' },
    });
    state = chatReducer(state, {
      type: 'chat.user_send', swarmId: 's2',
      message: { id: 'u2', role: 'user', content: 'For swarm 2' },
    });
    expect(state.chats['s1'].messages).toHaveLength(1);
    expect(state.chats['s1'].messages[0].content).toBe('For swarm 1');
    expect(state.chats['s2'].messages).toHaveLength(1);
    expect(state.chats['s2'].messages[0].content).toBe('For swarm 2');
  });

  it('chat.tool_start adds tool to activeTools', () => {
    const state = chatReducer(initialChatStore, {
      type: 'chat.tool_start', swarmId: 's1',
      toolName: 'bash', toolCallId: 'tc-1',
    });
    expect(state.chats['s1'].activeTools).toHaveLength(1);
    expect(state.chats['s1'].activeTools[0]).toEqual({
      toolCallId: 'tc-1', toolName: 'bash', status: 'running',
    });
  });

  it('chat.tool_result updates tool status', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start', swarmId: 's1',
      toolName: 'bash', toolCallId: 'tc-1',
    });
    state = chatReducer(state, {
      type: 'chat.tool_result', swarmId: 's1',
      toolCallId: 'tc-1', success: true,
    });
    expect(state.chats['s1'].activeTools[0].status).toBe('complete');
  });
});
