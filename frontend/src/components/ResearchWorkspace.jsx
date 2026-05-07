import { useRef, useState } from 'react';
import KnowledgeGraph from './KnowledgeGraph';
import './ResearchWorkspace.css';

export default function ResearchWorkspace({
  conversation,
  researchLogs,
  researchSessions,
  currentResearchSession,
  researchGraph,
  researchStatus,
  onExportConversation,
  onSaveResearchLog,
  onLoadResearchFile,
  onLoadSavedResearchLog,
  onClearResearchContext,
  onCreateResearchSession,
  onSelectResearchSession,
  onSaveResearchSessionFile,
  onAppendResearchSessionLog,
  onLoadResearchSessionContext,
  onSendResearchPrompt,
}) {
  const fileInputRef = useRef(null);
  const [selectedLog, setSelectedLog] = useState('');
  const [selectedSessionId, setSelectedSessionId] = useState('');
  const [workspaceTab, setWorkspaceTab] = useState('plan');
  const [draftOverrides, setDraftOverrides] = useState({});
  const [logNote, setLogNote] = useState('');

  if (!conversation) return null;

  const activeContext = conversation.research_context;
  const activeSession = currentResearchSession;
  const sessionSelectValue = selectedSessionId || activeSession?.id || '';
  const planDraftKey = activeSession?.id ? `${activeSession.id}:plan.md` : '';
  const logDraftKey = activeSession?.id ? `${activeSession.id}:research_log.md` : '';
  const planDraft = draftOverrides[planDraftKey] ?? activeSession?.plan?.content ?? '';
  const logDraft = draftOverrides[logDraftKey] ?? activeSession?.research_log?.content ?? '';

  const updateDraft = (key, value) => {
    setDraftOverrides((previous) => ({ ...previous, [key]: value }));
  };

  const clearDraft = (key) => {
    setDraftOverrides((previous) => {
      const next = { ...previous };
      delete next[key];
      return next;
    });
  };

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    if (file) onLoadResearchFile(file);
    event.target.value = '';
  };

  const handleOpenSession = () => {
    if (sessionSelectValue) onSelectResearchSession(sessionSelectValue);
  };

  const handleLoadSessionContext = () => {
    if (activeSession?.id) onLoadResearchSessionContext(activeSession.id);
  };

  const handleAppendLogNote = () => {
    if (!logNote.trim()) return;
    onAppendResearchSessionLog(logNote);
    setLogNote('');
  };

  return (
    <div className="research-workspace">
      <div className="research-workspace-main">
        <div>
          <div className="workspace-kicker">Research Workspace</div>
          <div className="workspace-title">{conversation.title || 'New Conversation'}</div>
        </div>
        <div className="workspace-actions">
          <button type="button" onClick={() => onExportConversation('markdown')}>Export MD</button>
          <button type="button" onClick={() => onExportConversation('json')}>Export JSON</button>
          <button type="button" onClick={onSaveResearchLog}>Save to Repo</button>
          <button type="button" onClick={() => fileInputRef.current?.click()}>Upload Plan</button>
          <button type="button" onClick={onCreateResearchSession}>New Session</button>
          <input
            ref={fileInputRef}
            className="workspace-file-input"
            type="file"
            accept=".md,.markdown,.txt,.json"
            onChange={handleFileChange}
          />
        </div>
      </div>

      <div className="workspace-secondary">
        <div className="workspace-context">
          {activeContext ? (
            <>
              <span className="context-badge active">Loaded</span>
              <span>{activeContext.filename}</span>
              <span>{activeContext.content?.length || 0} chars</span>
              <button type="button" onClick={onClearResearchContext}>Clear</button>
            </>
          ) : (
            <>
              <span className="context-badge">No file loaded</span>
              <span>Next prompt uses this conversation only.</span>
            </>
          )}
        </div>

        <div className="workspace-load-saved">
          <select value={selectedLog} onChange={(event) => setSelectedLog(event.target.value)}>
            <option value="">Saved research logs</option>
            {(researchLogs || []).map((log) => (
              <option key={log.filename} value={log.filename}>{log.filename}</option>
            ))}
          </select>
          <button type="button" disabled={!selectedLog} onClick={() => onLoadSavedResearchLog(selectedLog)}>
            Load
          </button>
        </div>
      </div>

      <div className="workspace-session-bar">
        <select value={sessionSelectValue} onChange={(event) => setSelectedSessionId(event.target.value)}>
          <option value="">Research sessions</option>
          {(researchSessions || []).map((session) => (
            <option key={session.id} value={session.id}>{session.title}</option>
          ))}
        </select>
        <button type="button" disabled={!sessionSelectValue} onClick={handleOpenSession}>Open</button>
        <button type="button" disabled={!activeSession} onClick={handleLoadSessionContext}>Load Context</button>
        <div className="workspace-session-actions">
          <button type="button" disabled={!activeSession} onClick={() => onSendResearchPrompt('critique')}>Ask Council</button>
          <button type="button" disabled={!activeSession} onClick={() => onSendResearchPrompt('revise')}>Revise Plan</button>
          <button type="button" disabled={!activeSession} onClick={() => onSendResearchPrompt('tests')}>Extract Tests</button>
        </div>
      </div>

      {activeSession && (
        <div className="workspace-session-panel">
          <div className="workspace-session-header">
            <div>
              <div className="workspace-kicker">Active Session</div>
              <div className="workspace-session-title">{activeSession.title}</div>
            </div>
            <div className="workspace-tabs" role="tablist" aria-label="Research session views">
              {['plan', 'log', 'graph'].map((tab) => (
                <button
                  key={tab}
                  type="button"
                  className={workspaceTab === tab ? 'active' : ''}
                  onClick={() => setWorkspaceTab(tab)}
                >
                  {tab === 'plan' ? 'Plan' : tab === 'log' ? 'Log' : 'Graph'}
                </button>
              ))}
            </div>
          </div>

          {workspaceTab === 'plan' && (
            <div className="session-editor">
              <textarea
                value={planDraft}
                onChange={(event) => updateDraft(planDraftKey, event.target.value)}
                spellCheck="true"
              />
              <div className="session-editor-actions">
                <span>{activeSession.plan?.filename || 'plan.md'}</span>
                <button
                  type="button"
                  onClick={() => {
                    onSaveResearchSessionFile('plan.md', planDraft);
                    clearDraft(planDraftKey);
                  }}
                >
                  Save Plan
                </button>
              </div>
            </div>
          )}

          {workspaceTab === 'log' && (
            <div className="session-editor log-editor">
              <textarea
                value={logDraft}
                onChange={(event) => updateDraft(logDraftKey, event.target.value)}
                spellCheck="true"
              />
              <div className="session-editor-actions">
                <span>{activeSession.research_log?.filename || 'research_log.md'}</span>
                <button
                  type="button"
                  onClick={() => {
                    onSaveResearchSessionFile('research_log.md', logDraft);
                    clearDraft(logDraftKey);
                  }}
                >
                  Save Log
                </button>
              </div>
              <div className="append-log-row">
                <textarea
                  value={logNote}
                  onChange={(event) => setLogNote(event.target.value)}
                  placeholder="Add a research note"
                  rows={3}
                />
                <button type="button" disabled={!logNote.trim()} onClick={handleAppendLogNote}>Append</button>
              </div>
            </div>
          )}

          {workspaceTab === 'graph' && (
            <KnowledgeGraph graph={researchGraph} activeSessionId={activeSession.id} />
          )}
        </div>
      )}

      {researchStatus && <div className="workspace-status">{researchStatus}</div>}
    </div>
  );
}
