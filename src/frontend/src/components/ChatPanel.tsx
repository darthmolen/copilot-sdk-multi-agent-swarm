import { useRef } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { useAutoScroll } from '../hooks/useAutoScroll';
import { StreamingMarkdown } from './StreamingMarkdown';
import { ChatInput } from './ChatInput';
import type { ChatMessage } from '../types/swarm';

interface ChatPanelProps {
  messages: ChatMessage[];
  streamingMessage: { id: string; content: string } | null;
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

export function ChatPanel({
  messages,
  streamingMessage,
  onSend,
  chatEnabled,
}: ChatPanelProps) {
  const messagesRef = useRef<HTMLDivElement>(null);
  useAutoScroll(messagesRef, [messages.length, streamingMessage?.content]);

  return (
    <div className="chat-panel-v2">
      <div className="chat-panel-v2__header">
        <h3>Refinement Chat</h3>
      </div>
      <div ref={messagesRef} className="chat-panel-v2__messages">
        {messages.length === 0 && !streamingMessage && (
          <p className="empty-text">
            {chatEnabled
              ? 'Ask questions or request changes to refine the report.'
              : 'Chat will be available once synthesis completes.'}
          </p>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}
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
      <ChatInput onSend={onSend} disabled={!chatEnabled || !!streamingMessage} />
    </div>
  );
}
