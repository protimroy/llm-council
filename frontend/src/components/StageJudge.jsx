import './StageJudge.css';

/**
 * Displays the Fast Judge triage decision and/or the
 * Post-Verification Judge final decision.
 *
 * Props:
 *   judgeDecision — FastJudgeDecision dict (from fast_judge_complete event)
 *   finalDecision — FinalDecision dict (from post_judge_complete event)
 */
export default function StageJudge({ judgeDecision, finalDecision }) {
  // Show the most relevant decision
  const decision = finalDecision || judgeDecision;
  if (!decision) return null;

  const decisionType = decision.decision || 'synthesize_now';
  const isFinal = !!finalDecision;

  // Map decision values to display labels and CSS classes
  const decisionConfig = {
    synthesize_now: { label: 'Synthesize', badge: 'synthesize' },
    synthesize: { label: 'Synthesize', badge: 'synthesize' },
    escalate_for_verification: { label: 'Verify Claims', badge: 'verification' },
    request_second_round: { label: 'Second Round', badge: 'second-round' },
    second_round: { label: 'Second Round', badge: 'second-round' },
    unresolved: { label: 'Unresolved', badge: 'unresolved' },
  };

  const config = decisionConfig[decisionType] || decisionConfig.synthesize_now;

  return (
    <div className={`stage-judge decision-${decisionType}`}>
      <div className="judge-header">
        <h4>{isFinal ? 'Post-Verification Judge' : 'Fast Judge Triage'}</h4>
        <span className={`judge-badge ${config.badge}`}>
          {config.label}
        </span>
      </div>

      {decision.rationale && (
        <div className="judge-rationale">{decision.rationale}</div>
      )}

      {decision.confidence && (
        <div className="judge-confidence">
          Confidence: <strong>{decision.confidence}</strong>
        </div>
      )}

      {/* Show claim classification stats for final decisions */}
      {isFinal && finalDecision && (
        <div className="judge-stats">
          {finalDecision.resolved_claims && finalDecision.resolved_claims.length > 0 && (
            <div className="judge-stat resolved">
              Resolved: <span className="count">{finalDecision.resolved_claims.length}</span>
            </div>
          )}
          {finalDecision.rejected_claims && finalDecision.rejected_claims.length > 0 && (
            <div className="judge-stat rejected">
              Rejected: <span className="count">{finalDecision.rejected_claims.length}</span>
            </div>
          )}
          {finalDecision.unresolved_claims && finalDecision.unresolved_claims.length > 0 && (
            <div className="judge-stat unresolved">
              Unresolved: <span className="count">{finalDecision.unresolved_claims.length}</span>
            </div>
          )}
        </div>
      )}

      {/* Show prioritized issues for fast judge */}
      {!isFinal && judgeDecision && judgeDecision.prioritized_issues && (
        <div className="judge-stats">
          <div className="judge-stat">
            Issues: <span className="count">{judgeDecision.prioritized_issues.length}</span>
          </div>
          {judgeDecision.minority_alerts_to_preserve && (
            <div className="judge-stat">
              Minority alerts: <span className="count">{judgeDecision.minority_alerts_to_preserve.length}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
