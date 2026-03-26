import { useReducer, useCallback, useState } from 'react';
import { multiSwarmReducer, initialMultiSwarmState, isThinking } from './hooks/useSwarmState';
import { chatReducer, initialChatStore, type ChatAction } from './hooks/useChatState';
import { useWebSocket } from './hooks/useWebSocket';
import { SwarmControls } from './components/SwarmControls';
import { TaskBoard } from './components/TaskBoard';
import { AgentRoster } from './components/AgentRoster';
import { ChatPanel } from './components/ChatPanel';
import { InboxFeed } from './components/InboxFeed';
import { ResizableLayout } from './components/ResizableLayout';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { SwarmEvent } from './types/swarm';
import './App.css';

const API_BASE = import.meta.env.VITE_API_URL ?? '';

export function getApiKey(): string {
  return sessionStorage.getItem('swarm_api_key') ?? '';
}

function renderMarkdown(md: string): string {
  return DOMPurify.sanitize(marked.parse(md) as string);
}

function AuthGate({ onAuth }: { onAuth: () => void }) {
  const [key, setKey] = useState('');
  const [error, setError] = useState('');

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!key.trim()) { setError('API key is required'); return; }
    sessionStorage.setItem('swarm_api_key', key.trim());
    onAuth();
  }

  return (
    <div className="auth-gate">
      <form className="auth-form" onSubmit={handleSubmit} autoComplete="off">
        <h2>Multi-Agent Swarm</h2>
        <p>Enter your API key to continue</p>
        <input
          type="password"
          placeholder="API Key"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          autoFocus
          autoComplete="off"
          className="auth-input"
        />
        <button type="submit" className="auth-button">Connect</button>
        {error && <p className="error-text">{error}</p>}
      </form>
    </div>
  );
}

/** Invisible component that owns a WS connection for one swarm. */
function SwarmConnection({
  swarmId,
  onEvent,
}: {
  swarmId: string;
  onEvent: (swarmId: string, event: SwarmEvent) => void;
}) {
  const handler = useCallback(
    (event: SwarmEvent) => onEvent(swarmId, event),
    [swarmId, onEvent],
  );
  useWebSocket(swarmId, handler);
  return null;
}

function App() {
  const [authed, setAuthed] = useState(() => !!sessionStorage.getItem('swarm_api_key'));

  if (!authed) {
    return <AuthGate onAuth={() => setAuthed(true)} />;
  }

  return <SwarmDashboard />;
}

function SwarmDashboard() {
  const [store, swarmDispatch] = useReducer(multiSwarmReducer, initialMultiSwarmState);
  const [chatStore, chatDispatch] = useReducer(chatReducer, initialChatStore);
  const [reportSwarmId, setReportSwarmId] = useState<string | null>(null);

  const handleSwarmEvent = useCallback(
    (swarmId: string, event: SwarmEvent) => {
      // Route chat events to chatReducer
      if (event.type === 'leader.chat_delta') {
        chatDispatch({
          type: 'chat.delta',
          swarmId,
          delta: (event.data.delta as string) ?? '',
          messageId: (event.data.message_id as string) ?? '',
        });
      } else if (event.type === 'leader.chat_message') {
        chatDispatch({
          type: 'chat.message',
          swarmId,
          content: (event.data.content as string) ?? '',
          messageId: (event.data.message_id as string) ?? '',
        });
      } else if (event.type === 'leader.chat_tool_start') {
        chatDispatch({
          type: 'chat.tool_start',
          swarmId,
          toolName: (event.data.tool_name as string) ?? '',
          toolCallId: (event.data.tool_call_id as string) ?? '',
        });
      } else if (event.type === 'leader.chat_tool_result') {
        chatDispatch({
          type: 'chat.tool_result',
          swarmId,
          toolCallId: (event.data.tool_call_id as string) ?? '',
          success: event.data.success as boolean,
        });
      } else {
        // All other events go to swarm reducer
        swarmDispatch({ type: 'swarm.event', swarmId, event });
      }
    },
    [],
  );

  function handleStartSwarm(swarmId: string) {
    swarmDispatch({ type: 'swarm.add', swarmId });
  }

  async function handleSendChat(swarmId: string, message: string) {
    // Optimistically add user message
    chatDispatch({
      type: 'chat.user_send',
      swarmId,
      message: { id: `user-${Date.now()}`, role: 'user', content: message },
    });

    const apiKey = getApiKey();
    await fetch(`${API_BASE}/api/swarm/${swarmId}/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(apiKey ? { 'X-API-Key': apiKey } : {}),
      },
      body: JSON.stringify({ message }),
    });
  }

  // Aggregate across all swarms
  const allTasks = Object.values(store.swarms).flatMap((s) => s.tasks);
  const allAgents = Object.values(store.swarms).flatMap((s) => s.agents);
  const allMessages = Object.values(store.swarms).flatMap((s) => s.messages);
  const allOutputs: Record<string, string> = {};
  for (const s of Object.values(store.swarms)) {
    for (const [k, v] of Object.entries(s.agentOutputs)) {
      allOutputs[k] = v;
    }
  }

  // Header status
  const anyConnected = store.activeSwarmIds.length > 0;
  const anyThinking = Object.values(store.swarms).some((s) => isThinking(s.phase));
  const anyError = Object.values(store.swarms).find((s) => s.error)?.error ?? null;

  // Reports from completed swarms
  const swarmReports = [...store.activeSwarmIds, ...store.completedSwarmIds]
    .filter((id) => store.swarms[id]?.leaderReport)
    .map((id) => ({ id, report: store.swarms[id].leaderReport }));

  const currentReport = reportSwarmId ? store.swarms[reportSwarmId]?.leaderReport : null;
  const currentChatState = reportSwarmId ? chatStore.chats[reportSwarmId] : null;
  const isSwarmComplete = reportSwarmId
    ? store.swarms[reportSwarmId]?.phase === 'complete'
    : false;

  // Full-screen report + chat view
  if (reportSwarmId && currentReport) {
    return (
      <div className="app app--report-view">
        <header className="app-header">
          <button className="back-button" onClick={() => setReportSwarmId(null)}>
            ← Dashboard
          </button>
          <h1>Report — {reportSwarmId.slice(0, 8)}</h1>
          <div className="modal-actions">
            <button
              className="copy-button"
              onClick={() => {
                navigator.clipboard.writeText(currentReport);
                const btn = document.querySelector('.copy-button');
                if (btn) { btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy', 1500); }
              }}
            >Copy</button>
          </div>
        </header>

        {/* WS connections stay alive for chat events */}
        {store.activeSwarmIds.map((id) => (
          <SwarmConnection key={id} swarmId={id} onEvent={handleSwarmEvent} />
        ))}
        {/* Also connect to completed swarms for chat */}
        {store.completedSwarmIds
          .filter((id) => id === reportSwarmId)
          .map((id) => (
            <SwarmConnection key={`chat-${id}`} swarmId={id} onEvent={handleSwarmEvent} />
          ))}

        <ResizableLayout
          left={
            <div className="report-view">
              <div
                className="report-content"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(currentReport) }}
              />
            </div>
          }
          right={
            <ChatPanel
              messages={currentChatState?.messages ?? []}
              streamingMessage={currentChatState?.streamingMessage ?? null}
              onSend={(msg) => handleSendChat(reportSwarmId, msg)}
              chatEnabled={isSwarmComplete}
            />
          }
          defaultLeftPercent={55}
        />
      </div>
    );
  }

  // Dashboard view
  return (
    <div className="app">
      <header className="app-header">
        <h1>Multi-Agent Swarm</h1>
        <div className="status-bar">
          <span className={`connection-status ${anyConnected ? 'connected' : 'disconnected'}`}>
            {anyConnected ? 'Connected' : 'Disconnected'}
          </span>
          {anyThinking && (
            <span className="thinking-badge">
              <span className="thinking-icon">🧠</span>
              <span className="thinking-text">Thinking...</span>
            </span>
          )}
          {store.activeSwarmIds.length > 0 && (
            <span className="phase-badge">{store.activeSwarmIds.length} active</span>
          )}
        </div>
        {anyError && <p className="error-banner">{anyError}</p>}
      </header>

      <div className="controls-row">
        {swarmReports.map((r) => (
          <button
            key={r.id}
            className="report-button active"
            onClick={() => setReportSwarmId(r.id)}
          >
            📄 {r.id.slice(0, 8)}
          </button>
        ))}
        <SwarmControls onStart={handleStartSwarm} />
      </div>

      {/* WS connections — one per active swarm */}
      {store.activeSwarmIds.map((id) => (
        <SwarmConnection key={id} swarmId={id} onEvent={handleSwarmEvent} />
      ))}

      <div className="dashboard-new">
        <div className="top-row">
          <AgentRoster agents={allAgents} outputs={allOutputs} />
          <InboxFeed messages={allMessages} />
        </div>
        <div className="bottom-row">
          <TaskBoard tasks={allTasks} />
        </div>
      </div>
    </div>
  );
}

export default App;
