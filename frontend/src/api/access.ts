import { useQuery } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'

// Demo access token: issued by the server for the demo password, stored per
// browser, sent as a Bearer header on AI and write requests. A 401 clears it,
// which makes every <AccessGate> show the password form again.

const KEY = 'voltride.accessToken'
let memoryToken: string | null = null
const listeners = new Set<() => void>()

function read(): string | null {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return memoryToken
    const { token, expiresAt } = JSON.parse(raw) as { token: string; expiresAt: number }
    return expiresAt * 1000 > Date.now() ? token : null
  } catch {
    return memoryToken
  }
}

function write(value: { token: string; expiresAt: number } | null) {
  memoryToken = value?.token ?? null
  try {
    if (value) localStorage.setItem(KEY, JSON.stringify(value))
    else localStorage.removeItem(KEY)
  } catch {
    // storage unavailable (private mode): the in-memory copy still works this session
  }
  listeners.forEach((l) => l())
}

export const accessToken = read
export const clearAccessToken = () => write(null)

export function useAccessToken(): string | null {
  return useSyncExternalStore(
    (onChange) => {
      listeners.add(onChange)
      return () => listeners.delete(onChange)
    },
    read,
    read,
  )
}

export const useAuthStatus = () =>
  useQuery({
    queryKey: ['auth', 'status'],
    queryFn: async () => {
      const r = await fetch('/api/auth/status')
      if (!r.ok) throw new Error('Cannot reach the server.')
      return (await r.json()) as { required: boolean }
    },
    staleTime: Infinity,
  })

export async function login(password: string): Promise<void> {
  let response: Response
  try {
    response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password }),
    })
  } catch {
    throw new Error('Cannot reach the server.')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'Login failed.')
  write({ token: body.token, expiresAt: body.expires_at })
}
