import { useLowStock } from '../api/dashboard'
import { Card, QueryState } from './Card'
import { formatQty } from './format'

export function LowStockList() {
  const query = useLowStock()
  return (
    <Card title="Low-stock components" subtitle="On hand vs. reorder minimum, most critical first">
      <QueryState query={query} empty="Everything is above its reorder minimum.">
        {(levels) => (
          <ul className="space-y-3">
            {levels.map((s) => {
              const coverage = s.min_qty > 0 ? Math.min(s.on_hand / s.min_qty, 1) : 1
              return (
                <li key={s.product_id}>
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="truncate text-slate-800">
                      {s.product_name}
                      {s.product_code && <span className="ml-1.5 text-xs text-slate-400">{s.product_code}</span>}
                    </span>
                    <span className="shrink-0 tabular-nums text-slate-600">
                      <span className={s.on_hand === 0 ? 'font-semibold text-rose-600' : ''}>{formatQty(s.on_hand)}</span>
                      <span className="text-slate-400"> / {formatQty(s.min_qty)}</span>
                    </span>
                  </div>
                  <div
                    className="mt-1 h-1.5 rounded-full bg-slate-100"
                    role="meter"
                    aria-valuemin={0}
                    aria-valuemax={s.min_qty}
                    aria-valuenow={s.on_hand}
                    aria-label={`${s.product_name} stock coverage`}
                  >
                    <div
                      className={`h-full rounded-full ${coverage < 0.25 ? 'bg-rose-500' : 'bg-amber-400'}`}
                      style={{ width: `${Math.max(coverage * 100, 2)}%` }}
                    />
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </QueryState>
    </Card>
  )
}
