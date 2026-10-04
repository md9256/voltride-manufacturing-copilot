import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'

export function Card({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-5 py-3.5">
        <h2 className="text-sm font-semibold text-slate-800">{title}</h2>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </header>
      <div className="p-5">{children}</div>
    </section>
  )
}

/** Renders loading / error / empty states for a query, and `children` once data is in. */
export function QueryState<T>({
  query,
  empty,
  isEmpty = (data) => Array.isArray(data) && data.length === 0,
  children,
}: {
  query: UseQueryResult<T>
  empty?: string
  isEmpty?: (data: T) => boolean
  children: (data: T) => ReactNode
}) {
  if (query.isPending) {
    return (
      <div className="space-y-2" aria-busy="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-4 animate-pulse rounded bg-slate-100" />
        ))}
      </div>
    )
  }
  if (query.isError) {
    return (
      <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700" role="alert">
        Could not load: {query.error.message}
        <button className="ml-2 font-medium underline" onClick={() => query.refetch()}>
          Retry
        </button>
      </div>
    )
  }
  if (empty && isEmpty(query.data)) {
    return <p className="text-sm text-slate-500">{empty}</p>
  }
  return <>{children(query.data)}</>
}
