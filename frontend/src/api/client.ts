import { accessToken, clearAccessToken } from './access'

// Minimal typed fetch wrapper. All requests are same-origin `/api/...`
// (Vite proxy in dev, Vercel rewrite in production).

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

const CLIENT_ID_KEY = 'voltride.clientId'
let memoryClientId: string | null = null

/**
 * A random id that scopes this browser's conversations, proposals and quote
 * reviews (not authentication). Kept in localStorage; falls back to memory
 * where storage is unavailable.
 */
export function clientId(): string {
  try {
    const stored = localStorage.getItem(CLIENT_ID_KEY)
    if (stored) return stored
    const id = crypto.randomUUID()
    localStorage.setItem(CLIENT_ID_KEY, id)
    return id
  } catch {
    memoryClientId ??= crypto.randomUUID()
    return memoryClientId
  }
}

export async function errorFrom(response: Response): Promise<ApiError> {
  // The backend returns {"detail": "..."} for errors (a list of field errors
  // for 422 validation failures); fall back to the status text.
  const body = await response.json().catch(() => null)
  const detail = typeof body?.detail === 'string' ? body.detail : response.statusText
  return new ApiError(response.status, detail || `Request failed (${response.status})`)
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { ...init, headers: { Accept: 'application/json', ...init?.headers } })
  } catch {
    throw new ApiError(0, 'Cannot reach the server.')
  }
  if (!response.ok) {
    // A rejected access token: forget it so the password form shows again.
    if (response.status === 401 && (init?.headers as Record<string, string> | undefined)?.Authorization) clearAccessToken()
    throw await errorFrom(response)
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

export const getJson = <T>(path: string) => request<T>(path)

export const postJson = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

/** Headers for requests scoped to this browser: client id, plus the demo access token if held. */
export function ownedHeaders(): Record<string, string> {
  const token = accessToken()
  return { 'X-Client-Id': clientId(), ...(token ? { Authorization: `Bearer ${token}` } : {}) }
}

/** A request scoped to this browser's client id (chat, proposals, intake, audit). */
export const ownedRequest = <T>(path: string, init?: RequestInit) =>
  request<T>(path, { ...init, headers: { ...ownedHeaders(), ...(init?.headers as Record<string, string>) } })

export const ownedPost = <T>(path: string, body?: unknown) =>
  ownedRequest<T>(path, {
    method: 'POST',
    ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
