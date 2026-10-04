import { Fragment } from 'react'
import { Link } from 'react-router'
import { useSummary } from '../api/dashboard'
import { usePlan, useProducts } from '../api/planning'
import type { PlanResult, Requirement } from '../api/types'
import { Card, QueryState } from '../components/Card'
import { PlanControls } from '../components/PlanControls'
import { NodeStatusBadge } from '../components/StateBadge'
import { formatMoney, formatQty } from '../components/format'
import { usePlanParams } from '../hooks/usePlanParams'

export function PlannerPage() {
  const products = useProducts('manufactured')
  const { product, quantity, countIncoming, update } = usePlanParams(products.data)
  const plan = usePlan(product ? { product_id: product.id, quantity, count_incoming: countIncoming } : null)
  const currency = useSummary().data?.currency

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">What-if planner</h1>
        <p className="mt-0.5 text-sm text-slate-500">What it takes to build a quantity: shortages, purchases, bottlenecks and cost.</p>
      </div>
      <PlanControls productId={product?.id ?? null} quantity={quantity} onChange={update}>
        <label className="flex items-center gap-2 py-2 text-sm text-slate-700">
          <input
            type="checkbox"
            className="h-4 w-4 accent-teal-700"
            checked={countIncoming}
            onChange={(e) => update({ countIncoming: e.target.checked })}
          />
          Count incoming receipts
        </label>
        {product && (
          <Link
            to={`/bom?product=${product.id}&qty=${quantity}`}
            className="py-2 text-sm font-medium text-teal-700 hover:underline"
          >
            View BOM tree
          </Link>
        )}
      </PlanControls>

      {products.isError && <QueryState query={products}>{() => null}</QueryState>}
      <QueryState query={plan}>
        {() =>
          plan.data && (
            // Dim stale results while a new plan loads instead of flashing skeletons.
            <div className={`space-y-6 transition-opacity ${plan.isPlaceholderData ? 'opacity-50' : ''}`}>
              <PlanKpis plan={plan.data} currency={currency} />
              <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
                <Bottlenecks plan={plan.data} />
                <Purchases plan={plan.data} currency={currency} />
              </div>
              <Requirements rows={plan.data.requirements} />
              <ul className="space-y-1 text-xs text-slate-500">
                {plan.data.notes.map((n) => (
                  <li key={n}>* {n}</li>
                ))}
              </ul>
            </div>
          )
        }
      </QueryState>
    </div>
  )
}

function Kpi({ label, value, hint, tone }: { label: string; value: string; hint?: string; tone?: 'bad' | 'good' }) {
  const color = tone === 'bad' ? 'text-rose-600' : tone === 'good' ? 'text-emerald-600' : 'text-slate-900'
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      {hint && <p className="mt-0.5 truncate text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

function PlanKpis({ plan, currency }: { plan: PlanResult; currency: string | undefined }) {
  const cap = plan.capacity_bottleneck
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Kpi
        label="Purchase cost"
        value={formatMoney(plan.purchase_total, currency, true)}
        hint={`${plan.purchases.length} supplier${plan.purchases.length === 1 ? '' : 's'}`}
      />
      <Kpi
        label="Short components"
        value={String(plan.short_count)}
        hint={plan.short_count ? 'must be ordered' : 'all covered'}
        tone={plan.short_count ? 'bad' : 'good'}
      />
      <Kpi label="Est. lead time" value={`~${Math.ceil(plan.estimated_days)} d`} hint="critical path" />
      <Kpi
        label="Capacity bottleneck"
        value={cap ? `${cap.days} d` : '—'}
        hint={cap ? `${cap.name}, ${cap.hours} h of work` : 'no operations'}
      />
    </div>
  )
}

function Bottlenecks({ plan }: { plan: PlanResult }) {
  const maxDays = Math.max(...plan.capacity.map((c) => c.days), 0.1)
  return (
    <Card title="Bottlenecks" subtitle="What limits this build, longest first">
      <h3 className="text-xs font-semibold tracking-wide text-slate-500 uppercase">Materials</h3>
      {plan.material_bottlenecks.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">No material shortages.</p>
      ) : (
        <ul className="mt-2 divide-y divide-slate-100 text-sm">
          {plan.material_bottlenecks.map((m) => (
            <li key={m.product_id} className="flex items-baseline justify-between gap-3 py-1.5">
              <span className="min-w-0 truncate">
                {m.name} <span className="text-xs text-slate-400">{m.code}</span>
              </span>
              <span className="shrink-0 text-right tabular-nums text-slate-600">
                short {formatQty(m.shortage)} ·{' '}
                <span className="font-medium text-slate-800">{m.lead_days ?? '?'} d</span>
              </span>
            </li>
          ))}
        </ul>
      )}
      <h3 className="mt-5 text-xs font-semibold tracking-wide text-slate-500 uppercase">Work center load</h3>
      <ul className="mt-2 space-y-2.5">
        {plan.capacity.map((c) => (
          <li key={c.workcenter_id} className="text-sm">
            <div className="flex justify-between gap-3">
              <span>{c.name}</span>
              <span className="tabular-nums text-slate-600">
                {c.hours} h · {c.days} d <span className="text-slate-400">at {c.hours_per_day} h/day</span>
              </span>
            </div>
            <div className="mt-1 h-1.5 rounded-full bg-slate-100">
              <div
                className={`h-full rounded-full ${c === plan.capacity[0] ? 'bg-teal-700' : 'bg-teal-300'}`}
                style={{ width: `${Math.max((c.days / maxDays) * 100, 2)}%` }}
              />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function Purchases({ plan, currency }: { plan: PlanResult; currency: string | undefined }) {
  return (
    <Card
      title="Purchase list"
      subtitle={plan.count_incoming ? 'Shortages after expected receipts, by supplier' : 'Shortages, by supplier'}
    >
      {plan.purchases.length === 0 ? (
        <p className="text-sm text-slate-500">Nothing to buy: free stock{plan.count_incoming && ' and receipts'} cover it.</p>
      ) : (
        <div className="space-y-4">
          {plan.purchases.map((g) => (
            <div key={g.supplier ?? 'none'}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="font-medium text-slate-800">{g.supplier ?? 'No supplier configured'}</span>
                <span className="tabular-nums font-medium">{formatMoney(g.total, currency)}</span>
              </div>
              <ul className="mt-1 space-y-0.5 text-sm text-slate-600">
                {g.lines.map((l) => (
                  <li key={l.product_id} className="flex justify-between gap-3">
                    <span className="min-w-0 truncate">
                      {formatQty(l.order_qty)} × {l.name}
                      {l.note && <span className="block text-xs text-amber-700">{l.note}</span>}
                    </span>
                    <span className="shrink-0 tabular-nums">
                      {formatMoney(l.total, currency)}
                      <span className="text-xs text-slate-400"> · {l.lead_days ?? '?'} d</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <div className="flex justify-between border-t border-slate-200 pt-2 text-sm font-semibold">
            <span>Total</span>
            <span className="tabular-nums">{formatMoney(plan.purchase_total, currency)}</span>
          </div>
        </div>
      )}
    </Card>
  )
}

function Requirements({ rows }: { rows: Requirement[] }) {
  const levels = [...new Set(rows.map((r) => r.level))]
  return (
    <Card title="Requirements by BOM level" subtitle="Each product netted once against free stock, across all branches">
      <div className="-mx-5 -my-2 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-right text-xs text-slate-500">
              <th className="px-5 py-2 text-left font-medium">Product</th>
              <th className="px-2 py-2 font-medium">Needed</th>
              <th className="px-2 py-2 font-medium">From stock</th>
              <th className="px-2 py-2 font-medium">Build</th>
              <th className="px-2 py-2 font-medium">Buy</th>
              <th className="px-2 py-2 font-medium">Incoming</th>
              <th className="px-2 py-2 font-medium">Short</th>
              <th className="px-5 py-2 text-left font-medium">Status</th>
            </tr>
          </thead>
          <tbody>
            {levels.map((level) => (
              <Fragment key={level}>
                <tr>
                  <td colSpan={8} className="bg-slate-50 px-5 py-1 text-xs font-medium text-slate-500">
                    {level === 0 ? 'Finished product' : `Level ${level}`}
                  </td>
                </tr>
                {rows
                  .filter((r) => r.level === level)
                  .map((r) => (
                    <tr key={r.product_id} className="border-t border-slate-100 text-right tabular-nums">
                      <td className="px-5 py-1.5 text-left">
                        <span className="text-slate-800">{r.name}</span>
                        <span className="ml-1.5 text-xs text-slate-400">{r.code}</span>
                      </td>
                      <td className="px-2 py-1.5">{formatQty(r.gross_qty)}</td>
                      <Num value={r.from_stock} />
                      <Num value={r.to_build} />
                      <Num value={r.to_buy} />
                      <Num value={r.covered_by_incoming} />
                      <Num value={r.shortage} bad />
                      <td className="px-5 py-1.5 text-left">
                        <NodeStatusBadge status={r.status} />
                      </td>
                    </tr>
                  ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** A quantity cell that fades zeros so the non-zero numbers stand out. */
function Num({ value, bad }: { value: number; bad?: boolean }) {
  if (value === 0) return <td className="px-2 py-1.5 text-slate-300">–</td>
  return <td className={`px-2 py-1.5 ${bad ? 'font-semibold text-rose-600' : ''}`}>{formatQty(value)}</td>
}
