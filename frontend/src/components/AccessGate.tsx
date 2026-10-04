import { useState, type ReactNode } from 'react'
import { login, useAccessToken, useAuthStatus } from '../api/access'

/**
 * Shows `children` when the demo needs no password or a valid token is held;
 * otherwise an inline password form. Read-only pages never use this gate.
 */
export function AccessGate({ children, what }: { children: ReactNode; what: string }) {
  const status = useAuthStatus()
  const token = useAccessToken()
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status.isPending) return <div className="h-16 animate-pulse rounded-lg bg-slate-50" />
  if (!status.data?.required || token) return <>{children}</>

  return (
    <form
      className="rounded-xl border border-slate-200 bg-slate-50 p-4 text-sm"
      onSubmit={async (e) => {
        e.preventDefault()
        setBusy(true)
        setError(null)
        try {
          await login(password)
        } catch (err) {
          setError((err as Error).message)
        } finally {
          setBusy(false)
        }
      }}
    >
      <p className="font-medium text-slate-800">{what} is password-protected on this public demo.</p>
      <p className="mt-0.5 text-xs text-slate-500">
        It calls a paid-per-use AI model and can create draft records, so access is limited. Ask the author for the
        demo password.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Demo password"
          aria-label="Demo password"
          className="min-w-0 flex-1 rounded-lg border border-slate-300 px-3 py-1.5"
        />
        <button
          type="submit"
          disabled={busy || !password}
          className="rounded-lg bg-teal-700 px-4 py-1.5 font-medium text-white hover:bg-teal-800 disabled:opacity-50"
        >
          {busy ? 'Checking…' : 'Unlock'}
        </button>
      </div>
      {error && <p className="mt-2 text-rose-600">{error}</p>}
    </form>
  )
}
