import { useState } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  availableModels,
  currentConfig,
  onSaveConfig,
  configLoading,
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedModels, setSelectedModels] = useState(
    currentConfig?.council_models || []
  );
  const [chairmanModel, setChairmanModel] = useState(
    currentConfig?.chairman_model || ''
  );

  const handleToggleModel = (modelId) => {
    setSelectedModels((prev) => (
      prev.includes(modelId)
        ? prev.filter((id) => id !== modelId)
        : [...prev, modelId]
    ));
  };

  const handleSave = () => {
    onSaveConfig(selectedModels, chairmanModel);
  };

  const handleReset = () => {
    setSelectedModels(currentConfig?.council_models || []);
    setChairmanModel(currentConfig?.chairman_model || '');
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <h1>LLM Council</h1>
        <button className="new-conversation-btn" onClick={onNewConversation}>
          + New Conversation
        </button>
      </div>

      <div className="conversation-list">
        {conversations.length === 0 ? (
          <div className="no-conversations">No conversations yet</div>
        ) : (
          conversations.map((conv) => (
            <div
              key={conv.id}
              className={`conversation-item ${
                conv.id === currentConversationId ? 'active' : ''
              }`}
              onClick={() => onSelectConversation(conv.id)}
            >
              <div className="conversation-title">
                {conv.title || 'New Conversation'}
              </div>
              <div className="conversation-meta">
                {conv.message_count} messages
              </div>
            </div>
          ))
        )}
      </div>

      <div className="sidebar-settings">
        <button
          className="settings-toggle"
          onClick={() => setSettingsOpen((prev) => !prev)}
        >
          {settingsOpen ? 'Hide Settings' : 'Council Settings'}
        </button>

        {settingsOpen && (
          <div className="settings-panel">
            <div>
              <div className="settings-label">Council Models</div>
              <div className="settings-help">Select which models participate in Stage 1 and Stage 2.</div>
              <div className="model-list">
                {(availableModels || []).map((model) => (
                  <label key={model.id} className="model-option">
                    <input
                      type="checkbox"
                      checked={selectedModels.includes(model.id)}
                      onChange={() => handleToggleModel(model.id)}
                    />
                    <span className="model-option-name">{model.name}</span>
                    <span className="model-option-provider">{model.provider}</span>
                  </label>
                ))}
              </div>
            </div>

            <div>
              <div className="settings-label">Chairman Model</div>
              <select
                className="chairman-select"
                value={chairmanModel}
                onChange={(e) => setChairmanModel(e.target.value)}
              >
                <option value="">Select chairman</option>
                {(availableModels || []).map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} ({model.provider})
                  </option>
                ))}
              </select>
            </div>

            <div className="settings-actions">
              <button className="settings-btn secondary" onClick={handleReset}>
                Reset
              </button>
              <button className="settings-btn primary" onClick={handleSave} disabled={configLoading}>
                {configLoading ? 'Saving...' : 'Save'}
              </button>
            </div>

            <div className="settings-status">
              {selectedModels.length} council model{selectedModels.length === 1 ? '' : 's'} selected
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
