import { useInfiniteQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ownedRequest } from '../api/client'
import { Card } from '../components/Card'

interface AuditEntry {
  id: number
  created_at: string
  conversation_id: string | null
  kind: 'tool_call' | 'action' | 'extraction'
  name: string
  question: string | null
  params: Record<string, unknown> | null
  result: Record<string, unknown> | null
  ok: boolean
  duration_ms: number | null
  provider: string | null
  model: string | null
}

const PAGE = 50
const KINDS = [
  ['', 'Everything'],
  ['tool_call', 'Tool calls'],
  ['action', 'Proposals & decisions'],
  ['extraction', 'Document extractions'],
] as const

export function AuditPage() {
  const [kind, setKind] = useState('')
  const query = useInfiniteQuery({
    queryKey: ['audit', kind],
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: String(PAGE) })
      if (kind) params.set('kind', kind)
      if (pageParam) params.set('before_id', String(pageParam))
      return ownedRequest<AuditEntry[]>(`/api/audit?${params}`)
    },
    initialPageParam: 0,
    getNextPageParam: (last) => (last.length === PAGE ? last[last.length - 1].id : undefined),
  })
  const rows = query.data?.pages.flat() ?? []

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Audit log</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Every AI tool call, every proposed write and its decision, and every document extraction. Append-only.
          Showing this browser's activity until sign-in arrives.
        </p>
      </div>
      <div className="flex flex-wrap gap-1">
        {KINDS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            onClick={() => setKind(value)}
            className={`rounded-lg px-3 py-1.5 text-sm ${kind === value ? 'bg-teal-50 font-medium text-teal-800' : 'text-slate-600 hover:bg-slate-100'}`}
          >
            {label}
          </button>
        ))}
      </div>
      <Card
        title={query.isPending ? 'Loading…' : `${rows.length}${query.hasNextPage ? '+' : ''} entries`} subtitle="Newest first; expand a row for parameters and result">
        {query.isPending ? (
          <div className="h-24 animate-pulse rounded bg-slate-50" />
        ) : query.isError ? (
          <p className="text-sm text-rose-600">Could not load: {query.error.message}</p>
        ) : rows.length === 0 ? (
          <p className="text-sm text-slate-500">Nothing yet. Ask the Copilot something or upload a quote.</p>
        ) : (
          <ul className="-mx-5 -my-2 divide-y divide-slate-100">
            {rows.map((e) => (
              <li key={e.id}>
                <details className="group px-5 py-2">
                  <summary className="flex cursor-pointer list-none flex-wrap items-baseline gap-x-3 gap-y-0.5 text-sm">
                    <span className="w-36 shrink-0 text-xs text-slate-400 tabular-nums">
                      {new Date(e.created_at).toLocaleString()}
                    </span>
                    <span className={`w-4 ${e.ok ? 'text-emerald-600' : 'text-rose-600'}`}>{e.ok ? '✓' : '✕'}</span>
                    <span className="font-medium text-slate-800">
                      {e.kind === 'action' ? `proposal ${e.name}` : e.name}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-slate-500">{e.question}</span>
                    {e.duration_ms != null && <span className="text-xs text-slate-400">{Math.round(e.duration_ms)} ms</span>}
                  </summary>
                  <div className="mt-2 grid gap-2 text-xs md:grid-cols-2">
                    <Json label="Parameters" value={e.params} />
                    <Json label="Result" value={e.result} />
                    {e.model && <p className="text-slate-500">Model: {e.provider} · {e.model}</p>}
                  </div>
                </details>
              </li>
            ))}
          </ul>
        )}
        {query.hasNextPage && (
          <button
            type="button"
            onClick={() => query.fetchNextPage()}
            disabled={query.isFetchingNextPage}
            className="mt-4 rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
          >
            {query.isFetchingNextPage ? 'Loading…' : 'Load older'}
          </button>
        )}
      </Card>
    </div>
  )
}

function Json({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="min-w-0">
      <p className="mb-0.5 font-medium text-slate-500">{label}</p>
      <pre className="max-h-64 overflow-auto rounded-md bg-slate-50 p-2 text-[11px] whitespace-pre-wrap text-slate-700">
        {value == null ? '—' : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}
