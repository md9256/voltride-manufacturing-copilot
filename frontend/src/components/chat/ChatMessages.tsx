import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { ProposalCard } from '../ProposalCard'
import type { ToolChip, TranscriptItem } from './transcript'

const TOOL_LABELS: Record<string, string> = {
  search_products: 'Searched products',
  get_stock_levels: 'Checked stock levels',
  get_bom: 'Read bill of materials',
  get_bom_shortages: 'Ran shortage plan',
  get_manufacturing_order: 'Looked up manufacturing order',
  list_manufacturing_orders: 'Listed manufacturing orders',
  get_sales_summary: 'Summarised sales',
  draft_purchase_orders: 'Prepared purchase proposal',
}

function ToolChipView({ tool }: { tool: ToolChip }) {
  const icon = tool.status === 'running' ? '…' : tool.status === 'ok' ? '✓' : '!'
  const tone =
    tool.status === 'running'
      ? 'border-slate-200 bg-slate-50 text-slate-600'
      : tool.status === 'ok'
        ? 'border-teal-200 bg-teal-50 text-teal-800'
        : 'border-amber-200 bg-amber-50 text-amber-800'
  return (
    <details className={`group rounded-lg border text-xs ${tone}`}>
      <summary className="flex cursor-pointer list-none items-center gap-1.5 px-2 py-1">
        <span className={tool.status === 'running' ? 'animate-pulse' : ''} aria-hidden>
          {icon}
        </span>
        <span className="font-medium">{TOOL_LABELS[tool.name] ?? tool.name}</span>
        {tool.status === 'error' && tool.summary && <span className="truncate opacity-80">· {tool.summary}</span>}
        <span className="ml-auto opacity-50 group-open:rotate-90" aria-hidden>
          ›
        </span>
      </summary>
      <pre className="overflow-x-auto border-t border-current/10 px-2 py-1.5 font-mono text-[11px] whitespace-pre-wrap opacity-80">
        {tool.name}({JSON.stringify(tool.input, null, 1)})
      </pre>
    </details>
  )
}

export function ChatMessages({ items }: { items: TranscriptItem[] }) {
  return (
    <div className="space-y-4">
      {items.map((item, i) =>
        item.kind === 'user' ? (
          <div key={i} className="flex justify-end">
            <p className="max-w-[85%] rounded-2xl rounded-br-sm bg-teal-700 px-3.5 py-2 text-sm whitespace-pre-wrap text-white">
              {item.text}
            </p>
          </div>
        ) : (
          <div key={i} className="max-w-[95%] space-y-2">
            {item.tools.length > 0 && (
              <div className="space-y-1">
                {item.tools.map((t) => (
                  <ToolChipView key={t.id} tool={t} />
                ))}
              </div>
            )}
            {item.actions.map((a) => (
              <ProposalCard key={a.id} id={a.id} initial={a.initial} compact />
            ))}
            {item.text && (
              <div className="chat-markdown text-sm text-slate-800">
                <Markdown remarkPlugins={[remarkGfm]}>{item.text}</Markdown>
              </div>
            )}
            {item.streaming && !item.text && item.tools.every((t) => t.status !== 'running') && (
              <p className="text-sm text-slate-400" aria-live="polite">
                Thinking…
              </p>
            )}
            {item.error && (
              <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
                {item.error}
              </p>
            )}
          </div>
        ),
      )}
    </div>
  )
}
