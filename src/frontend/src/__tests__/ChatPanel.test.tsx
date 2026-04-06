import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChatPanel } from '../components/ChatPanel';
import type { ChatEntry } from '../types/swarm';

// Mock marked to return raw text (avoids markdown parsing complexity in tests)
vi.mock('marked', () => ({
  marked: {
    parse: (md: string) => md,
  },
}));

// Mock DOMPurify to passthrough
vi.mock('dompurify', () => ({
  default: {
    sanitize: (html: string) => html,
  },
}));

// Mock hooks that interact with DOM/mermaid
vi.mock('../hooks/useAutoScroll', () => ({
  useAutoScroll: vi.fn(),
}));
vi.mock('../hooks/useMermaid', () => ({
  useMermaid: vi.fn(),
}));

// Mock StreamingMarkdown to render content directly
vi.mock('../components/StreamingMarkdown', () => ({
  StreamingMarkdown: ({ content }: { content: string }) => (
    <div data-testid="streaming-markdown">{content}</div>
  ),
}));

// Mock ChatInput to render a simple placeholder
vi.mock('../components/ChatInput', () => ({
  ChatInput: ({ onSend, disabled }: { onSend: (msg: string) => void; disabled: boolean }) => (
    <div data-testid="chat-input" data-disabled={disabled}>
      <button onClick={() => onSend('test')}>Send</button>
    </div>
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ChatPanel', () => {
  // 1. renders message entries as MessageBubble
  it('renders message entries as MessageBubble', () => {
    const entries: ChatEntry[] = [
      { type: 'message', message: { id: '1', role: 'user', content: 'hi' } },
    ];
    render(
      <ChatPanel
        entries={entries}
        streamingMessage={null}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    expect(screen.getByText('hi')).toBeInTheDocument();
  });

  // 2. renders tool_group entries inline with ToolGroup component
  it('renders tool_group entries inline', () => {
    const entries: ChatEntry[] = [
      { type: 'message', message: { id: '1', role: 'assistant', content: 'Let me check' } },
      {
        type: 'tool_group',
        tools: [{ toolCallId: 'tc-1', toolName: 'bash', status: 'running' as const }],
      },
    ];
    render(
      <ChatPanel
        entries={entries}
        streamingMessage={null}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    expect(screen.getByText('Let me check')).toBeInTheDocument();
    expect(screen.getByText('bash')).toBeInTheDocument();
  });

  // 3. renders streaming message after all entries
  it('renders streaming message after entries', () => {
    const entries: ChatEntry[] = [
      { type: 'message', message: { id: '1', role: 'user', content: 'hello' } },
    ];
    render(
      <ChatPanel
        entries={entries}
        streamingMessage={{ id: 's1', content: 'thinking...' }}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    expect(screen.getByText('hello')).toBeInTheDocument();
    // StreamingMarkdown should render the streaming content
    expect(screen.getByTestId('streaming-markdown')).toBeInTheDocument();
    expect(screen.getByText('thinking...')).toBeInTheDocument();
  });

  // 4. does not render ToolCardList (old flat list removed)
  it('does not render old ToolCardList', () => {
    const entries: ChatEntry[] = [
      {
        type: 'tool_group',
        tools: [
          { toolCallId: 'tc-1', toolName: 'read_file', status: 'running' as const },
        ],
      },
    ];
    render(
      <ChatPanel
        entries={entries}
        streamingMessage={null}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    // ToolCardList renders a .tool-card-list container -- should NOT be present
    expect(document.querySelector('.tool-card-list')).toBeNull();
    // But the ToolGroup should render the tool name
    expect(screen.getByText('read_file')).toBeInTheDocument();
  });

  // 5. handles empty entries
  it('renders empty state with no entries', () => {
    render(
      <ChatPanel
        entries={[]}
        streamingMessage={null}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    // Should render without errors and show the empty message prompt
    expect(
      screen.getByText('Ask questions or request changes to refine the report.'),
    ).toBeInTheDocument();
  });

  // 6. renders interleaved messages and tool groups in order
  it('renders interleaved messages and tool groups in timeline order', () => {
    const entries: ChatEntry[] = [
      { type: 'message', message: { id: '1', role: 'user', content: 'First message' } },
      {
        type: 'tool_group',
        tools: [{ toolCallId: 'tc-1', toolName: 'bash', status: 'complete' as const }],
      },
      { type: 'message', message: { id: '2', role: 'assistant', content: 'Second message' } },
      {
        type: 'tool_group',
        tools: [{ toolCallId: 'tc-2', toolName: 'read_file', status: 'running' as const }],
      },
    ];
    render(
      <ChatPanel
        entries={entries}
        streamingMessage={null}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    expect(screen.getByText('First message')).toBeInTheDocument();
    expect(screen.getByText('bash')).toBeInTheDocument();
    expect(screen.getByText('Second message')).toBeInTheDocument();
    expect(screen.getByText('read_file')).toBeInTheDocument();
  });

  // 7. shows "Starting session..." when sessionStarting is true
  it('shows session starting indicator', () => {
    render(
      <ChatPanel
        entries={[]}
        streamingMessage={null}
        sessionStarting={true}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    expect(screen.getByText('Starting session...')).toBeInTheDocument();
  });

  // 8. shows "Thinking..." when last message is from user and no streaming
  it('shows thinking indicator when waiting for response', () => {
    const entries: ChatEntry[] = [
      { type: 'message', message: { id: '1', role: 'user', content: 'hello' } },
    ];
    render(
      <ChatPanel
        entries={entries}
        streamingMessage={null}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={true}
      />,
    );
    expect(screen.getByText('Thinking...')).toBeInTheDocument();
  });

  // 9. empty state when chat is disabled
  it('shows disabled message when chat is not enabled', () => {
    render(
      <ChatPanel
        entries={[]}
        streamingMessage={null}
        sessionStarting={false}
        onSend={vi.fn()}
        chatEnabled={false}
      />,
    );
    expect(
      screen.getByText('Chat will be available once synthesis completes.'),
    ).toBeInTheDocument();
  });
});
