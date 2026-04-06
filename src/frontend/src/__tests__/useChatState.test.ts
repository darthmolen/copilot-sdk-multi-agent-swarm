import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { chatReducer, initialChatStore } from '../hooks/useChatState';
import type { ChatMessage, ChatEntry, ChatState } from '../types/swarm';

// Helper: get ChatState for a swarm from the store
function getChat(store: ReturnType<typeof chatReducer>, swarmId: string): ChatState {
  return store.chats[swarmId]!;
}

// Helper: get entries of a specific type
function getEntries<T extends ChatEntry['type']>(
  entries: ChatEntry[],
  type: T,
): Extract<ChatEntry, { type: T }>[] {
  return entries.filter((e): e is Extract<ChatEntry, { type: T }> => e.type === type);
}

describe('useChatState – ChatEntry timeline', () => {
  let dateNowSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    dateNowSpy = vi.spyOn(Date, 'now').mockReturnValue(1000);
  });

  afterEach(() => {
    dateNowSpy.mockRestore();
  });

  // -----------------------------------------------------------------------
  // 1. tool_start creates tool_group when last entry is a message
  // -----------------------------------------------------------------------
  it('tool_start creates a new tool_group entry when last entry is a message', () => {
    // First add a message so the last entry is a message
    let state = chatReducer(initialChatStore, {
      type: 'chat.user_send',
      swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'Hello' },
    });

    state = chatReducer(state, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
      input: 'ls -la',
    });

    const chat = getChat(state, 's1');
    expect(chat.entries).toHaveLength(2); // message + tool_group

    const lastEntry = chat.entries[1];
    expect(lastEntry.type).toBe('tool_group');
    if (lastEntry.type === 'tool_group') {
      expect(lastEntry.tools).toHaveLength(1);
      expect(lastEntry.tools[0]).toMatchObject({
        toolCallId: 'tc-1',
        toolName: 'bash',
        status: 'running',
        input: 'ls -la',
        startedAt: 1000,
      });
    }
  });

  // -----------------------------------------------------------------------
  // 2. tool_start appends to existing tool_group (last entry already tool_group)
  // -----------------------------------------------------------------------
  it('tool_start appends to existing tool_group when last entry is already a tool_group', () => {
    // Start from empty (no messages) — first tool_start creates a group
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    dateNowSpy.mockReturnValue(2000);

    state = chatReducer(state, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'read_file',
      toolCallId: 'tc-2',
      input: '/path/to/file',
    });

    const chat = getChat(state, 's1');
    // Should still be a single tool_group entry with 2 tools
    expect(chat.entries).toHaveLength(1);
    expect(chat.entries[0].type).toBe('tool_group');
    if (chat.entries[0].type === 'tool_group') {
      expect(chat.entries[0].tools).toHaveLength(2);
      expect(chat.entries[0].tools[0].toolCallId).toBe('tc-1');
      expect(chat.entries[0].tools[0].startedAt).toBe(1000);
      expect(chat.entries[0].tools[1].toolCallId).toBe('tc-2');
      expect(chat.entries[0].tools[1].toolName).toBe('read_file');
      expect(chat.entries[0].tools[1].input).toBe('/path/to/file');
      expect(chat.entries[0].tools[1].startedAt).toBe(2000);
    }
  });

  // -----------------------------------------------------------------------
  // 3. chat.message after tool_group → next tool_start creates NEW group
  // -----------------------------------------------------------------------
  it('tool_start after a chat.message creates a new tool_group (not appending to old one)', () => {
    // Create a tool group
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    // Add a message (closes the group conceptually)
    state = chatReducer(state, {
      type: 'chat.message',
      swarmId: 's1',
      content: 'Here are the results',
      messageId: 'msg-1',
    });

    // Now another tool_start should create a NEW tool_group
    state = chatReducer(state, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'write_file',
      toolCallId: 'tc-2',
    });

    const chat = getChat(state, 's1');
    expect(chat.entries).toHaveLength(3); // tool_group, message, tool_group
    expect(chat.entries[0].type).toBe('tool_group');
    expect(chat.entries[1].type).toBe('message');
    expect(chat.entries[2].type).toBe('tool_group');

    if (chat.entries[2].type === 'tool_group') {
      expect(chat.entries[2].tools).toHaveLength(1);
      expect(chat.entries[2].tools[0].toolCallId).toBe('tc-2');
    }
  });

  // -----------------------------------------------------------------------
  // 4. tool_result updates tool status, output, error in its group
  // -----------------------------------------------------------------------
  it('tool_result updates the tool status, output, and completedAt in its group', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    dateNowSpy.mockReturnValue(5000);

    state = chatReducer(state, {
      type: 'chat.tool_result',
      swarmId: 's1',
      toolCallId: 'tc-1',
      success: true,
      output: 'file1.txt\nfile2.txt',
    });

    const chat = getChat(state, 's1');
    const group = chat.entries[0];
    expect(group.type).toBe('tool_group');
    if (group.type === 'tool_group') {
      expect(group.tools[0].status).toBe('complete');
      expect(group.tools[0].output).toBe('file1.txt\nfile2.txt');
      expect(group.tools[0].completedAt).toBe(5000);
      expect(group.tools[0].error).toBeUndefined();
    }
  });

  it('tool_result sets failed status and error message on failure', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    dateNowSpy.mockReturnValue(5000);

    state = chatReducer(state, {
      type: 'chat.tool_result',
      swarmId: 's1',
      toolCallId: 'tc-1',
      success: false,
      error: 'Command not found',
    });

    const chat = getChat(state, 's1');
    const group = chat.entries[0];
    if (group.type === 'tool_group') {
      expect(group.tools[0].status).toBe('failed');
      expect(group.tools[0].error).toBe('Command not found');
      expect(group.tools[0].completedAt).toBe(5000);
    }
  });

  // -----------------------------------------------------------------------
  // 5. chat.message clears streamingMessage with matching messageId (dedup fix)
  // -----------------------------------------------------------------------
  it('chat.message clears streamingMessage when messageId matches', () => {
    // Stream some deltas
    let state = chatReducer(initialChatStore, {
      type: 'chat.delta',
      swarmId: 's1',
      delta: 'partial...',
      messageId: 'msg-1',
    });

    expect(getChat(state, 's1').streamingMessage).not.toBeNull();

    // Finalize with same messageId
    state = chatReducer(state, {
      type: 'chat.message',
      swarmId: 's1',
      content: 'Full response',
      messageId: 'msg-1',
    });

    const chat = getChat(state, 's1');
    expect(chat.streamingMessage).toBeNull();

    // Should have a message entry
    const messageEntries = getEntries(chat.entries, 'message');
    expect(messageEntries).toHaveLength(1);
    expect(messageEntries[0].message.content).toBe('Full response');
  });

  it('chat.message clears streamingMessage even when messageId differs', () => {
    // Stream deltas with msg-1
    let state = chatReducer(initialChatStore, {
      type: 'chat.delta',
      swarmId: 's1',
      delta: 'partial...',
      messageId: 'msg-1',
    });

    // Finalize with msg-2 (different ID — still should clear streaming)
    state = chatReducer(state, {
      type: 'chat.message',
      swarmId: 's1',
      content: 'Full response',
      messageId: 'msg-2',
    });

    expect(getChat(state, 's1').streamingMessage).toBeNull();
  });

  // -----------------------------------------------------------------------
  // 6. chat.delta updates streamingMessage
  // -----------------------------------------------------------------------
  it('chat.delta creates and updates streamingMessage', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.delta',
      swarmId: 's1',
      delta: 'Hello ',
      messageId: 'msg-1',
    });

    expect(getChat(state, 's1').streamingMessage).toEqual({
      id: 'msg-1',
      content: 'Hello ',
    });

    state = chatReducer(state, {
      type: 'chat.delta',
      swarmId: 's1',
      delta: 'World',
      messageId: 'msg-1',
    });

    expect(getChat(state, 's1').streamingMessage).toEqual({
      id: 'msg-1',
      content: 'Hello World',
    });
  });

  // -----------------------------------------------------------------------
  // 7. chat.user_send pushes message entry
  // -----------------------------------------------------------------------
  it('chat.user_send pushes a message entry and sets sessionStarting', () => {
    const msg: ChatMessage = { id: 'u1', role: 'user', content: 'Build me a dashboard' };
    const state = chatReducer(initialChatStore, {
      type: 'chat.user_send',
      swarmId: 's1',
      message: msg,
    });

    const chat = getChat(state, 's1');
    expect(chat.entries).toHaveLength(1);
    expect(chat.entries[0].type).toBe('message');
    if (chat.entries[0].type === 'message') {
      expect(chat.entries[0].message).toEqual(msg);
    }
    expect(chat.sessionStarting).toBe(true);
  });

  // -----------------------------------------------------------------------
  // 8. tool_start includes input field
  // -----------------------------------------------------------------------
  it('tool_start captures the input field in the tool entry', () => {
    const state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'web_search',
      toolCallId: 'tc-1',
      input: 'React 19 release date',
    });

    const chat = getChat(state, 's1');
    const group = chat.entries[0];
    if (group.type === 'tool_group') {
      expect(group.tools[0].input).toBe('React 19 release date');
    }
  });

  it('tool_start works without input field (optional)', () => {
    const state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    const chat = getChat(state, 's1');
    const group = chat.entries[0];
    if (group.type === 'tool_group') {
      expect(group.tools[0].input).toBeUndefined();
    }
  });

  // -----------------------------------------------------------------------
  // 9. tool_result includes output and error fields
  // -----------------------------------------------------------------------
  it('tool_result stores output on success', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    state = chatReducer(state, {
      type: 'chat.tool_result',
      swarmId: 's1',
      toolCallId: 'tc-1',
      success: true,
      output: 'Success output here',
    });

    const chat = getChat(state, 's1');
    const group = chat.entries[0];
    if (group.type === 'tool_group') {
      expect(group.tools[0].output).toBe('Success output here');
      expect(group.tools[0].error).toBeUndefined();
    }
  });

  it('tool_result stores error on failure', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    state = chatReducer(state, {
      type: 'chat.tool_result',
      swarmId: 's1',
      toolCallId: 'tc-1',
      success: false,
      error: 'Permission denied',
    });

    const chat = getChat(state, 's1');
    const group = chat.entries[0];
    if (group.type === 'tool_group') {
      expect(group.tools[0].error).toBe('Permission denied');
      expect(group.tools[0].output).toBeUndefined();
    }
  });

  // -----------------------------------------------------------------------
  // 10. tool_result finds tool across multiple groups
  // -----------------------------------------------------------------------
  it('tool_result finds the correct tool across multiple tool_groups', () => {
    // Create first group
    let state = chatReducer(initialChatStore, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    // Insert a message to close the first group
    state = chatReducer(state, {
      type: 'chat.message',
      swarmId: 's1',
      content: 'Intermediate',
      messageId: 'msg-1',
    });

    // Create second group
    state = chatReducer(state, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'write_file',
      toolCallId: 'tc-2',
    });

    dateNowSpy.mockReturnValue(9000);

    // Complete tool from the FIRST group
    state = chatReducer(state, {
      type: 'chat.tool_result',
      swarmId: 's1',
      toolCallId: 'tc-1',
      success: true,
      output: 'done',
    });

    const chat = getChat(state, 's1');
    // First group's tool should be updated
    const firstGroup = chat.entries[0];
    if (firstGroup.type === 'tool_group') {
      expect(firstGroup.tools[0].status).toBe('complete');
      expect(firstGroup.tools[0].output).toBe('done');
      expect(firstGroup.tools[0].completedAt).toBe(9000);
    }

    // Second group's tool should remain running
    const secondGroup = chat.entries[2];
    if (secondGroup.type === 'tool_group') {
      expect(secondGroup.tools[0].status).toBe('running');
    }
  });

  // -----------------------------------------------------------------------
  // 11. chat.clear resets entries and streamingMessage
  // -----------------------------------------------------------------------
  it('chat.clear resets entries and streamingMessage', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.user_send',
      swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'Hi' },
    });
    state = chatReducer(state, {
      type: 'chat.tool_start',
      swarmId: 's1',
      toolName: 'bash',
      toolCallId: 'tc-1',
    });

    state = chatReducer(state, { type: 'chat.clear', swarmId: 's1' });

    const chat = getChat(state, 's1');
    expect(chat.entries).toHaveLength(0);
    expect(chat.streamingMessage).toBeNull();
    expect(chat.sessionStarting).toBe(false);
  });

  // -----------------------------------------------------------------------
  // 12. chat.select_swarm sets activeSwarmId (unchanged behavior)
  // -----------------------------------------------------------------------
  it('chat.select_swarm sets activeSwarmId', () => {
    const state = chatReducer(initialChatStore, {
      type: 'chat.select_swarm',
      swarmId: 's2',
    });
    expect(state.activeSwarmId).toBe('s2');
  });

  // -----------------------------------------------------------------------
  // 13. Chats are isolated per swarm_id
  // -----------------------------------------------------------------------
  it('chats are isolated per swarm_id', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.user_send',
      swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'For swarm 1' },
    });
    state = chatReducer(state, {
      type: 'chat.user_send',
      swarmId: 's2',
      message: { id: 'u2', role: 'user', content: 'For swarm 2' },
    });

    const s1 = getChat(state, 's1');
    const s2 = getChat(state, 's2');
    expect(s1.entries).toHaveLength(1);
    expect(s2.entries).toHaveLength(1);

    if (s1.entries[0].type === 'message' && s2.entries[0].type === 'message') {
      expect(s1.entries[0].message.content).toBe('For swarm 1');
      expect(s2.entries[0].message.content).toBe('For swarm 2');
    }
  });

  // -----------------------------------------------------------------------
  // 14. chat.delta clears sessionStarting
  // -----------------------------------------------------------------------
  it('chat.delta clears sessionStarting', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.user_send',
      swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'Hi' },
    });
    state = chatReducer(state, {
      type: 'chat.delta',
      swarmId: 's1',
      delta: 'Hello',
      messageId: 'msg-1',
    });
    expect(getChat(state, 's1').sessionStarting).toBe(false);
  });

  // -----------------------------------------------------------------------
  // 15. chat.message clears sessionStarting
  // -----------------------------------------------------------------------
  it('chat.message clears sessionStarting', () => {
    let state = chatReducer(initialChatStore, {
      type: 'chat.user_send',
      swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'Hi' },
    });
    state = chatReducer(state, {
      type: 'chat.message',
      swarmId: 's1',
      content: 'Response',
      messageId: 'msg-1',
    });
    expect(getChat(state, 's1').sessionStarting).toBe(false);
  });

  // -----------------------------------------------------------------------
  // 16. Initial empty state shape
  // -----------------------------------------------------------------------
  it('initial ChatState has entries array, null streamingMessage, false sessionStarting', () => {
    const state = chatReducer(initialChatStore, {
      type: 'chat.user_send',
      swarmId: 's1',
      message: { id: 'u1', role: 'user', content: 'Hi' },
    });
    // Then clear to get back to empty
    const cleared = chatReducer(state, { type: 'chat.clear', swarmId: 's1' });
    const chat = getChat(cleared, 's1');
    expect(chat.entries).toEqual([]);
    expect(chat.streamingMessage).toBeNull();
    expect(chat.sessionStarting).toBe(false);
  });
});
