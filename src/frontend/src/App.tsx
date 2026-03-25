import { useReducer, useCallback, useState } from 'react';
import { multiSwarmReducer, initialMultiSwarmState, isThinking } from './hooks/useSwarmState';
import { useWebSocket } from './hooks/useWebSocket';
import { SwarmControls } from './components/SwarmControls';
import { TaskBoard } from './components/TaskBoard';
import { AgentRoster } from './components/AgentRoster';
import { ChatPanel } from './components/ChatPanel';
import { InboxFeed } from './components/InboxFeed';
import type { SwarmEvent } from './types/swarm';
import './App.css';

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
  const [store, dispatch] = useReducer(multiSwarmReducer, initialMultiSwarmState);
  const [reportSwarmId, setReportSwarmId] = useState<string | null>(null);

  const handleSwarmEvent = useCallback(
    (swarmId: string, event: SwarmEvent) => {
      dispatch({ type: 'swarm.event', swarmId, event });
    },
    [],
  );

  function handleStartSwarm(swarmId: string) {
    dispatch({ type: 'swarm.add', swarmId });
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

  // Header status: any connected, any thinking
  const anyConnected = store.activeSwarmIds.length > 0;
  const anyThinking = Object.values(store.swarms).some((s) => isThinking(s.phase));
  const anyError = Object.values(store.swarms).find((s) => s.error)?.error ?? null;

  // Reports from completed swarms
  const swarmReports = [...store.activeSwarmIds, ...store.completedSwarmIds]
    .filter((id) => store.swarms[id]?.leaderReport)
    .map((id) => ({ id, report: store.swarms[id].leaderReport }));

  const currentReport = reportSwarmId ? store.swarms[reportSwarmId]?.leaderReport : null;

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

      {/* Report Modal */}
      {reportSwarmId && currentReport && (
        <div className="modal-overlay" onClick={() => setReportSwarmId(null)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Report — {reportSwarmId.slice(0, 8)}</h2>
              <div className="modal-actions">
                <button
                  className="copy-button"
                  onClick={() => {
                    navigator.clipboard.writeText(currentReport);
                    const btn = document.querySelector('.copy-button');
                    if (btn) { btn.textContent = 'Copied!'; setTimeout(() => btn.textContent = 'Copy', 1500); }
                  }}
                >Copy</button>
                <button className="modal-close" onClick={() => setReportSwarmId(null)}>✕</button>
              </div>
            </div>
            <div className="modal-body">
              <ChatPanel plan="" report={currentReport} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
