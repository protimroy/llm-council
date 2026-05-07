import { useRef, useState } from 'react';
import './ResearchWorkspace.css';

export default function ResearchWorkspace({
  conversation,
  researchLogs,
  researchStatus,
  onExportConversation,
  onSaveResearchLog,
  onLoadResearchFile,
  onLoadSavedResearchLog,
  onClearResearchContext,
}) {
  const fileInputRef = useRef(null);
  const [selectedLog, setSelectedLog] = useState('');

  if (!conversation) return null;

  const activeContext = conversation.research_context;

  const handleFileChange = (event) => {
    const file = event.target.files?.[0];
    if (file) onLoadResearchFile(file);
    event.target.value = '';
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

      {researchStatus && <div className="workspace-status">{researchStatus}</div>}
    </div>
  );
}
