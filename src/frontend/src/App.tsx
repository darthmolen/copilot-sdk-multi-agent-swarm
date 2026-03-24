import { useState } from 'react';
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
            {isThinking(state.phase) && (
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
      <SwarmControls onStart={setSwarmId} />
      <div className="dashboard">
        <ChatPanel plan={state.leaderPlan} report={state.leaderReport} />
        <TaskBoard tasks={state.tasks} />
        <AgentRoster agents={state.agents} outputs={state.agentOutputs} />
        <InboxFeed messages={state.messages} />
      </div>
    </div>
  );
}

export default App;
