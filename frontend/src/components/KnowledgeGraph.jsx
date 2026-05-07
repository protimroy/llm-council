import { useMemo, useState } from 'react';
import './KnowledgeGraph.css';

const TYPE_LABELS = {
  document: 'Document',
  tag: 'Tag',
  missing: 'Missing note',
};

function shortLabel(value, length = 28) {
  if (!value) return 'Untitled';
  return value.length > length ? `${value.slice(0, length - 1)}...` : value;
}

export default function KnowledgeGraph({ graph, activeSessionId }) {
  const [selectedId, setSelectedId] = useState(null);
  const layout = useMemo(() => {
    const nodes = graph?.nodes || [];
    const edges = graph?.edges || [];
    const width = 760;
    const height = 340;
    const centerX = width / 2;
    const centerY = height / 2;
    const radius = Math.min(width, height) * 0.37;
    const positioned = nodes.map((node, index) => {
      const angle = nodes.length ? (Math.PI * 2 * index) / nodes.length - Math.PI / 2 : 0;
      const nodeRadius = node.type === 'document' ? 12 : node.type === 'tag' ? 9 : 8;
      return {
        ...node,
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
        r: nodeRadius,
      };
    });
    const byId = Object.fromEntries(positioned.map((node) => [node.id, node]));
    return { width, height, nodes: positioned, edges, byId };
  }, [graph]);

  const selectedNode = selectedId ? layout.byId[selectedId] : null;
  const visibleEdges = layout.edges.filter((edge) => layout.byId[edge.source] && layout.byId[edge.target]);

  if (!graph || !layout.nodes.length) {
    return (
      <div className="knowledge-graph empty">
        <div className="graph-empty-title">No Research Graph Yet</div>
        <div className="graph-empty-body">Create a session or save a research log.</div>
      </div>
    );
  }

  return (
    <div className="knowledge-graph">
      <div className="graph-header-row">
        <div>
          <div className="graph-title">Knowledge Graph</div>
          <div className="graph-meta">
            {graph.document_count || 0} docs · {graph.tag_count || 0} tags · {visibleEdges.length} links
          </div>
        </div>
        <div className="graph-mode">Markdown graph</div>
      </div>

      <div className="graph-stage">
        <svg viewBox={`0 0 ${layout.width} ${layout.height}`} role="img" aria-label="Research knowledge graph">
          <g>
            {visibleEdges.map((edge) => {
              const source = layout.byId[edge.source];
              const target = layout.byId[edge.target];
              return (
                <line
                  key={`${edge.source}-${edge.target}-${edge.type}`}
                  className={`graph-edge edge-${edge.type}`}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                />
              );
            })}
          </g>
          <g>
            {layout.nodes.map((node) => {
              const isActive = node.session_id && node.session_id === activeSessionId;
              const isSelected = selectedId === node.id;
              return (
                <g
                  key={node.id}
                  className={`graph-node node-${node.type}${isActive ? ' active-session' : ''}${isSelected ? ' selected' : ''}`}
                  onClick={() => setSelectedId(node.id)}
                >
                  <circle cx={node.x} cy={node.y} r={node.r} />
                  <text x={node.x} y={node.y + node.r + 13} textAnchor="middle">
                    {shortLabel(node.label, 18)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      <div className="graph-detail-row">
        {selectedNode ? (
          <>
            <span className={`graph-type type-${selectedNode.type}`}>{TYPE_LABELS[selectedNode.type] || selectedNode.type}</span>
            <span className="graph-node-title">{selectedNode.label}</span>
            {selectedNode.path && <span className="graph-node-path">{selectedNode.path}</span>}
          </>
        ) : (
          <span className="graph-node-path">Select a node</span>
        )}
      </div>
    </div>
  );
}