import PreText from './PreText';
import './ReasoningTrace.css';

function hasUsage(usage) {
  return usage && Object.values(usage).some((value) => value !== null && value !== undefined);
}

export default function ReasoningTrace({ item, compact = false }) {
  if (!item) return null;

  const hasReasoning = Boolean(item.reasoning || item.reasoning_details);
  const usageAvailable = hasUsage(item.usage);

  if (!hasReasoning && !usageAvailable) return null;

  return (
    <details className={`reasoning-trace ${compact ? 'compact' : ''}`}>
      <summary>
        <span>Reasoning Trace</span>
        {usageAvailable && (
          <span className="reasoning-usage">
            {item.usage.total_tokens ? `${item.usage.total_tokens} tokens` : 'usage'}
          </span>
        )}
      </summary>
      <div className="reasoning-trace-body">
        <div className="reasoning-meta-grid">
          {item.usage?.prompt_tokens !== undefined && <span>Prompt {item.usage.prompt_tokens}</span>}
          {item.usage?.completion_tokens !== undefined && <span>Completion {item.usage.completion_tokens}</span>}
          {item.usage?.total_tokens !== undefined && <span>Total {item.usage.total_tokens}</span>}
        </div>
        <PreText title="Reasoning" value={item.reasoning} />
        <PreText title="Reasoning Details" value={item.reasoning_details} language="json" />
      </div>
    </details>
  );
}
