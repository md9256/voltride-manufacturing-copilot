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

export async function getJson<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { headers: { Accept: 'application/json' } })
  } catch {
    throw new ApiError(0, 'Cannot reach the server.')
  }
  if (!response.ok) {
    // The backend returns {"detail": "..."} for errors; fall back to the status text.
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : response.statusText
    throw new ApiError(response.status, detail || `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}
