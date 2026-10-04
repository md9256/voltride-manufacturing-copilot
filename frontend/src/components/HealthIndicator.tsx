import { useHealth } from '../api/dashboard'

/** Small status pill: is the API up, and can it reach Odoo? */
export function HealthIndicator() {
  const { data, isPending, isError } = useHealth()

  let dot = 'bg-slate-300'
  let text = 'Connecting…'
  if (isError) {
    dot = 'bg-rose-500'
    text = 'API unreachable'
  } else if (!isPending && data) {
    dot = data.odoo.reachable ? 'bg-emerald-500' : 'bg-amber-500'
    text = data.odoo.reachable ? `Odoo ${data.odoo.version} · ${data.odoo.mode}` : 'Odoo unreachable'
  }

  return (
    <span
      className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1 text-xs text-slate-600"
      title={data?.odoo.error ?? undefined}
    >
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden />
      {text}
    </span>
  )
}
