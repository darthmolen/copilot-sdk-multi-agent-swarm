import { useEffect, useRef } from 'react';
import type { InboxMessage } from '../types/swarm';

interface InboxFeedProps {
  messages: InboxMessage[];
}

export function InboxFeed({ messages }: InboxFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length]);

  return (
    <div className="inbox-feed">
      <h2>Inbox Feed</h2>
      <div className="message-list">
        {messages.map((msg, idx) => (
          <div key={idx} className="inbox-message">
            <div className="message-header">
              <span className="sender">{msg.sender}</span>
              <span className="arrow"> &rarr; </span>
              <span className="recipient">{msg.recipient}</span>
              <span className="timestamp">
                {new Date(msg.timestamp).toLocaleTimeString()}
              </span>
            </div>
            <p className="message-content">{msg.content}</p>
          </div>
        ))}
        {messages.length === 0 && (
          <p className="empty-text">No messages yet</p>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
