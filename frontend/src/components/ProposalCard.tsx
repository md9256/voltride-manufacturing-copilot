import { useAction, useDecideAction, type ActionView } from '../api/actions'
import { formatMoney, formatQty } from './format'

const STATUS: Record<ActionView['status'], [string, string]> = {
  pending: ['Awaiting your confirmation', 'bg-amber-50 text-amber-800 border-amber-200'],
  executing: ['Creating…', 'bg-sky-50 text-sky-800 border-sky-200'],
  executed: ['Draft purchase orders created', 'bg-emerald-50 text-emerald-800 border-emerald-200'],
  failed: ['Not created', 'bg-rose-50 text-rose-800 border-rose-200'],
  rejected: ['Rejected', 'bg-slate-100 text-slate-600 border-slate-200'],
  expired: ['Expired', 'bg-slate-100 text-slate-600 border-slate-200'],
}

/**
 * A proposed write, shown for an explicit decision. Confirm is the only way
 * anything reaches the ERP, and it only ever creates draft purchase orders.
 */
export function ProposalCard({ id, initial, compact = false }: { id: string; initial?: ActionView; compact?: boolean }) {
  const { data: action, isPending, isError, error } = useAction(id, initial)
  const decide = useDecideAction(id)

  if (isPending) return <div className="h-24 animate-pulse rounded-xl border border-slate-200 bg-slate-50" />
  if (isError) return <p className="text-sm text-rose-600">Could not load proposal: {error.message}</p>

  const p = action.payload
  const [label, tone] = STATUS[action.status]
  const canDecide = action.status === 'pending' || action.status === 'failed'

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white text-sm shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-2.5">
        <div className="min-w-0">
          <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">Proposed draft purchase orders</p>
          <p className="truncate font-medium text-slate-800">{p.summary}</p>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}>{label}</span>
      </header>

      <div className="space-y-3 px-4 py-3">
        {p.orders.map((o) => (
          <div key={o.supplier_id}>
            <div className="flex items-baseline justify-between gap-2">
              <p className="font-medium text-slate-800">
                {o.supplier}
                {o.partner_ref && <span className="ml-1.5 text-xs font-normal text-slate-400">ref {o.partner_ref}</span>}
              </p>
              <p className="shrink-0 tabular-nums">
                {formatMoney(o.total, p.currency)}
                {o.lead_days != null && <span className="text-xs text-slate-400"> · {o.lead_days} d lead</span>}
              </p>
            </div>
            <ul className={`mt-1 space-y-0.5 text-slate-600 ${compact ? 'text-xs' : ''}`}>
              {o.lines.map((l) => (
                <li key={l.product_id} className="flex justify-between gap-3">
                  <span className="min-w-0 truncate">
                    {formatQty(l.quantity)} × {l.code} <span className="text-slate-400">{l.name}</span>
                  </span>
                  <span className="shrink-0 tabular-nums">
                    @ {formatMoney(l.unit_price, p.currency)}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div className="flex justify-between border-t border-slate-100 pt-2 font-semibold">
          <span>Total</span>
          <span className="tabular-nums">{formatMoney(p.total, p.currency)}</span>
        </div>
        {p.warnings.length > 0 && (
          <ul className="space-y-0.5 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {p.warnings.map((w) => (
              <li key={w}>⚠ {w}</li>
            ))}
          </ul>
        )}

        {action.status === 'executed' && (
          <ul className="space-y-1 rounded-lg bg-emerald-50 px-3 py-2 text-emerald-900">
            {action.created.map((po) => (
              <li key={po.name} className="flex flex-wrap justify-between gap-2">
                <span>
                  <span className="font-semibold">{po.name}</span> · {po.supplier} (draft RFQ)
                  {po.simulated && <span className="ml-1 text-xs">· demo, not sent to an ERP</span>}
                </span>
                {po.url && (
                  <a href={po.url} target="_blank" rel="noreferrer" className="font-medium underline">
                    Open in Odoo
                  </a>
                )}
              </li>
            ))}
          </ul>
        )}
        {action.error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-rose-700">{action.error}</p>}
        {decide.isError && <p className="text-rose-600">{decide.error.message}</p>}
        {action.status === 'expired' && <p className="text-xs text-slate-500">Proposals expire after 30 minutes.</p>}

        {canDecide && (
          <div className="flex flex-wrap items-center gap-2 pt-1">
            <button
              type="button"
              disabled={decide.isPending}
              onClick={() => decide.mutate('confirm')}
              className="rounded-lg bg-teal-700 px-3.5 py-1.5 font-medium text-white hover:bg-teal-800 disabled:opacity-50"
            >
              {decide.isPending ? 'Working…' : action.status === 'failed' ? 'Retry' : 'Confirm & create drafts'}
            </button>
            {action.status === 'pending' && (
              <button
                type="button"
                disabled={decide.isPending}
                onClick={() => decide.mutate('reject')}
                className="rounded-lg border border-slate-300 px-3.5 py-1.5 text-slate-700 hover:bg-slate-50 disabled:opacity-50"
              >
                Reject
              </button>
            )}
            <span className="text-xs text-slate-500">Creates draft RFQs only; nothing is sent to suppliers.</span>
          </div>
        )}
      </div>
    </section>
  )
}
