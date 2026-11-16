import { useId, useState } from 'react'
import {
  ArrowDownRight,
  AlertCircle,
  Box,
  FileCode2,
  GitBranch,
  LoaderCircle,
  Package,
  RotateCcw,
  Unlink,
} from 'lucide-react'
import type {
  DependencyEdge,
  DependencyGraphResponse,
} from '../../api/dependencies'

const NODE_WIDTH = 280
const NODE_HEIGHT = 42
const LEFT_X = 24
const RIGHT_X = 416
const ROW_GAP = 62
const VIEWBOX_WIDTH = 720

function nodePosition(index: number) {
  return {
    x: index % 2 === 0 ? LEFT_X : RIGHT_X,
    y: 30 + Math.floor(index / 2) * ROW_GAP,
  }
}

function edgePath(source: { x: number; y: number }, target: { x: number; y: number }) {
  const sourceCenterY = source.y + NODE_HEIGHT / 2
  const targetCenterY = target.y + NODE_HEIGHT / 2

  if (source.x === target.x) {
    const sideX = source.x + NODE_WIDTH + 36
    return `M ${source.x + NODE_WIDTH} ${sourceCenterY} C ${sideX} ${sourceCenterY}, ${sideX} ${targetCenterY}, ${target.x + NODE_WIDTH} ${targetCenterY}`
  }

  const sourceOnLeft = source.x < target.x
  const startX = sourceOnLeft ? source.x + NODE_WIDTH : source.x
  const endX = sourceOnLeft ? target.x : target.x + NODE_WIDTH
  const controlX = (startX + endX) / 2
  return `M ${startX} ${sourceCenterY} C ${controlX} ${sourceCenterY}, ${controlX} ${targetCenterY}, ${endX} ${targetCenterY}`
}

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string
  value: number
  icon: typeof Box
}) {
  return (
    <div className="dependency-stat">
      <Icon size={14} aria-hidden="true" />
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  )
}

function ImportList({
  title,
  type,
  edges,
  icon: Icon,
}: {
  title: string
  type: 'external' | 'unresolved'
  edges: DependencyEdge[]
  icon: typeof Package
}) {
  if (edges.length === 0) return null

  return (
    <section className={`dependency-import-list dependency-import-${type}`}>
      <h5>
        <Icon size={14} aria-hidden="true" />
        {title} ({edges.length.toLocaleString()})
      </h5>
      <ul>
        {edges.map((edge, index) => (
          <li key={`${edge.source}:${edge.dependency}:${index}`}>
            <code>{edge.dependency || 'Unknown import'}</code>
            <span>{edge.source}</span>
            {edge.line !== null && <span>Line {edge.line}</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}

function RepositoryDependencyGraph({
  graph,
  isLoading,
  error,
  onRetry,
}: {
  graph: DependencyGraphResponse | null
  isLoading: boolean
  error: string | null
  onRetry: () => void
}) {
  const markerId = `dependency-arrow-${useId().replace(/[^a-zA-Z0-9_-]/g, '')}`
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  if (isLoading) {
    return (
      <section className="analysis-result-section dependency-graph-section" aria-labelledby="dependency-graph-title">
        <div className="analysis-result-heading">
          <h4 id="dependency-graph-title">Dependency graph</h4>
        </div>
        <div className="dependency-graph-state" role="status" aria-live="polite">
          <LoaderCircle size={16} className="spin-icon" />
          Loading dependency graph…
        </div>
      </section>
    )
  }

  if (error || !graph) {
    return (
      <section className="analysis-result-section dependency-graph-section" aria-labelledby="dependency-graph-title">
        <div className="analysis-result-heading">
          <h4 id="dependency-graph-title">Dependency graph</h4>
        </div>
        <div className="dependency-graph-error" role="alert">
          <AlertCircle size={15} aria-hidden="true" />
          <span>{error ?? 'Dependency graph data is unavailable.'}</span>
          <button
            className="repository-button repository-button-quiet"
            type="button"
            onClick={onRetry}
          >
            <RotateCcw size={12} />
            Retry
          </button>
        </div>
      </section>
    )
  }

  const internalEdges = graph.edges.filter((edge) => edge.dependency_type === 'internal')
  const externalEdges = graph.edges.filter((edge) => edge.dependency_type === 'external')
  const unresolvedEdges = graph.edges.filter((edge) => edge.dependency_type === 'unresolved')
  const positions = new Map(
    graph.nodes.map((node, index) => [node.id, nodePosition(index)]),
  )
  const selectedNode = graph.nodes.find((node) => node.id === selectedNodeId) ?? null
  const graphHeight = Math.max(
    220,
    48 + Math.ceil(graph.nodes.length / 2) * ROW_GAP,
  )

  return (
    <section className="analysis-result-section dependency-graph-section" aria-labelledby="dependency-graph-title">
      <div className="analysis-result-heading">
        <h4 id="dependency-graph-title">Dependency graph</h4>
        <span>{graph.status}</span>
      </div>

      <div className="dependency-stats">
        <Stat label="Total files" value={graph.summary.total_files} icon={FileCode2} />
        <Stat label="Nodes" value={graph.summary.nodes} icon={Box} />
        <Stat label="Edges" value={graph.summary.edges} icon={ArrowDownRight} />
        <Stat label="Internal" value={graph.summary.internal_dependencies} icon={GitBranch} />
        <Stat label="External" value={graph.summary.external_dependencies} icon={Package} />
        <Stat label="Unresolved" value={graph.summary.unresolved_imports} icon={Unlink} />
      </div>

      {graph.unsupported_languages.length > 0 && (
        <div className="dependency-unsupported" role="status">
          Dependency details are unavailable for unsupported languages:{' '}
          {graph.unsupported_languages.join(', ')}.
        </div>
      )}

      {graph.nodes.length === 0 ? (
        <div className="dependency-graph-empty" role="status">
          No parsed source files were returned for this repository.
        </div>
      ) : (
        <>
          <div className="dependency-legend" aria-label="Graph legend">
            <span><i className="dependency-legend-dot dependency-dot-internal" />Internal dependency</span>
            <span><i className="dependency-legend-dot dependency-dot-external" />External import</span>
            <span><i className="dependency-legend-dot dependency-dot-unresolved" />Unresolved import</span>
          </div>

          <div className="dependency-graph-viewport">
            <svg
              className="dependency-graph-svg"
              width={VIEWBOX_WIDTH}
              height={graphHeight}
              viewBox={`0 0 ${VIEWBOX_WIDTH} ${graphHeight}`}
              role="group"
              aria-label="Interactive file dependency graph"
            >
              <defs>
                <marker
                  id={markerId}
                  markerWidth="7"
                  markerHeight="7"
                  refX="6"
                  refY="3.5"
                  orient="auto"
                  markerUnits="strokeWidth"
                >
                  <path d="M 0 0 L 7 3.5 L 0 7 z" />
                </marker>
              </defs>
              <g className="dependency-graph-edges" aria-hidden="true">
                {internalEdges.map((edge, index) => {
                  const source = positions.get(edge.source)
                  const target = edge.target ? positions.get(edge.target) : undefined
                  if (!source || !target) return null
                  return (
                    <path
                      key={`${edge.source}:${edge.target}:${index}`}
                      d={edgePath(source, target)}
                      markerEnd={`url(#${markerId})`}
                    />
                  )
                })}
              </g>
              <g className="dependency-graph-nodes">
                {graph.nodes.map((node, index) => {
                  const position = nodePosition(index)
                  const isSelected = selectedNodeId === node.id
                  return (
                    <g
                      key={node.id}
                      className={`dependency-graph-node${isSelected ? ' is-selected' : ''}`}
                      transform={`translate(${position.x} ${position.y})`}
                      role="button"
                      tabIndex={0}
                      aria-label={`${node.file_path}, ${node.language}, ${node.status}`}
                      aria-pressed={isSelected}
                      onClick={() => setSelectedNodeId(node.id)}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          setSelectedNodeId(node.id)
                        }
                      }}
                    >
                      <title>{node.file_path}</title>
                      <rect width={NODE_WIDTH} height={NODE_HEIGHT} rx="7" />
                      <text className="dependency-node-path" x="11" y="17">
                        {node.file_path.length > 38
                          ? `${node.file_path.slice(0, 35)}…`
                          : node.file_path}
                      </text>
                      <text className="dependency-node-language" x="11" y="32">
                        {node.language}
                      </text>
                    </g>
                  )
                })}
              </g>
            </svg>
          </div>

          <div className="dependency-selected-node" aria-live="polite">
            {selectedNode ? (
              <>
                <strong>Selected file</strong>
                <code>{selectedNode.file_path}</code>
                <span>{selectedNode.language} · {selectedNode.status}</span>
              </>
            ) : (
              <span>Select a file node to inspect its path and language.</span>
            )}
          </div>
        </>
      )}

      <div className="dependency-other-imports">
        <ImportList
          title="External dependencies"
          type="external"
          edges={externalEdges}
          icon={Package}
        />
        <ImportList
          title="Unresolved imports"
          type="unresolved"
          edges={unresolvedEdges}
          icon={Unlink}
        />
        {externalEdges.length === 0 && unresolvedEdges.length === 0 && (
          <p className="analysis-empty-detail">
            No external or unresolved imports were returned.
          </p>
        )}
      </div>

      {internalEdges.length > 0 && graph.nodes.length > 0 && (
        <p className="dependency-graph-note">
          Arrows show internal imports; graph statistics include all returned dependency types.
        </p>
      )}
    </section>
  )
}

export default RepositoryDependencyGraph
