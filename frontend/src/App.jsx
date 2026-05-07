import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ChatInterface from './components/ChatInterface';
import { api } from './api';
import './App.css';

function App() {
  const [conversations, setConversations] = useState([]);
  const [currentConversationId, setCurrentConversationId] = useState(null);
  const [currentConversation, setCurrentConversation] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [availableModels, setAvailableModels] = useState([]);
  const [currentConfig, setCurrentConfig] = useState(null);
  const [modelCatalogMeta, setModelCatalogMeta] = useState(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [researchLogs, setResearchLogs] = useState([]);
  const [researchStatus, setResearchStatus] = useState('');

  // Load conversations on mount
  useEffect(() => {
    loadConversations();
    loadConfig();
    loadResearchLogs();
  }, []);

  // Load conversation details when selected
  useEffect(() => {
    if (currentConversationId) {
      loadConversation(currentConversationId);
    }
  }, [currentConversationId]);

  const loadConversations = async () => {
    try {
      const convs = await api.listConversations();
      setConversations(convs);
    } catch (error) {
      console.error('Failed to load conversations:', error);
    }
  };

  const loadConversation = async (id) => {
    try {
      const conv = await api.getConversation(id);
      setCurrentConversation(conv);
    } catch (error) {
      console.error('Failed to load conversation:', error);
    }
  };

  const loadConfig = async () => {
    try {
      const data = await api.listModels();
      setAvailableModels(data.available_models || []);
      setCurrentConfig(data.current_config || null);
      setModelCatalogMeta({
        source: data.model_source,
        error: data.model_catalog_error,
        fetchedAt: data.model_catalog_fetched_at,
      });
    } catch (error) {
      console.error('Failed to load config:', error);
    }
  };

  const loadResearchLogs = async () => {
    try {
      const data = await api.listResearchLogs();
      setResearchLogs(data.logs || []);
    } catch (error) {
      console.error('Failed to load research logs:', error);
    }
  };

  const handleRefreshModels = async () => {
    setConfigLoading(true);
    try {
      const data = await api.refreshModels();
      setAvailableModels(data.available_models || []);
      setModelCatalogMeta({
        source: data.source,
        error: data.error,
        fetchedAt: data.fetched_at,
      });
    } catch (error) {
      console.error('Failed to refresh model catalog:', error);
    } finally {
      setConfigLoading(false);
    }
  };

  const handleSaveConfig = async (councilModels, chairmanModel) => {
    setConfigLoading(true);
    try {
      const config = await api.updateConfig(councilModels, chairmanModel);
      setCurrentConfig(config);
    } catch (error) {
      console.error('Failed to save config:', error);
    } finally {
      setConfigLoading(false);
    }
  };

  const handleNewConversation = async () => {
    try {
      const newConv = await api.createConversation();
      setConversations([
        { id: newConv.id, created_at: newConv.created_at, title: newConv.title, message_count: 0 },
        ...conversations,
      ]);
      setCurrentConversationId(newConv.id);
    } catch (error) {
      console.error('Failed to create conversation:', error);
    }
  };

  const handleSelectConversation = (id) => {
    setCurrentConversationId(id);
  };

  const handleSendMessage = async (content) => {
    if (!currentConversationId) return;

    setIsLoading(true);
    try {
      // Optimistically add user message to UI
      const userMessage = { role: 'user', content };
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, userMessage],
      }));

      // Create a partial assistant message that will be updated progressively
      const assistantMessage = {
        role: 'assistant',
        stage1: null,
        stage2: null,
        stage3: null,
        metadata: null,
        trace: null,
        judgeDecision: null,
        verificationReport: null,
        finalDecision: null,
        critiqueReport: null,
        secondRound: null,
        loading: {
          stage1: false,
          stage2: false,
          stage3: false,
          fastJudge: false,
          verification: false,
          secondRound: false,
        },
      };

      // Add the partial assistant message
      setCurrentConversation((prev) => ({
        ...prev,
        messages: [...prev.messages, assistantMessage],
      }));

      // Send message with streaming
      await api.sendMessageStream(currentConversationId, content, (eventType, event) => {
        switch (eventType) {
          case 'trace_context':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.trace = event.data;
              return { ...prev, messages };
            });
            break;

          case 'stage1_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage1 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage1_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage1 = event.data;
              lastMsg.loading.stage1 = false;
              return { ...prev, messages };
            });
            break;

          case 'stage2_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage2 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage2_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage2 = event.data;
              lastMsg.metadata = event.metadata;
              lastMsg.loading.stage2 = false;
              if (event.metadata?.trace) {
                lastMsg.trace = event.metadata.trace;
              }
              // Also store critique_report from metadata if available
              if (event.metadata?.critique_report) {
                lastMsg.critiqueReport = event.metadata.critique_report;
              }
              return { ...prev, messages };
            });
            break;

          case 'fast_judge_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.fastJudge = true;
              return { ...prev, messages };
            });
            break;

          case 'fast_judge_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.judgeDecision = event.data;
              lastMsg.loading.fastJudge = false;
              return { ...prev, messages };
            });
            break;

          case 'verification_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.verification = true;
              return { ...prev, messages };
            });
            break;

          case 'verification_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.verificationReport = event.data;
              lastMsg.loading.verification = false;
              return { ...prev, messages };
            });
            break;

          case 'post_judge_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.finalDecision = event.data;
              return { ...prev, messages };
            });
            break;

          case 'second_round_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.secondRound = true;
              lastMsg.secondRound = event.data;
              return { ...prev, messages };
            });
            break;

          case 'second_round_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.secondRound = false;
              if (event.data?.research_briefing) {
                lastMsg.secondRound = {
                  ...(lastMsg.secondRound || {}),
                  research_briefing: event.data.research_briefing,
                };
              }
              if (event.data?.final_decision) {
                lastMsg.finalDecision = event.data.final_decision;
              }
              return { ...prev, messages };
            });
            break;

          case 'stage3_start':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.loading.stage3 = true;
              return { ...prev, messages };
            });
            break;

          case 'stage3_complete':
            setCurrentConversation((prev) => {
              const messages = [...prev.messages];
              const lastMsg = messages[messages.length - 1];
              lastMsg.stage3 = event.data;
              lastMsg.loading.stage3 = false;
              return { ...prev, messages };
            });
            break;

          case 'title_complete':
            // Reload conversations to get updated title
            loadConversations();
            break;

          case 'complete':
            // Stream complete, reload conversations list
            if (event.data?.trace) {
              setCurrentConversation((prev) => {
                const messages = [...prev.messages];
                const lastMsg = messages[messages.length - 1];
                lastMsg.trace = event.data.trace;
                return { ...prev, messages };
              });
            }
            loadConversations();
            setIsLoading(false);
            break;

          case 'error':
            console.error('Stream error:', event.message);
            setIsLoading(false);
            break;

          default:
            console.log('Unknown event type:', eventType);
        }
      });
    } catch (error) {
      console.error('Failed to send message:', error);
      // Remove optimistic messages on error
      setCurrentConversation((prev) => ({
        ...prev,
        messages: prev.messages.slice(0, -2),
      }));
      setIsLoading(false);
    }
  };

  const downloadTextFile = (filename, content, contentType) => {
    const blob = new Blob([content], { type: contentType || 'text/plain' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const handleExportConversation = async (format) => {
    if (!currentConversationId) return;
    try {
      const exportPayload = await api.exportConversation(currentConversationId, format);
      downloadTextFile(exportPayload.filename, exportPayload.content, exportPayload.content_type);
      setResearchStatus(`Exported ${exportPayload.filename}`);
    } catch (error) {
      console.error('Failed to export conversation:', error);
      setResearchStatus('Export failed');
    }
  };

  const handleSaveResearchLog = async () => {
    if (!currentConversationId) return;
    try {
      const saved = await api.saveResearchLog(currentConversationId);
      await loadResearchLogs();
      setResearchStatus(`Saved ${saved.path}`);
    } catch (error) {
      console.error('Failed to save research log:', error);
      setResearchStatus('Save failed');
    }
  };

  const handleLoadResearchFile = async (file) => {
    if (!currentConversationId || !file) return;
    try {
      const content = await file.text();
      await api.setResearchContext(currentConversationId, file.name, content);
      await loadConversation(currentConversationId);
      setResearchStatus(`Loaded ${file.name} as context`);
    } catch (error) {
      console.error('Failed to load research file:', error);
      setResearchStatus('Load failed');
    }
  };

  const handleLoadSavedResearchLog = async (filename) => {
    if (!currentConversationId || !filename) return;
    try {
      await api.setResearchContextFromLog(currentConversationId, filename);
      await loadConversation(currentConversationId);
      setResearchStatus(`Loaded ${filename} as context`);
    } catch (error) {
      console.error('Failed to load saved research log:', error);
      setResearchStatus('Load failed');
    }
  };

  const handleClearResearchContext = async () => {
    if (!currentConversationId) return;
    try {
      await api.clearResearchContext(currentConversationId);
      await loadConversation(currentConversationId);
      setResearchStatus('Cleared research context');
    } catch (error) {
      console.error('Failed to clear research context:', error);
      setResearchStatus('Clear failed');
    }
  };

  return (
    <div className="app">
      <Sidebar
        conversations={conversations}
        currentConversationId={currentConversationId}
        onSelectConversation={handleSelectConversation}
        onNewConversation={handleNewConversation}
        availableModels={availableModels}
        currentConfig={currentConfig}
        onSaveConfig={handleSaveConfig}
        onRefreshModels={handleRefreshModels}
        modelCatalogMeta={modelCatalogMeta}
        configLoading={configLoading}
      />
      <ChatInterface
        conversation={currentConversation}
        onSendMessage={handleSendMessage}
        isLoading={isLoading}
        researchLogs={researchLogs}
        researchStatus={researchStatus}
        onExportConversation={handleExportConversation}
        onSaveResearchLog={handleSaveResearchLog}
        onLoadResearchFile={handleLoadResearchFile}
        onLoadSavedResearchLog={handleLoadSavedResearchLog}
        onClearResearchContext={handleClearResearchContext}
      />
    </div>
  );
}

export default App;
