import './StageCritique.css';

/**
 * Displays the structured critique report: agreements, disagreements,
 * load-bearing points, and minority alerts.
 *
 * Props:
 *   critiqueReport — CritiqueReport dict (from metadata)
 */
export default function StageCritique({ critiqueReport }) {
  if (!critiqueReport) return null;

  const hasAgreements = critiqueReport.agreements && critiqueReport.agreements.length > 0;
  const hasDisagreements = critiqueReport.disagreements && critiqueReport.disagreements.length > 0;
  const hasLoadBearing = critiqueReport.candidate_load_bearing_points && critiqueReport.candidate_load_bearing_points.length > 0;
  const hasMinorityAlerts = critiqueReport.minority_alerts && critiqueReport.minority_alerts.length > 0;

  if (!hasAgreements && !hasDisagreements && !hasLoadBearing && !hasMinorityAlerts) {
    return null;
  }

  return (
    <div className="stage-critique">
      <div className="critique-header">
        <h4>Structured Critique Analysis</h4>
      </div>

      {/* Agreements */}
      {hasAgreements && (
        <div className="critique-section">
          <h5>Agreements ({critiqueReport.agreements.length})</h5>
          {critiqueReport.agreements.map((a, i) => (
            <div key={a.agreement_id || i} className="critique-item severity-low">
              {a.shared_claim_summary}
              <span className="confidence">{(a.aggregate_confidence * 100).toFixed(0)}% confidence</span>
            </div>
          ))}
        </div>
      )}

      {/* Disagreements */}
      {hasDisagreements && (
        <div className="critique-section">
          <h5>Disagreements ({critiqueReport.disagreements.length})</h5>
          {critiqueReport.disagreements.map((d, i) => (
            <div key={d.disagreement_id || i} className={`critique-item severity-${d.disagreement_severity}`}>
              <span className={`severity-badge ${d.disagreement_severity}`}>
                {d.disagreement_severity}
              </span>
              <span className={`impact-badge ${d.decision_impact}`}>
                {d.decision_impact} impact
              </span>
              {d.description}
              {d.evidence_strength_summary && (
                <span className="confidence"> — evidence: {d.evidence_strength_summary}</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Load-bearing points */}
      {hasLoadBearing && (
        <div className="critique-section">
          <h5>Load-Bearing Points ({critiqueReport.candidate_load_bearing_points.length})</h5>
          {critiqueReport.candidate_load_bearing_points.map((lb, i) => (
            <div key={lb.disagreement_id || i} className="critique-item severity-high">
              {lb.reason || `Disagreement ${lb.disagreement_id}`}
              {lb.would_change_recommendation && (
                <span className="confidence"> — would change recommendation</span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Minority alerts */}
      {hasMinorityAlerts && (
        <div className="critique-section">
          <h5>Minority Alerts ({critiqueReport.minority_alerts.length})</h5>
          {critiqueReport.minority_alerts.map((m, i) => (
            <div key={m.alert_id || i} className="critique-item minority-alert">
              <div className="why-outlier">{m.why_outlier}</div>
              {m.why_might_matter && (
                <div className="why-matter">May matter: {m.why_might_matter}</div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
