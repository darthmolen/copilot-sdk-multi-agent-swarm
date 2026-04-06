import { useRef } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { useAutoScroll } from '../hooks/useAutoScroll';
import { useMermaid } from '../hooks/useMermaid';
import { StreamingMarkdown } from './StreamingMarkdown';
import { ChatInput } from './ChatInput';
import { ToolGroup } from './ToolGroup';
import type { ChatMessage, ChatEntry } from '../types/swarm';

interface ChatPanelProps {
  entries: ChatEntry[];
  streamingMessage: { id: string; content: string } | null;
  sessionStarting: boolean;
  onSend: (message: string) => void;
  chatEnabled: boolean;
}

function renderMarkdown(md: string): string {
  return DOMPurify.sanitize(marked.parse(md) as string);
}

function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user';
  return (
    <div className={`chat-bubble chat-bubble--${message.role}`}>
      <div className="chat-bubble__header">
        {isUser ? 'You' : 'Synthesis Agent'}
      </div>
      <div
        className="chat-bubble__content"
        dangerouslySetInnerHTML={
          isUser
            ? undefined
            : { __html: renderMarkdown(message.content) }
        }
      >
        {isUser ? message.content : undefined}
      </div>
    </div>
  );
}

/** Extract only message entries for computing "waiting for response" state. */
function getLastMessageRole(entries: ChatEntry[]): string | null {
  for (let i = entries.length - 1; i >= 0; i--) {
    const entry = entries[i];
    if (entry.type === 'message') return entry.message.role;
  }
  return null;
}

export function ChatPanel({
  entries,
  streamingMessage,
  sessionStarting,
  onSend,
  chatEnabled,
}: ChatPanelProps) {
  const messagesRef = useRef<HTMLDivElement>(null);
  useAutoScroll(messagesRef, [entries.length, streamingMessage?.content]);
  useMermaid(messagesRef, [entries.length, streamingMessage?.content]);

  const lastRole = getLastMessageRole(entries);
  const waitingForResponse = lastRole === 'user' && !streamingMessage && !sessionStarting;

  return (
    <div className="chat-panel-v2">
      <div className="chat-panel-v2__header">
        <h3>Refinement Chat</h3>
      </div>
      <div ref={messagesRef} className="chat-panel-v2__messages">
        {entries.length === 0 && !streamingMessage && (
          <p className="empty-text">
            {chatEnabled
              ? 'Ask questions or request changes to refine the report.'
              : 'Chat will be available once synthesis completes.'}
          </p>
        )}
        {entries.map((entry, i) => {
          if (entry.type === 'message') {
            return <MessageBubble key={entry.message.id} message={entry.message} />;
          }
          if (entry.type === 'tool_group') {
            return <ToolGroup key={`tg-${i}`} tools={entry.tools} />;
          }
          return null;
        })}
        {streamingMessage && (
          <div className="chat-bubble chat-bubble--assistant chat-bubble--streaming">
            <div className="chat-bubble__header">Synthesis Agent</div>
            <div className="chat-bubble__content">
              <StreamingMarkdown
                content={streamingMessage.content}
                isStreaming={true}
              />
            </div>
          </div>
        )}
      </div>
      {sessionStarting && (
        <div className="chat-thinking">
          <span className="thinking-icon">🧠</span>
          <span className="thinking-text">Starting session...</span>
        </div>
      )}
      {waitingForResponse && (
        <div className="chat-thinking">
          <span className="thinking-icon">🧠</span>
          <span className="thinking-text">Thinking...</span>
        </div>
      )}
      <ChatInput onSend={onSend} disabled={!chatEnabled} />
    </div>
  );
}
