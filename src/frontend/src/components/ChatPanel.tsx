interface ChatPanelProps {
  plan: string;
  report: string;
}

export function ChatPanel({ plan, report }: ChatPanelProps) {
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
          <pre className="chat-content">{report}</pre>
        </section>
      )}
      {!plan && !report && (
        <p className="empty-text">Waiting for leader output...</p>
      )}
    </div>
  );
}
