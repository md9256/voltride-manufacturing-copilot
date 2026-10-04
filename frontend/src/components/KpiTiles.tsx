import { useSummary } from '../api/dashboard'
import { formatMoney } from './format'

function Tile({ label, value, hint, alert }: { label: string; value: string; hint?: string; alert?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white px-5 py-4 shadow-sm">
      <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${alert ? 'text-rose-600' : 'text-slate-900'}`}>
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

export function KpiTiles() {
  const { data, isPending, isError } = useSummary()
  if (isPending || isError) {
    // Placeholders keep the layout stable; errors surface in the cards below.
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="h-[92px] animate-pulse rounded-xl border border-slate-200 bg-white" />
        ))}
      </div>
    )
  }
  const inProgress = data.manufacturing_by_state.progress ?? 0
  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <Tile
        label="Open sales orders"
        value={String(data.open_sales_count)}
        hint={`incl. ${data.quotations_count} quotation${data.quotations_count === 1 ? '' : 's'}`}
      />
      <Tile label="Open order value" value={formatMoney(data.open_sales_value, data.currency, true)} hint={data.currency} />
      <Tile
        label="Active manufacturing"
        value={String(data.active_manufacturing_count)}
        hint={`${inProgress} in progress`}
      />
      <Tile
        label="Low-stock components"
        value={String(data.low_stock_count)}
        hint="below reorder minimum"
        alert={data.low_stock_count > 0}
      />
    </div>
  )
}
