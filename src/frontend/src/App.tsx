import { useReducer, useCallback, useState, useEffect, useRef } from 'react';
import toast, { Toaster } from 'react-hot-toast';
import { multiSwarmReducer, initialMultiSwarmState, isThinking, shouldShowReportView } from './hooks/useSwarmState';
import { chatReducer, initialChatStore } from './hooks/useChatState';
import { useWebSocket } from './hooks/useWebSocket';
import { SwarmControls } from './components/SwarmControls';
import { SwarmStatusWindow } from './components/SwarmStatusWindow';
import { TaskBoard } from './components/TaskBoard';
import { AgentRoster } from './components/AgentRoster';
import { InboxFeed } from './components/InboxFeed';
import { ResizableLayout } from './components/ResizableLayout';
import { ToolCardList } from './components/ToolCard';
import { ArtifactList } from './components/ArtifactList';
import { ReportRightPanel } from './components/ReportRightPanel';
import { useMermaid } from './hooks/useMermaid';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import type { SwarmEvent, FileInfo, ActiveTool } from './types/swarm';
import { saveReport, getSavedReports, getReportById, truncateTitle } from './utils/savedReportStorage';
import { parseSessionFromSearch } from './utils/urlSession';
import { buildReportList, type SuspendedSwarm } from './utils/buildReportList';
import { hydrateTasksIntoSwarm } from './utils/hydrateTasksIntoSwarm';
import { ReportList } from './components/ReportList';
import { InterventionView } from './components/InterventionView';
import './App.css';

const API_BASE = import.meta.env.VITE_API_URL ?? '';
const DEBUG = import.meta.env.VITE_DEBUG === 'true';

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
  const [authChecked, setAuthChecked] = useState(false);

  // Probe backend to see if auth is required
  useEffect(() => {
    if (authed) { setAuthChecked(true); return; }
    fetch(`${API_BASE}/api/templates`)
      .then((res) => {
        if (res.ok) {
          // Backend doesn't require auth — skip the gate
          setAuthed(true);
        }
        setAuthChecked(true);
      })
      .catch(() => setAuthChecked(true));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!authChecked) return null;

  if (!authed) {
    return <AuthGate onAuth={() => setAuthed(true)} />;
  }

  return (
    <>
      <Toaster position="top-right" toastOptions={{
        style: { background: '#1e293b', color: '#e2e8f0', border: '1px solid #334155' },
      }} />
      <SwarmDashboard />
    </>
  );
}

function SwarmDashboard() {
  const [store, swarmDispatch] = useReducer(multiSwarmReducer, initialMultiSwarmState);
  const [chatStore, chatDispatch] = useReducer(chatReducer, initialChatStore);
  const [reportSwarmId, setReportSwarmId] = useState<string | null>(() => {
    const sessionId = parseSessionFromSearch(window.location.search);
    if (sessionId) {
      // If in localStorage, show immediately
      if (getReportById(sessionId)) return sessionId;
      // Otherwise return the ID — useEffect below will try to fetch from backend
      return sessionId;
    }
    return null;
  });

  // Artifact explorer state
  const [swarmFiles, setSwarmFiles] = useState<FileInfo[]>([]);
  const [activeFilePath, setActiveFilePath] = useState<string | null>(null);
  const [activeFileContent, setActiveFileContent] = useState<string | null>(null);

  // Intervention view state
  const [interventionTaskId, setInterventionTaskId] = useState<string | null>(null);

  // Suspended swarms from DB (for resume button in ReportList)
  const [suspendedSwarms, setSuspendedSwarms] = useState<SuspendedSwarm[]>([]);
  useEffect(() => {
    const apiKey = getApiKey();
    fetch(`${API_BASE}/api/swarms`, {
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
    })
      .then((r) => (r.ok ? r.json() : { swarms: [] }))
      .then((data) => {
        const suspended = (data.swarms ?? []).filter(
          (s: { phase: string }) => s.phase === 'suspended',
        );
        setSuspendedSwarms(suspended);
      })
      .catch(() => {}); // DB may not be configured
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch report from backend when URL has a session but localStorage is empty
  const fetchedRef = useRef(false);
  useEffect(() => {
    if (fetchedRef.current) return;
    const sessionId = parseSessionFromSearch(window.location.search);
    if (!sessionId || getReportById(sessionId)) return;
    fetchedRef.current = true;

    const apiKey = getApiKey();
    fetch(`${API_BASE}/api/swarm/${sessionId}/status`, {
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.report) {
          const firstLine = data.report.split('\n')[0].replace(/^#+\s*/, '');
          saveReport({
            swarmId: sessionId,
            title: truncateTitle(firstLine),
            timestamp: Date.now(),
            report: data.report,
            phase: data.phase ?? 'complete',
          });
          // Hydrate tasks into swarm state so report view can display them
          for (const action of hydrateTasksIntoSwarm(sessionId, data.tasks)) {
            swarmDispatch(action);
          }
          setReportSwarmId(sessionId);
        }
      })
      .catch(() => {
        // Backend unreachable or swarm not found — stay on dashboard
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSwarmEvent = useCallback(
    (swarmId: string, event: SwarmEvent) => {
      if (DEBUG) console.log(`[Event] ${event.type}`, { swarmId, ...event.data });
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
      } else if (event.type === 'agent.tool_call') {
        // Route to chat reducer if message_id present (chat context)
        if (event.data.message_id) {
          chatDispatch({
            type: 'chat.tool_start',
            swarmId,
            toolName: (event.data.tool_name as string) ?? '',
            toolCallId: (event.data.tool_call_id as string) ?? '',
            input: event.data.input as string | undefined,
          });
        }
        // Always route to swarm reducer (dashboard tool cards)
        swarmDispatch({ type: 'swarm.event', swarmId, event });
      } else if (event.type === 'agent.tool_result') {
        if (event.data.message_id) {
          chatDispatch({
            type: 'chat.tool_result',
            swarmId,
            toolCallId: (event.data.tool_call_id as string) ?? '',
            success: event.data.success as boolean,
            output: event.data.output as string | undefined,
            error: event.data.error as string | undefined,
          });
        }
        swarmDispatch({ type: 'swarm.event', swarmId, event });
      } else {
        // All other events go to swarm reducer
        swarmDispatch({ type: 'swarm.event', swarmId, event });

        // Notify user when swarm is suspended
        if (event.type === 'swarm.suspended') {
          toast('Swarm paused — action required', { icon: '\u23F8', duration: 8000 });
        }

        // Auto-switch to report view when Q&A phase starts or swarm completes
        if (
          event.type === 'swarm.phase_changed' &&
          (event.data.phase === 'qa' || event.data.phase === 'complete')
        ) {
          setReportSwarmId(swarmId);
        }

        // Auto-switch back to dashboard when swarm kicks off planning
        if (event.type === 'swarm.phase_changed' && event.data.phase === 'planning') {
          setReportSwarmId(null);
          toast('Swarm started! Watch progress on the task board.', { icon: '\u{1F680}', duration: 5000 });
        }

        // Live artifact list: append new files as agents write them
        if (event.type === 'file.created' && event.data.swarm_id === reportSwarmId) {
          const filename = event.data.filename as string;
          const sizeBytes = (event.data.size_bytes as number) ?? 0;
          setSwarmFiles((prev) => {
            if (prev.some((f) => f.name === filename)) return prev;
            return [...prev, { name: filename, path: filename, size: sizeBytes }];
          });
        }
      }
    },
    [],
  );

  function handleStartSwarm(swarmId: string) {
    swarmDispatch({ type: 'swarm.add', swarmId });

    // Poll swarm status shortly after start to catch phases emitted before WebSocket connected
    const apiKey = getApiKey();
    const headers: Record<string, string> = apiKey ? { 'X-API-Key': apiKey } : {};
    setTimeout(() => {
      fetch(`${API_BASE}/api/swarm/${swarmId}/status`, { headers })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          if (data?.phase === 'qa') {
            setReportSwarmId(swarmId);
            swarmDispatch({
              type: 'swarm.event',
              swarmId,
              event: { type: 'swarm.phase_changed', data: { phase: 'qa', swarm_id: swarmId } },
            });
          }
        })
        .catch(() => null);
    }, 500);
  }

  // Auto-save completed reports to localStorage
  useEffect(() => {
    for (const id of store.completedSwarmIds) {
      const swarm = store.swarms[id];
      if (swarm?.leaderReport && swarm.phase === 'complete') {
        const firstLine = swarm.leaderReport.split('\n')[0].replace(/^#+\s*/, '');
        saveReport({
          swarmId: id,
          title: truncateTitle(firstLine),
          timestamp: Date.now(),
          report: swarm.leaderReport,
          phase: swarm.phase,
        });
      }
    }
  }, [store.completedSwarmIds, store.swarms]);

  // When entering report view: ensure report on server + fetch file list
  const artifactFetchedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!reportSwarmId) {
      artifactFetchedRef.current = null;  // Reset so re-entry re-fetches
      return;
    }
    if (artifactFetchedRef.current === reportSwarmId) return;
    artifactFetchedRef.current = reportSwarmId;

    const apiKey = getApiKey();
    const headers: Record<string, string> = apiKey ? { 'X-API-Key': apiKey } : {};

    // Hydrate tasks if not already in memory (e.g. viewing a past report from localStorage)
    if (!(store.swarms[reportSwarmId]?.tasks?.length)) {
      fetch(`${API_BASE}/api/swarm/${reportSwarmId}/status`, { headers })
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => {
          for (const action of hydrateTasksIntoSwarm(reportSwarmId, data?.tasks)) {
            swarmDispatch(action);
          }
        })
        .catch(() => null);
    }

    // Step 1: Ensure the synthesis report exists on disk
    const reportText = store.swarms[reportSwarmId]?.leaderReport || getReportById(reportSwarmId)?.report;
    const ensurePromise = reportText
      ? fetch(`${API_BASE}/api/swarm/${reportSwarmId}/files/ensure-report`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...headers },
          body: JSON.stringify({ report: reportText }),
        }).catch(() => null)
      : Promise.resolve(null);

    // Step 2: After ensure, fetch file list
    ensurePromise.then(() =>
      fetch(`${API_BASE}/api/swarm/${reportSwarmId}/files`, { headers })
    )
      .then((res) => (res.ok ? res.json() : { files: [] }))
      .then((data) => {
        const files: FileInfo[] = data.files ?? [];
        setSwarmFiles(files);
        // Default to synthesis_report.md if it exists
        const defaultFile = files.find((f: FileInfo) => f.name === 'synthesis_report.md')?.path
          ?? files[0]?.path ?? null;
        setActiveFilePath(defaultFile);
        // Fetch the default file content
        if (defaultFile) {
          fetch(`${API_BASE}/api/swarm/${reportSwarmId}/files/${defaultFile}`, { headers })
            .then((r) => (r.ok ? r.json() : null))
            .then((d) => { if (d?.content) setActiveFileContent(d.content); })
            .catch(() => null);
        }
      })
      .catch(() => null);
  }, [reportSwarmId]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch file content when active file changes
  function handleSelectArtifact(path: string) {
    if (!reportSwarmId || path === activeFilePath) return;
    setActiveFilePath(path);
    setActiveFileContent(null); // clear while loading

    const apiKey = getApiKey();
    fetch(`${API_BASE}/api/swarm/${reportSwarmId}/files/${path}`, {
      headers: apiKey ? { 'X-API-Key': apiKey } : {},
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => { if (data?.content) setActiveFileContent(data.content); })
      .catch(() => null);
  }

  // Sync URL with current report view
  useEffect(() => {
    if (reportSwarmId) {
      window.history.replaceState(null, '', `?session=${reportSwarmId}`);
    } else {
      window.history.replaceState(null, '', window.location.pathname);
    }
  }, [reportSwarmId]);

  async function handleSendChat(swarmId: string, message: string, activeFile?: string | null) {
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
      body: JSON.stringify({ message, active_file: activeFile ?? null }),
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
  const allActiveTools: ActiveTool[] = Object.values(store.swarms).flatMap((s) => s.activeTools);

  // Latest active swarm for status window
  const latestActiveSwarmId = store.activeSwarmIds.length > 0
    ? store.activeSwarmIds[store.activeSwarmIds.length - 1]
    : null;
  const latestActiveSwarm = latestActiveSwarmId ? store.swarms[latestActiveSwarmId] ?? null : null;

  // Header status
  const anyConnected = store.activeSwarmIds.length > 0;
  const anyThinking = Object.values(store.swarms).some((s) => isThinking(s.phase));
  const anyError = Object.values(store.swarms).find((s) => s.error)?.error ?? null;

  // Unified report list from live swarms + localStorage
  const savedReports = getSavedReports();
  const reportListItems = buildReportList(
    store.activeSwarmIds, store.completedSwarmIds, store.swarms, savedReports, suspendedSwarms,
  );
  const currentReport = reportSwarmId
    ? (store.swarms[reportSwarmId]?.leaderReport || getReportById(reportSwarmId)?.report || null)
    : null;
  const currentPhase = reportSwarmId ? (store.swarms[reportSwarmId]?.phase ?? null) : null;
  const currentChatState = reportSwarmId ? chatStore.chats[reportSwarmId] : null;
  // Chat is always enabled — backend can resume_session for any past swarm
  const chatEnabled = !!reportSwarmId;

  // Tasks for the report swarm (used by TaskPillBar in the report view)
  const reportSwarmTasks = reportSwarmId ? (store.swarms[reportSwarmId]?.tasks ?? []) : [];

  // Compute failed/timeout tasks for intervention view
  const failedTasks = allTasks.filter(
    (t) => t.status === 'failed' || t.status === 'timeout',
  );

  // Handler to enter intervention view when a failed task pill is clicked
  const handleInterventionClick = (taskId: string) => setInterventionTaskId(taskId);

  // Resume a suspended swarm from DB
  const handleResumeSwarm = async (swarmId: string) => {
    const apiKey = getApiKey();
    try {
      const resp = await fetch(`${API_BASE}/api/swarm/${swarmId}/resume`, {
        method: 'POST',
        headers: apiKey ? { 'X-API-Key': apiKey } : {},
      });
      if (!resp.ok) {
        const detail = await resp.json().catch(() => ({}));
        toast.error(`Resume failed: ${detail.detail ?? resp.statusText}`);
        return;
      }
      toast.success('Swarm resuming...');
      // Add to active swarms so we start tracking it
      swarmDispatch({ type: 'swarm.add', swarmId });
      // Remove from suspended list
      setSuspendedSwarms((prev) => prev.filter((s) => s.id !== swarmId));

      // Hydrate existing task/agent state from backend before WS connects
      try {
        const statusResp = await fetch(`${API_BASE}/api/swarm/${swarmId}/status`, {
          headers: apiKey ? { 'X-API-Key': apiKey } : {},
        });
        if (statusResp.ok) {
          const status = await statusResp.json();
          for (const task of status.tasks ?? []) {
            swarmDispatch({
              type: 'swarm.event', swarmId,
              event: { type: 'task.created', data: { task, swarm_id: swarmId } },
            });
            swarmDispatch({
              type: 'swarm.event', swarmId,
              event: { type: 'task.updated', data: { task, swarm_id: swarmId } },
            });
          }
          for (const agent of status.agents ?? []) {
            swarmDispatch({
              type: 'swarm.event', swarmId,
              event: { type: 'agent.spawned', data: { agent, swarm_id: swarmId } },
            });
          }
        }
      } catch { /* status fetch is best-effort */ }
    } catch {
      toast.error('Failed to resume swarm');
    }
  };

  // Determine template key for the intervention swarm (use first active swarm's id as fallback)
  const interventionSwarmId = latestActiveSwarmId ?? reportSwarmId ?? '';

  // Mermaid diagram rendering for report view
  const reportContentRef = useRef<HTMLDivElement>(null);
  useMermaid(reportContentRef, [activeFileContent, currentReport]);

  // Intervention view: shown when a task is selected for intervention
  if (interventionTaskId && failedTasks.length > 0) {
    return (
      <div className="app app--intervention-view">
        {/* Keep WS connections alive */}
        {store.activeSwarmIds.map((id) => (
          <SwarmConnection key={id} swarmId={id} onEvent={handleSwarmEvent} />
        ))}
        <InterventionView
          swarmId={interventionSwarmId}
          templateKey={interventionSwarmId}
          tasks={failedTasks}
          selectedTaskId={interventionTaskId}
          onSelectTask={setInterventionTaskId}
          agentOutputs={allOutputs}
          onBack={() => setInterventionTaskId(null)}
          onSaveAndRetry={async () => {
            if (!interventionSwarmId) return;
            const apiKey = getApiKey();
            try {
              await fetch(`${API_BASE}/api/swarm/${interventionSwarmId}/continue`, {
                method: 'POST',
                headers: apiKey ? { 'X-API-Key': apiKey } : {},
              });
              setInterventionTaskId(null);
            } catch (err) {
              console.error('Failed to continue swarm:', err);
            }
          }}
        />
      </div>
    );
  }

  // Full-screen report + chat view (also shown during QA phase before report exists)
  if (shouldShowReportView(reportSwarmId, currentReport, currentPhase)) {
    return (
      <div className="app app--report-view">
        <header className="app-header">
          <button className="back-button" onClick={() => setReportSwarmId(null)}>
            ← Dashboard
          </button>
          <h1>Report — {reportSwarmId!.slice(0, 8)}</h1>
          <div className="modal-actions">
            <button
              className="copy-button"
              onClick={() => {
                navigator.clipboard.writeText(currentReport ?? '');
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
        {/* Always connect WS for the current report — needed for saved/resumed sessions */}
        {reportSwarmId && !store.activeSwarmIds.includes(reportSwarmId) && (
          <SwarmConnection key={`chat-${reportSwarmId}`} swarmId={reportSwarmId} onEvent={handleSwarmEvent} />
        )}

        <ResizableLayout
          left={
            <div className="report-view">
              <ArtifactList
                files={swarmFiles}
                activeFile={activeFilePath}
                onSelect={handleSelectArtifact}
                swarmId={reportSwarmId ?? undefined}
              />
              <div
                ref={reportContentRef}
                className="report-content"
                dangerouslySetInnerHTML={{
                  __html: renderMarkdown(activeFileContent ?? currentReport ?? ''),
                }}
              />
            </div>
          }
          right={
            <ReportRightPanel
              swarmId={reportSwarmId ?? undefined}
              tasks={reportSwarmTasks}
              entries={currentChatState?.entries ?? []}
              streamingMessage={currentChatState?.streamingMessage ?? null}
              sessionStarting={currentChatState?.sessionStarting ?? false}
              onSend={(msg) => handleSendChat(reportSwarmId!, msg, activeFilePath)}
              chatEnabled={chatEnabled}
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
        <ReportList
          items={reportListItems}
          activeId={reportSwarmId}
          onSelect={setReportSwarmId}
          onResume={handleResumeSwarm}
        />
        <div className="controls-stack">
          {latestActiveSwarm && latestActiveSwarmId && (
            <SwarmStatusWindow
              swarmId={latestActiveSwarmId}
              phase={latestActiveSwarm.phase ?? 'starting'}
              tasks={latestActiveSwarm.tasks}
              agents={latestActiveSwarm.agents}
              roundNumber={latestActiveSwarm.roundNumber}
              suspended={latestActiveSwarm.suspended}
              onGoToReport={() => setReportSwarmId(latestActiveSwarmId)}
              onClose={() => swarmDispatch({ type: 'swarm.remove', swarmId: latestActiveSwarmId })}
            />
          )}
          <SwarmControls onStart={handleStartSwarm} />
        </div>
      </div>

      {/* Failed task pills — click to enter intervention view */}
      {failedTasks.length > 0 && (
        <div className="failed-tasks-bar">
          <span className="failed-tasks-label">Failed tasks:</span>
          {failedTasks.map((t) => (
            <button
              key={t.id}
              className="failed-task-pill"
              onClick={() => handleInterventionClick(t.id)}
              title={`${t.subject} (${t.status})`}
            >
              {t.worker_name} — {t.status}
            </button>
          ))}
        </div>
      )}

      {/* WS connections — one per active swarm */}
      {store.activeSwarmIds.map((id) => (
        <SwarmConnection key={id} swarmId={id} onEvent={handleSwarmEvent} />
      ))}

      <div className="dashboard-new">
        <div className="top-row">
          <AgentRoster agents={allAgents} outputs={allOutputs} />
          <InboxFeed messages={allMessages} />
        </div>
        <ToolCardList tools={allActiveTools.filter((t) => t.status === 'running')} />
        <div className="bottom-row">
          <TaskBoard tasks={allTasks} />
        </div>
      </div>
    </div>
  );
}

export default App;
