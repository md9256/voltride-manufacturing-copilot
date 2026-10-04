import { useMemo, useState } from 'react'
import type { BarStatus, Timeline, TimelineBar } from '../../api/shopfloor'

const STATUS_STYLE: Record<BarStatus, { bar: string; label: string }> = {
  done: { bar: 'bg-emerald-500', label: 'Done' },
  in_progress: { bar: 'bg-amber-400', label: 'In progress' },
  planned: { bar: 'bg-sky-500', label: 'Planned' },
  late: { bar: 'bg-rose-500', label: 'Late' },
}
const DAY_WIDTH = 56 // px per day: a 3-week window fits a desktop card, and scrolls on small screens
const ROW_HEIGHT = 44
const DAY_MS = 86_400_000

/**
 * A Gantt-style view: one row per work center, bars positioned by time.
 * Built from plain divs (no chart library): a timeline is just absolute
 * positioning, and buttons keep every bar keyboard-accessible.
 */
export function WorkOrderTimeline({ timeline }: { timeline: Timeline }) {
  const [selected, setSelected] = useState<TimelineBar | null>(null)
  const tz = timeline.timezone
  const start = Date.parse(timeline.start)
  const end = Date.parse(timeline.end)
  const width = ((end - start) / DAY_MS) * DAY_WIDTH
  const x = (iso: string) => ((Date.parse(iso) - start) / (end - start)) * width

  const days = useMemo(() => {
    // Local midnights in the company time zone, so day columns match the shop floor's days.
    const fmt = new Intl.DateTimeFormat('en-CA', { timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit' })
    const out: { left: number; label: string; weekday: string; weekend: boolean }[] = []
    let t = start
    let last = ''
    while (t < end) {
      const key = fmt.format(t)
      if (key !== last) {
        last = key
        const d = new Date(t)
        const weekday = new Intl.DateTimeFormat('en', { timeZone: tz, weekday: 'short' }).format(d)
        out.push({
          left: ((t - start) / (end - start)) * width,
          label: new Intl.DateTimeFormat(undefined, { timeZone: tz, day: 'numeric', month: 'short' }).format(d),
          weekday,
          weekend: weekday === 'Sat' || weekday === 'Sun',
        })
      }
      t += 3_600_000 // step an hour; robust to any UTC offset
    }
    return out
  }, [start, end, tz, width])

  const local = (iso: string) =>
    new Intl.DateTimeFormat(undefined, { timeZone: tz, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(iso))

  return (
    <div>
      <div className="flex flex-wrap gap-3 pb-3 text-xs text-slate-600">
        {Object.entries(STATUS_STYLE).map(([key, s]) => (
          <span key={key} className="inline-flex items-center gap-1.5">
            <span className={`h-2.5 w-4 rounded-sm ${s.bar}`} /> {s.label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-0.5 bg-slate-800" /> Now
        </span>
        <span className="text-slate-400">Times in {tz}</span>
      </div>

      <div className="flex rounded-lg border border-slate-200">
        <div className="w-28 shrink-0 border-r border-slate-200 bg-slate-50 text-xs font-medium text-slate-700 sm:w-36">
          <div className="h-9 border-b border-slate-200" />
          {timeline.rows.map((row) => (
            <div key={row.workcenter_id} className="flex items-center px-3" style={{ height: ROW_HEIGHT }}>
              {row.workcenter}
            </div>
          ))}
        </div>
        <div className="overflow-x-auto">
          <div className="relative" style={{ width }}>
            {/* day header and weekend shading */}
            <div className="relative h-9 border-b border-slate-200">
              {days.map((d) => (
                <div
                  key={d.left}
                  className="absolute top-0 h-full border-l border-slate-100 px-1 text-[10px] leading-tight text-slate-500"
                  style={{ left: d.left }}
                >
                  <div className={d.weekend ? 'text-slate-400' : ''}>{d.weekday}</div>
                  <div className="whitespace-nowrap">{d.label}</div>
                </div>
              ))}
            </div>
            <div className="relative" style={{ height: ROW_HEIGHT * timeline.rows.length }}>
              {days.map((d, i) => (
                <div
                  key={d.left}
                  className={`absolute top-0 h-full border-l border-slate-100 ${d.weekend ? 'bg-slate-50' : ''}`}
                  style={{ left: d.left, width: (days[i + 1]?.left ?? width) - d.left }}
                />
              ))}
              {timeline.rows.map((row, r) =>
                row.bars.map((bar) => {
                  const left = x(bar.start)
                  const barWidth = Math.max(x(bar.end) - left, 4)
                  return (
                    <button
                      key={bar.id}
                      type="button"
                      onClick={() => setSelected(bar)}
                      onMouseEnter={() => setSelected(bar)}
                      onFocus={() => setSelected(bar)}
                      className={`absolute rounded-sm ${STATUS_STYLE[bar.status].bar} ${
                        selected?.id === bar.id ? 'ring-2 ring-slate-900 ring-offset-1' : 'hover:brightness-110'
                      }`}
                      style={{ left, width: barWidth, top: r * ROW_HEIGHT + 12, height: ROW_HEIGHT - 24 }}
                      aria-label={`${bar.production} ${bar.operation}, ${STATUS_STYLE[bar.status].label}`}
                    />
                  )
                }),
              )}
              <div className="absolute top-0 h-full w-0.5 bg-slate-800" style={{ left: x(timeline.now) }} />
            </div>
          </div>
        </div>
      </div>

      <div className="mt-3 min-h-[64px] rounded-lg bg-slate-50 px-4 py-3 text-sm" aria-live="polite">
        {selected ? (
          <div className="flex flex-wrap gap-x-6 gap-y-1">
            <span className="font-medium text-slate-800">
              {selected.production} · {selected.operation}
            </span>
            <span className="text-slate-600">
              {selected.product_code} × {selected.quantity}
            </span>
            <span className="text-slate-600">
              {STATUS_STYLE[selected.status].label}: {local(selected.start)} → {local(selected.end)}
            </span>
            <span className="text-slate-600">
              Planned {Math.round(selected.planned_minutes)} min
              {selected.status === 'done' && (
                <>
                  {' '}
                  · actual {Math.round(selected.actual_minutes)} min{' '}
                  {selected.variance_pct != null && (
                    <span className={selected.variance_pct > 10 ? 'font-medium text-rose-600' : 'text-emerald-700'}>
                      ({selected.variance_pct > 0 ? '+' : ''}
                      {selected.variance_pct}%)
                    </span>
                  )}
                </>
              )}
            </span>
          </div>
        ) : (
          <span className="text-slate-500">Hover or tap a bar for details.</span>
        )}
      </div>

      {timeline.unscheduled.length > 0 && (
        <p className="mt-3 text-xs text-slate-500">
          Not scheduled yet:{' '}
          {timeline.unscheduled.map((u) => `${u.production} ${u.operation} (${u.workcenter})`).join(', ')}
        </p>
      )}
    </div>
  )
}
