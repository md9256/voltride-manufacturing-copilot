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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { ...init, headers: { Accept: 'application/json', ...init?.headers } })
  } catch {
    throw new ApiError(0, 'Cannot reach the server.')
  }
  if (!response.ok) {
    // The backend returns {"detail": "..."} for errors (a list of field errors
    // for 422 validation failures); fall back to the status text.
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : response.statusText
    throw new ApiError(response.status, detail || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export const getJson = <T>(path: string) => request<T>(path)

export const postJson = <T>(path: string, body: unknown) =>
  request<T>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
