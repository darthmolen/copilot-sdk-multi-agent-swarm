import { useRef, useMemo } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { useMermaid } from '../hooks/useMermaid';

interface ChatPanelProps {
  plan: string;
  report: string;
}

function renderMarkdown(source: string): string {
  const raw = marked.parse(source, { async: false }) as string;
  return DOMPurify.sanitize(raw);
}

export function ChatPanel({ plan, report }: ChatPanelProps) {
  const reportRef = useRef<HTMLDivElement>(null);
  const reportHtml = useMemo(() => (report ? renderMarkdown(report) : ''), [report]);

  useMermaid(reportRef, [reportHtml]);

  return (
    <div className="chat-panel">
      <h2>Leader Output</h2>
      {plan && (
        <section className="chat-section">
          <h3>Plan</h3>
          <pre className="chat-content">{plan}</pre>
        </section>
      )}
      {report && (
        <section className="chat-section">
          <h3>Synthesis Report</h3>
          <div
            ref={reportRef}
            className="chat-content chat-content--html"
            dangerouslySetInnerHTML={{ __html: reportHtml }}
          />
        </section>
      )}
      {!plan && !report && (
        <p className="empty-text">Waiting for leader output...</p>
      )}
    </div>
  );
}
