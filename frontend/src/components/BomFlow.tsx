import { Graph, layout } from '@dagrejs/dagre'
import { Background, Controls, Handle, Position, ReactFlow, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { useMemo, useState } from 'react'
import type { BomTreeNode, NodeStatus } from '../api/types'
import { formatMoney, formatQty } from './format'
import { NodeStatusBadge } from './StateBadge'

const NODE_WIDTH = 236
const NODE_HEIGHT = 92

const STATUS_BORDER: Record<NodeStatus, string> = {
  ok: 'border-l-emerald-500',
  build: 'border-l-sky-500',
  incoming: 'border-l-amber-400',
  short: 'border-l-rose-500',
}
const EDGE_COLOR: Record<NodeStatus, string> = {
  ok: '#cbd5e1',
  build: '#7dd3fc',
  incoming: '#fbbf24',
  short: '#f43f5e',
}

type BomNodeData = {
  node: BomTreeNode
  currency: string | undefined
  isRoot: boolean
  expanded: boolean
  onToggle: (id: string) => void
}
type BomFlowNode = Node<BomNodeData, 'bom'>

function BomNodeCard({ id, data }: NodeProps<BomFlowNode>) {
  const { node, currency, isRoot, expanded, onToggle } = data
  const hasChildren = node.children.length > 0
  return (
    <div
      className={`relative rounded-lg border border-l-4 border-slate-200 bg-white px-3 py-2 text-xs shadow-sm ${STATUS_BORDER[node.status]}`}
      style={{ width: NODE_WIDTH, height: NODE_HEIGHT }}
    >
      {!isRoot && <Handle type="target" position={Position.Left} className="!bg-slate-300" />}
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-semibold text-slate-800" title={node.name}>
            {node.name}
          </p>
          <p className="text-slate-400">
            {node.code} · {node.kind}
          </p>
        </div>
        <NodeStatusBadge status={node.status} />
      </div>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-2 text-slate-600">
        <dt className="text-slate-400">{isRoot ? 'Build' : 'Needed'}</dt>
        <dd className="text-right tabular-nums">
          {formatQty(node.quantity)}
          {!isRoot && <span className="text-slate-400"> ({formatQty(node.qty_per_unit)}/unit)</span>}
        </dd>
        <dt className="text-slate-400">Free / on hand</dt>
        <dd className="text-right tabular-nums">
          {formatQty(node.free_qty)} / {formatQty(node.on_hand)}
          <span className="text-slate-400"> · {formatMoney(node.unit_cost, currency)}</span>
        </dd>
      </dl>
      {hasChildren && (
        <>
          <Handle type="source" position={Position.Right} className="!bg-slate-300" />
          <button
            type="button"
            // nodrag/nopan: let the click reach the button instead of React Flow.
            className="nodrag nopan absolute top-1/2 -right-3 h-6 min-w-6 -translate-y-1/2 rounded-full border border-slate-300 bg-white px-1.5 text-[11px] font-semibold text-slate-600 shadow-sm hover:bg-slate-50"
            onClick={() => onToggle(id)}
            aria-expanded={expanded}
            aria-label={`${expanded ? 'Collapse' : 'Expand'} ${node.name}`}
          >
            {expanded ? '−' : `+${node.children.length}`}
          </button>
        </>
      )}
    </div>
  )
}

const nodeTypes = { bom: BomNodeCard }

// A component can appear in several branches, so node ids are tree paths ("0.2.1"), not product ids.
const childId = (parentId: string, index: number) => `${parentId}.${index}`

/** Root, plus every node on a path to a shortage: problems are visible on first load. */
function defaultExpanded(tree: BomTreeNode): Set<string> {
  const expanded = new Set<string>(['0'])
  const visit = (node: BomTreeNode, id: string): boolean => {
    let shortBelow = false
    node.children.forEach((child, i) => {
      if (visit(child, childId(id, i)) || child.status === 'short') shortBelow = true
    })
    if (shortBelow) expanded.add(id)
    return shortBelow
  }
  visit(tree, '0')
  return expanded
}

function allIds(tree: BomTreeNode): Set<string> {
  const ids = new Set<string>()
  const visit = (node: BomTreeNode, id: string) => {
    if (node.children.length) ids.add(id)
    node.children.forEach((child, i) => visit(child, childId(id, i)))
  }
  visit(tree, '0')
  return ids
}

/** Visible nodes/edges, laid out left-to-right with dagre. */
function toFlow(
  tree: BomTreeNode,
  currency: string | undefined,
  expanded: Set<string>,
  onToggle: (id: string) => void,
): { nodes: BomFlowNode[]; edges: Edge[] } {
  const graph = new Graph()
  graph.setGraph({ rankdir: 'LR', nodesep: 12, ranksep: 64 })
  graph.setDefaultEdgeLabel(() => ({}))

  const nodes: BomFlowNode[] = []
  const edges: Edge[] = []
  const walk = (node: BomTreeNode, id: string, parentId: string | null) => {
    const isExpanded = expanded.has(id)
    graph.setNode(id, { width: NODE_WIDTH, height: NODE_HEIGHT })
    nodes.push({
      id,
      type: 'bom',
      position: { x: 0, y: 0 },
      data: { node, currency, isRoot: parentId === null, expanded: isExpanded, onToggle },
    })
    if (parentId) {
      graph.setEdge(parentId, id)
      edges.push({
        id: `${parentId}->${id}`,
        source: parentId,
        target: id,
        style: { stroke: EDGE_COLOR[node.status], strokeWidth: node.status === 'short' ? 2 : 1.5 },
      })
    }
    if (isExpanded) node.children.forEach((child, i) => walk(child, childId(id, i), id))
  }
  walk(tree, '0', null)
  layout(graph)

  for (const n of nodes) {
    const { x, y } = graph.node(n.id)
    n.position = { x: x - NODE_WIDTH / 2, y: y - NODE_HEIGHT / 2 } // dagre gives centres
  }
  return { nodes, edges }
}

/** Expects a `key` that changes with the product, so expansion state resets per product. */
export function BomFlow({ tree, currency }: { tree: BomTreeNode; currency: string | undefined }) {
  const [expanded, setExpanded] = useState(() => defaultExpanded(tree))
  const { nodes, edges } = useMemo(() => {
    const toggle = (id: string) =>
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
    return toFlow(tree, currency, expanded, toggle)
  }, [tree, currency, expanded])

  return (
    <div className="relative h-full">
      <div className="absolute top-2 right-2 z-10 flex gap-1">
        <ToolbarButton onClick={() => setExpanded(defaultExpanded(tree))}>Show problems</ToolbarButton>
        <ToolbarButton onClick={() => setExpanded(allIds(tree))}>Expand all</ToolbarButton>
        <ToolbarButton onClick={() => setExpanded(new Set(['0']))}>Collapse</ToolbarButton>
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        // Never shrink below a readable size; a tall tree scrolls instead.
        fitViewOptions={{ padding: 0.08, minZoom: 0.75, maxZoom: 1 }}
        minZoom={0.3}
        panOnScroll
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
      >
        <Background gap={20} color="#e2e8f0" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  )
}

function ToolbarButton({ onClick, children }: { onClick: () => void; children: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-600 shadow-sm hover:bg-slate-50"
    >
      {children}
    </button>
  )
}
