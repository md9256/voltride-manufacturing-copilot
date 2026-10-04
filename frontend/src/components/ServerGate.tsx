import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type ReactNode } from 'react'

/**
 * Free hosting puts the API to sleep when idle; the first request then takes
 * 30-60 s while the container starts. Until the API has answered once, show
 * a friendly "waking up" screen that keeps polling, instead of a page of
 * errors. After that, the app renders normally (the header's health pill
 * reports any later outage).
 */
export function ServerGate({ children }: { children: ReactNode }) {
  const [startedAt] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  const health = useQuery({
    queryKey: ['server-gate'],
    queryFn: async () => {
      const ctrl = new AbortController()
      const timer = setTimeout(() => ctrl.abort(), 20_000)
      try {
        const r = await fetch('/api/health', { signal: ctrl.signal })
        if (!r.ok) throw new Error(String(r.status)) // 502/503 from the proxy while the Space boots
        return true
      } finally {
        clearTimeout(timer)
      }
    },
    retry: false,
    staleTime: Infinity, // once awake, never show this screen again in this tab
    refetchInterval: (q) => (q.state.status === 'success' ? false : 4_000),
  })
  const ready = health.isSuccess

  useEffect(() => {
    if (ready) return
    const t = setInterval(() => setElapsed(Math.round((Date.now() - startedAt) / 1000)), 1000)
    return () => clearInterval(t)
  }, [ready, startedAt])

  if (ready) return <>{children}</>
  // Don't flash the screen for a server that answers within a moment.
  if (elapsed < 2 && !health.isError) return null

  return (
    <div className="mx-auto max-w-md py-24 text-center" role="status" aria-live="polite">
      <div className="mx-auto h-10 w-10 animate-spin rounded-full border-4 border-slate-200 border-t-teal-700" />
      <h1 className="mt-6 text-lg font-semibold">Waking up the server…</h1>
      <p className="mt-2 text-sm text-slate-600">
        The demo's API runs on free hosting that sleeps when nobody is using it. Starting it again usually takes 30–60
        seconds.
      </p>
      <p className="mt-4 text-xs text-slate-400 tabular-nums">{elapsed} s</p>
      {elapsed > 120 && (
        <p className="mt-4 text-sm text-amber-700">
          This is taking longer than usual. The server may be rebuilding; keep this tab open or try again in a few
          minutes.
        </p>
      )}
    </div>
  )
}
