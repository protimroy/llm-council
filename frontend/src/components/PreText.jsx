import { useState } from 'react';
import './PreText.css';

function stringifyValue(value) {
  if (value === null || value === undefined || value === '') return '';
  if (typeof value === 'string') return value;
  return JSON.stringify(value, null, 2);
}

export default function PreText({ title, value, language = 'text' }) {
  const [copied, setCopied] = useState(false);
  const content = stringifyValue(value);

  if (!content) return null;

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1400);
  };

  return (
    <div className="pretext-block">
      <div className="pretext-header">
        <span>{title}</span>
        <button className="pretext-copy" type="button" onClick={handleCopy}>
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className={`pretext-body language-${language}`}>
        <code>{content}</code>
      </pre>
    </div>
  );
}
