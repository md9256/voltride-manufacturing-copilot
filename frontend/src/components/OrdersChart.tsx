import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { useOrdersOverTime, useSummary } from '../api/dashboard'
import { Card, QueryState } from './Card'
import { formatMoney } from './format'

const WEEKS = 12

function weekLabel(isoDate: string): string {
  // week_start is a plain date (no time zone); parse it as local midnight.
  const [y, m, d] = isoDate.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

export function OrdersChart() {
  const query = useOrdersOverTime(WEEKS)
  const currency = useSummary().data?.currency
  return (
    <Card title="Confirmed orders per week" subtitle={`Last ${WEEKS} weeks, by order date`}>
      <QueryState query={query}>
        {(weeks) => (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={weeks} margin={{ top: 4, right: 4, bottom: 0, left: -12 }}>
                <CartesianGrid vertical={false} stroke="#e2e8f0" />
                <XAxis
                  dataKey="week_start"
                  tickFormatter={weekLabel}
                  tick={{ fontSize: 12, fill: '#64748b' }}
                  tickLine={false}
                  axisLine={false}
                  interval="preserveStartEnd"
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 12, fill: '#64748b' }}
                  tickLine={false}
                  axisLine={false}
                />
                <Tooltip
                  cursor={{ fill: '#f1f5f9' }}
                  content={({ active, payload }) => {
                    const week = active && payload?.[0]?.payload
                    if (!week) return null
                    return (
                      <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs shadow-md">
                        <p className="font-medium text-slate-800">Week of {weekLabel(week.week_start)}</p>
                        <p className="text-slate-600">
                          {week.order_count} order{week.order_count === 1 ? '' : 's'} ·{' '}
                          {formatMoney(week.revenue, currency)}
                        </p>
                      </div>
                    )
                  }}
                />
                <Bar dataKey="order_count" name="Orders" fill="#0f766e" radius={[4, 4, 0, 0]} maxBarSize={36} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </QueryState>
    </Card>
  )
}
