import './StageVerification.css';

/**
 * Displays verification results for claims that were tested.
 *
 * Props:
 *   verificationReport — VerificationReport dict (from verification_complete event)
 */
export default function StageVerification({ verificationReport }) {
  if (!verificationReport || !verificationReport.results || verificationReport.results.length === 0) {
    return null;
  }

  const statusLabels = {
    passed: 'Passed',
    failed: 'Failed',
    timeout: 'Timeout',
    skipped: 'Skipped',
    not_testable: 'Not Testable',
    error: 'Error',
  };

  return (
    <div className="stage-verification">
      <div className="verification-header">
        <h4>Claim Verification</h4>
      </div>

      {verificationReport.summary && (
        <div className="verification-summary">{verificationReport.summary}</div>
      )}

      <div className="verification-results">
        {verificationReport.results.map((result, index) => (
          <div key={result.target_id || index} className="verification-result">
            <span className={`result-status ${result.status}`}>
              {statusLabels[result.status] || result.status}
            </span>
            <div className="result-details">
              <div className="result-claim">
                Claim: {result.source_claim_id || result.target_id}
              </div>
              {result.summary && (
                <div className="result-summary">{result.summary}</div>
              )}
              {result.execution_time_ms > 0 && (
                <div className="result-meta">
                  Executed in {result.execution_time_ms}ms
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="verification-stats">
        {verificationReport.passed_count > 0 && (
          <div className="verification-stat">
            Passed: <span className="count">{verificationReport.passed_count}</span>
          </div>
        )}
        {verificationReport.failed_count > 0 && (
          <div className="verification-stat">
            Failed: <span className="count">{verificationReport.failed_count}</span>
          </div>
        )}
        {verificationReport.not_testable_count > 0 && (
          <div className="verification-stat">
            Not testable: <span className="count">{verificationReport.not_testable_count}</span>
          </div>
        )}
        {verificationReport.timeout_count > 0 && (
          <div className="verification-stat">
            Timed out: <span className="count">{verificationReport.timeout_count}</span>
          </div>
        )}
        {verificationReport.error_count > 0 && (
          <div className="verification-stat">
            Errors: <span className="count">{verificationReport.error_count}</span>
          </div>
        )}
      </div>
    </div>
  );
}
