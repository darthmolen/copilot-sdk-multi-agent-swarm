import { useState, useEffect } from 'react';
import { useSwarmState, isThinking } from './hooks/useSwarmState';
import { useWebSocket } from './hooks/useWebSocket';
import { SwarmControls } from './components/SwarmControls';
import { TaskBoard } from './components/TaskBoard';
import { AgentRoster } from './components/AgentRoster';
import { ChatPanel } from './components/ChatPanel';
import { InboxFeed } from './components/InboxFeed';
import './App.css';

function App() {
  const { state, dispatch } = useSwarmState();
  const [swarmId, setSwarmId] = useState<string | null>(null);
  const { connected } = useWebSocket(swarmId, dispatch);
  const [showReport, setShowReport] = useState(false);

  // Auto-pop modal when synthesis report arrives
  useEffect(() => {
    if (state.leaderReport && state.leaderReport.length > 50) {
      setShowReport(true);
    }
  }, [state.leaderReport]);

  return (
    <div className="app">
      <header className="app-header">
        <h1>Multi-Agent Swarm</h1>
        {swarmId && (
          <div className="status-bar">
            <span className={`connection-status ${connected ? 'connected' : 'disconnected'}`}>
              {connected ? 'Connected' : 'Disconnected'}
            </span>
            {state.phase && <span className="phase-badge">{state.phase}</span>}
            {(isThinking(state.phase) || (connected && !state.phase)) && (
              <span className="thinking-badge">
                <span className="thinking-icon">🧠</span>
                <span className="thinking-text">Thinking...</span>
              </span>
            )}
            {state.roundNumber > 0 && <span className="round-badge">Round {state.roundNumber}</span>}
          </div>
        )}
        {state.error && <p className="error-banner">{state.error}</p>}
      </header>

      <div className="controls-row">
        {state.leaderReport && (
          <button className="report-button" onClick={() => setShowReport(true)}>
            📄 Report
          </button>
        )}
        <SwarmControls onStart={setSwarmId} />
      </div>

      <div className="dashboard-new">
        <div className="top-row">
          <AgentRoster agents={state.agents} outputs={state.agentOutputs} />
          <InboxFeed messages={state.messages} />
        </div>
        <div className="bottom-row">
          <TaskBoard tasks={state.tasks} />
        </div>
      </div>

      {/* Report Modal */}
      {showReport && (
        <div className="modal-overlay" onClick={() => setShowReport(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Synthesis Report</h2>
              <button className="modal-close" onClick={() => setShowReport(false)}>✕</button>
            </div>
            <div className="modal-body">
              <ChatPanel plan={state.leaderPlan} report={state.leaderReport} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
