import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useState } from 'react'
import { useShopfloorStats, useTimeline, type ShopfloorStats } from '../api/shopfloor'
import { Card, QueryState } from '../components/Card'
import { DailySummary } from '../components/shopfloor/DailySummary'
import { WorkOrderTimeline } from '../components/shopfloor/WorkOrderTimeline'

const RANGES = [
  [14, 7, '2 weeks + next week'],
  [35, 7, '5 weeks + next week'],
] as const

function todayIn(tz: string): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' }).format(
    new Date(),
  )
}

export function ShopfloorPage() {
  const [range, setRange] = useState(0)
  const [back, ahead] = RANGES[range]
  const timeline = useTimeline(back, ahead)
  const stats = useShopfloorStats(6)
  const tz = timeline.data?.timezone ?? stats.data?.timezone

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Shop floor</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Work orders by work center, planned versus actual time, upcoming load, and an AI daily briefing.
        </p>
      </div>

      {tz ? <DailySummary today={todayIn(tz)} /> : <div className="h-28 animate-pulse rounded-xl bg-slate-100" />}

      <Card title="Work order timeline" subtitle="Odoo's own schedule for open work; recorded times for finished work">
        <div className="mb-3 flex flex-wrap gap-1">
          {RANGES.map(([, , label], i) => (
            <button
              key={label}
              type="button"
              onClick={() => setRange(i)}
              aria-pressed={range === i}
              className={`rounded-lg px-3 py-1 text-sm ${range === i ? 'bg-teal-50 font-medium text-teal-800' : 'text-slate-600 hover:bg-slate-100'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <QueryState query={timeline}>{(data) => <WorkOrderTimeline timeline={data} />}</QueryState>
      </Card>

      <QueryState query={stats}>
        {(data) => (
          <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
            <VarianceCard stats={data} />
            <LoadCard stats={data} />
          </div>
        )}
      </QueryState>
    </div>
  )
}

function pct(v: number | null) {
  return v == null ? '—' : `${v > 0 ? '+' : ''}${v}%`
}

function VarianceCard({ stats }: { stats: ShopfloorStats }) {
  const o = stats.overall
  return (
    <Card title="Planned vs actual (last 6 weeks)" subtitle={`${o.finished} finished work orders · ${pct(o.variance_pct)} overall`}>
      <div className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={stats.by_workcenter} margin={{ top: 4, right: 4, bottom: 0, left: -8 }}>
            <CartesianGrid vertical={false} stroke="#e2e8f0" />
            <XAxis dataKey="workcenter" tick={{ fontSize: 12, fill: '#64748b' }} tickLine={false} axisLine={false} />
            <YAxis tick={{ fontSize: 12, fill: '#64748b' }} tickLine={false} axisLine={false} unit=" m" />
            <Tooltip
              formatter={(value, name) => [`${Math.round(Number(value))} min`, name]}
              labelFormatter={(label, payload) => `${label} (${pct(payload?.[0]?.payload?.variance_pct ?? null)})`}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Bar dataKey="planned_minutes" name="Planned" fill="#94a3b8" radius={[3, 3, 0, 0]} />
            <Bar dataKey="actual_minutes" name="Actual" fill="#0f766e" radius={[3, 3, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <h3 className="mt-4 text-xs font-semibold tracking-wide text-slate-500 uppercase">Biggest overruns</h3>
      <ul className="mt-1 divide-y divide-slate-100 text-sm">
        {stats.top_overruns.map((r) => (
          <li key={`${r.production}-${r.operation}`} className="flex justify-between gap-3 py-1.5">
            <span className="min-w-0 truncate">
              {r.production} · {r.operation} <span className="text-xs text-slate-400">{r.workcenter}</span>
            </span>
            <span className="shrink-0 tabular-nums">
              {Math.round(r.actual_minutes)} / {Math.round(r.planned_minutes)} min{' '}
              <span className="font-medium text-rose-600">{pct(r.variance_pct)}</span>
            </span>
          </li>
        ))}
      </ul>
    </Card>
  )
}

function LoadCard({ stats }: { stats: ShopfloorStats }) {
  const days = [...new Set(stats.load.map((l) => l.day))]
  const centers = [...new Set(stats.load.map((l) => l.workcenter))]
  const cell = (wc: string, day: string) => stats.load.find((l) => l.workcenter === wc && l.day === day)
  return (
    <Card title="Planned load, next 7 days" subtitle="Hours of scheduled work vs. working hours (weekends closed)">
      <div className="-mx-5 overflow-x-auto px-5">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-slate-500">
              <th className="py-1 pr-2 text-left font-medium">Work center</th>
              {days.map((d) => (
                <th key={d} className="px-1 py-1 text-center font-medium whitespace-nowrap">
                  {new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric' })}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {centers.map((wc) => (
              <tr key={wc}>
                <td className="py-1 pr-2 whitespace-nowrap text-slate-700">{wc}</td>
                {days.map((d) => {
                  const l = cell(wc, d)!
                  const ratio = l.capacity_hours ? l.planned_hours / l.capacity_hours : l.planned_hours ? 2 : 0
                  const tone =
                    l.capacity_hours === 0 && l.planned_hours === 0
                      ? 'bg-slate-50 text-slate-300'
                      : ratio > 1
                        ? 'bg-rose-100 text-rose-800'
                        : ratio > 0.75
                          ? 'bg-amber-100 text-amber-800'
                          : ratio > 0
                            ? 'bg-teal-50 text-teal-800'
                            : 'text-slate-400'
                  return (
                    <td key={d} className="px-0.5 py-0.5">
                      <div className={`rounded px-1 py-1.5 text-center tabular-nums ${tone}`} title={`${l.planned_hours} h of ${l.capacity_hours} h`}>
                        {l.capacity_hours === 0 && l.planned_hours === 0 ? '—' : `${Math.round(l.planned_hours * 10) / 10}h`}
                      </div>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
