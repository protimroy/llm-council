import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import Stage1 from './Stage1';
import Stage2 from './Stage2';
import Stage3 from './Stage3';
import StageJudge from './StageJudge';
import StageVerification from './StageVerification';
import StageCritique from './StageCritique';
import './ChatInterface.css';

export default function ChatInterface({
  conversation,
  onSendMessage,
  isLoading,
}) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [conversation]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (input.trim() && !isLoading) {
      onSendMessage(input);
      setInput('');
    }
  };

  const handleKeyDown = (e) => {
    // Submit on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  if (!conversation) {
    return (
      <div className="chat-interface">
        <div className="empty-state">
          <h2>Welcome to LLM Council</h2>
          <p>Create a new conversation to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="chat-interface">
      <div className="messages-container">
        {conversation.messages.length === 0 ? (
          <div className="empty-state">
            <h2>Start a conversation</h2>
            <p>Ask a question to consult the LLM Council</p>
          </div>
        ) : (
          conversation.messages.map((msg, index) => (
            <div key={index} className="message-group">
              {msg.role === 'user' ? (
                <div className="user-message">
                  <div className="message-label">You</div>
                  <div className="message-content">
                    <div className="markdown-content">
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="assistant-message">
                  <div className="message-label">LLM Council</div>

                  {/* Stage 1 */}
                  {msg.loading?.stage1 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 1: Collecting individual responses...</span>
                    </div>
                  )}
                  {msg.stage1 && <Stage1 responses={msg.stage1} />}

                  {/* Stage 2 */}
                  {msg.loading?.stage2 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 2: Peer rankings...</span>
                    </div>
                  )}
                  {msg.stage2 && (
                    <Stage2
                      rankings={msg.stage2}
                      labelToModel={msg.metadata?.label_to_model}
                      aggregateRankings={msg.metadata?.aggregate_rankings}
                    />
                  )}

                  {/* Structured Critique Analysis */}
                  {msg.critiqueReport && (
                    <StageCritique critiqueReport={msg.critiqueReport} />
                  )}

                  {/* Fast Judge Triage */}
                  {msg.loading?.fastJudge && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Fast Judge triage...</span>
                    </div>
                  )}
                  {msg.judgeDecision && !msg.finalDecision && (
                    <StageJudge judgeDecision={msg.judgeDecision} />
                  )}

                  {/* Verification */}
                  {msg.loading?.verification && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running claim verification...</span>
                    </div>
                  )}
                  {msg.verificationReport && (
                    <StageVerification verificationReport={msg.verificationReport} />
                  )}

                  {/* Post-Verification Judge */}
                  {msg.finalDecision && (
                    <StageJudge finalDecision={msg.finalDecision} />
                  )}

                  {/* Second Round Indicator */}
                  {msg.loading?.secondRound && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running second round of consultation...</span>
                    </div>
                  )}
                  {msg.secondRound && !msg.loading?.secondRound && (
                    <div className="stage-judge decision-second_round">
                      <div className="judge-header">
                        <h4>Second Round</h4>
                        <span className="judge-badge second-round">Round {msg.secondRound.round || 1}</span>
                      </div>
                      {msg.secondRound.rationale && (
                        <div className="judge-rationale">{msg.secondRound.rationale}</div>
                      )}
                    </div>
                  )}

                  {/* Stage 3 */}
                  {msg.loading?.stage3 && (
                    <div className="stage-loading">
                      <div className="spinner"></div>
                      <span>Running Stage 3: Final synthesis...</span>
                    </div>
                  )}
                  {msg.stage3 && <Stage3 finalResponse={msg.stage3} />}
                </div>
              )}
            </div>
          ))
        )}

        {isLoading && (
          <div className="loading-indicator">
            <div className="spinner"></div>
            <span>Consulting the council...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {conversation.messages.length === 0 && (
        <form className="input-form" onSubmit={handleSubmit}>
          <textarea
            className="message-input"
            placeholder="Ask your question... (Shift+Enter for new line, Enter to send)"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
            rows={3}
          />
          <button
            type="submit"
            className="send-button"
            disabled={!input.trim() || isLoading}
          >
            Send
          </button>
        </form>
      )}
    </div>
  );
}
