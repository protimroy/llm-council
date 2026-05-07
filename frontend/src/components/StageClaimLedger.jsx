import './StageClaimLedger.css';

function addToMapList(map, key, value) {
  if (!key) return;
  const current = map.get(key) || [];
  current.push(value);
  map.set(key, current);
}

function buildClaimRows(stage1, critiqueReport, verificationReport, finalDecision) {
  const agreementByClaim = new Map();
  const disagreementByClaim = new Map();
  const hypothesisByClaim = new Map();
  const minorityClaimIds = new Set();
  const verificationByClaim = new Map();

  (critiqueReport?.agreements || []).forEach((agreement) => {
    (agreement.supporting_claim_ids || []).forEach((claimId) => {
      addToMapList(agreementByClaim, claimId, agreement);
    });
  });

  (critiqueReport?.disagreements || []).forEach((disagreement) => {
    (disagreement.claim_ids || []).forEach((claimId) => {
      addToMapList(disagreementByClaim, claimId, disagreement);
    });
  });

  (critiqueReport?.top_hypotheses || []).forEach((hypothesis) => {
    addToMapList(hypothesisByClaim, hypothesis.claim_id, hypothesis);
  });

  (critiqueReport?.minority_alerts || []).forEach((alert) => {
    if (alert.claim_id) minorityClaimIds.add(alert.claim_id);
  });

  (finalDecision?.minority_alerts || []).forEach((claimId) => {
    if (claimId) minorityClaimIds.add(claimId);
  });

  (verificationReport?.results || []).forEach((result) => {
    if (result.source_claim_id) verificationByClaim.set(result.source_claim_id, result);
  });

  const resolved = new Set(finalDecision?.resolved_claims || []);
  const rejected = new Set(finalDecision?.rejected_claims || []);
  const unresolved = new Set(finalDecision?.unresolved_claims || []);

  return (stage1 || []).flatMap((response, responseIndex) => {
    const claims = response.evidence_packet?.claims || [];
    return claims.map((claim, claimIndex) => {
      const claimId = claim.claim_id || `${responseIndex}-${claimIndex}`;
      const verification = verificationByClaim.get(claimId);
      const agreements = agreementByClaim.get(claimId) || [];
      const disagreements = disagreementByClaim.get(claimId) || [];
      const hypotheses = hypothesisByClaim.get(claimId) || [];

      let disposition = 'candidate';
      if (rejected.has(claimId)) disposition = 'rejected';
      else if (resolved.has(claimId)) disposition = 'accepted';
      else if (unresolved.has(claimId)) disposition = 'unresolved';
      else if (minorityClaimIds.has(claimId)) disposition = 'minority';
      else if (verification?.status === 'passed') disposition = 'verified';
      else if (verification?.status === 'failed') disposition = 'rejected';

      const critiqueLabels = [];
      if (agreements.length > 0) critiqueLabels.push('agreement');
      if (disagreements.length > 0) {
        const severities = [...new Set(disagreements.map((item) => item.disagreement_severity || 'medium'))];
        critiqueLabels.push(`disagreement (${severities.join(', ')})`);
      }
      if (hypotheses.length > 0) critiqueLabels.push('top hypothesis');
      if (minorityClaimIds.has(claimId)) critiqueLabels.push('minority');

      return {
        id: claimId,
        text: claim.claim_text || '',
        sourceModel: response.model || 'unknown',
        round: response.is_follow_up ? 'Follow-up' : 'Initial',
        claimType: claim.claim_type || 'factual',
        evidenceType: claim.evidence_type || 'none',
        confidence: typeof claim.confidence === 'number' ? Math.round(claim.confidence * 100) : null,
        risk: claim.risk_if_wrong || 'medium',
        isTestable: Boolean(claim.test_logic || claim.falsifiable_hypothesis),
        critique: critiqueLabels.length > 0 ? critiqueLabels.join(' | ') : 'not flagged',
        verificationStatus: verification?.status || 'not run',
        verificationSummary: verification?.summary || '',
        disposition,
      };
    });
  });
}

function shortModelName(model) {
  return model?.split('/')[1] || model || 'unknown';
}

function classToken(value) {
  return String(value || 'unknown').replace(/\s+/g, '_');
}

export default function StageClaimLedger({ stage1, critiqueReport, verificationReport, finalDecision }) {
  const rows = buildClaimRows(stage1, critiqueReport, verificationReport, finalDecision);
  if (rows.length === 0) return null;

  const acceptedCount = rows.filter((row) => ['accepted', 'verified'].includes(row.disposition)).length;
  const rejectedCount = rows.filter((row) => row.disposition === 'rejected').length;
  const unresolvedCount = rows.filter((row) => row.disposition === 'unresolved').length;
  const testedCount = rows.filter((row) => row.verificationStatus !== 'not run').length;

  return (
    <div className="stage claim-ledger">
      <div className="claim-ledger-header">
        <h3 className="stage-title">Claim Ledger</h3>
        <div className="claim-ledger-stats">
          <span>{rows.length} claims</span>
          <span>{acceptedCount} accepted</span>
          <span>{rejectedCount} rejected</span>
          <span>{unresolvedCount} unresolved</span>
          <span>{testedCount} tested</span>
        </div>
      </div>

      <div className="claim-ledger-table-wrap">
        <table className="claim-ledger-table">
          <thead>
            <tr>
              <th>Claim</th>
              <th>Source</th>
              <th>Evidence</th>
              <th>Critique</th>
              <th>Verification</th>
              <th>Final</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.id}-${row.sourceModel}-${row.round}`}>
                <td className="claim-text-cell">
                  <div className="claim-id">{row.id}</div>
                  <div className="claim-text">{row.text}</div>
                  <div className="claim-meta-inline">
                    <span>{row.claimType}</span>
                    <span>risk: {row.risk}</span>
                    {row.isTestable && <span>testable</span>}
                  </div>
                </td>
                <td>
                  <div className="claim-source-model">{shortModelName(row.sourceModel)}</div>
                  <div className="claim-round">{row.round}</div>
                </td>
                <td>
                  <span className={`claim-pill evidence-${row.evidenceType}`}>{row.evidenceType}</span>
                  {row.confidence !== null && <div className="claim-confidence">{row.confidence}%</div>}
                </td>
                <td>{row.critique}</td>
                <td>
                  <span className={`claim-pill verification-${classToken(row.verificationStatus)}`}>
                    {row.verificationStatus}
                  </span>
                  {row.verificationSummary && <div className="claim-verification-summary">{row.verificationSummary}</div>}
                </td>
                <td>
                  <span className={`claim-pill disposition-${row.disposition}`}>{row.disposition}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}