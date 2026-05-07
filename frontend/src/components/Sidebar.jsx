import { useMemo, useState } from 'react';
import './Sidebar.css';

export default function Sidebar({
  conversations,
  currentConversationId,
  onSelectConversation,
  onNewConversation,
  availableModels,
  currentConfig,
  onSaveConfig,
  onRefreshModels,
  modelCatalogMeta,
  configLoading,
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedModelDraft, setSelectedModelDraft] = useState(null);
  const [chairmanModelDraft, setChairmanModelDraft] = useState(null);
  const [modelSearch, setModelSearch] = useState('');
  const [providerFilter, setProviderFilter] = useState('all');
  const [chairmanSearch, setChairmanSearch] = useState('');

  const selectedModels = selectedModelDraft ?? currentConfig?.council_models ?? [];
  const chairmanModel = chairmanModelDraft ?? currentConfig?.chairman_model ?? '';

  const providers = useMemo(() => {
    const providerNames = new Set((availableModels || []).map((model) => model.provider || 'Other'));
    return ['all', ...Array.from(providerNames).sort()];
  }, [availableModels]);

  const filteredModels = useMemo(() => {
    const query = modelSearch.trim().toLowerCase();
    return (availableModels || [])
      .filter((model) => providerFilter === 'all' || model.provider === providerFilter)
      .filter((model) => {
        if (!query) return true;
        return [model.id, model.name, model.provider, model.description]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(query));
      })
      .slice(0, 250);
  }, [availableModels, modelSearch, providerFilter]);

  const chairmanOptions = useMemo(() => {
    const query = chairmanSearch.trim().toLowerCase();
    if (!query) return (availableModels || []).slice(0, 250);
    return (availableModels || [])
      .filter((model) => [model.id, model.name, model.provider]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(query)))
      .slice(0, 250);
  }, [availableModels, chairmanSearch]);

  const selectedModelDetails = selectedModels
    .map((modelId) => (availableModels || []).find((model) => model.id === modelId) || { id: modelId, name: modelId })
    .filter(Boolean);

  const handleToggleModel = (modelId) => {
    setSelectedModelDraft((prev) => {
      const currentModels = prev ?? currentConfig?.council_models ?? [];
      return currentModels.includes(modelId)
        ? currentModels.filter((id) => id !== modelId)
        : [...currentModels, modelId];
    });
  };

  const handleSave = () => {
    onSaveConfig(selectedModels, chairmanModel);
  };

  const handleReset = () => {
    setSelectedModelDraft(null);
    setChairmanModelDraft(null);
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
              <div className="settings-row-title">
                <div>
                  <div className="settings-label">OpenRouter Models</div>
                  <div className="settings-help">
                    {availableModels?.length || 0} models loaded from {modelCatalogMeta?.source || 'catalog'}.
                  </div>
                </div>
                <button className="settings-icon-btn" onClick={onRefreshModels} disabled={configLoading} title="Refresh model catalog">
                  Refresh
                </button>
              </div>
              {modelCatalogMeta?.error && (
                <div className="settings-warning">Catalog fallback: {modelCatalogMeta.error}</div>
              )}
              <div className="model-filters">
                <input
                  className="model-search"
                  value={modelSearch}
                  onChange={(event) => setModelSearch(event.target.value)}
                  placeholder="Search by model, provider, modality..."
                />
                <select
                  className="provider-filter"
                  value={providerFilter}
                  onChange={(event) => setProviderFilter(event.target.value)}
                >
                  {providers.map((provider) => (
                    <option key={provider} value={provider}>
                      {provider === 'all' ? 'All providers' : provider}
                    </option>
                  ))}
                </select>
              </div>

              {selectedModelDetails.length > 0 && (
                <div className="selected-models">
                  {selectedModelDetails.map((model) => (
                    <button
                      key={model.id}
                      className="selected-model-chip"
                      onClick={() => handleToggleModel(model.id)}
                      title="Remove from council"
                    >
                      {model.name || model.id}
                    </button>
                  ))}
                </div>
              )}

              <div className="settings-help">Select which models participate in Stage 1 and Stage 2.</div>
              <div className="model-list">
                {filteredModels.map((model) => (
                  <label key={model.id} className="model-option">
                    <input
                      type="checkbox"
                      checked={selectedModels.includes(model.id)}
                      onChange={() => handleToggleModel(model.id)}
                    />
                    <span className="model-option-main">
                      <span className="model-option-name">{model.name}</span>
                      <span className="model-option-id">{model.id}</span>
                    </span>
                    <span className="model-option-provider">{model.provider}</span>
                    {model.supports_reasoning && <span className="reasoning-dot" title="Reasoning artifacts supported">Reasoning</span>}
                  </label>
                ))}
              </div>
              {(availableModels || []).length > filteredModels.length && (
                <div className="settings-help">Showing first {filteredModels.length} matching models. Search to narrow the catalog.</div>
              )}
            </div>

            <div>
              <div className="settings-label">Chairman Model</div>
              <input
                className="model-search"
                value={chairmanSearch}
                onChange={(event) => setChairmanSearch(event.target.value)}
                placeholder="Search chairman model..."
              />
              <select
                className="chairman-select"
                value={chairmanModel}
                onChange={(e) => setChairmanModelDraft(e.target.value)}
              >
                <option value="">Select chairman</option>
                {chairmanOptions.map((model) => (
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
