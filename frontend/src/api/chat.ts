import { useQuery } from '@tanstack/react-query'
import { ApiError } from './client'

// --- types (mirror backend/app/api/chat.py) ---

export interface ChatStatus {
  enabled: boolean
  provider: string
  model: string
  reason: string | null
}

export interface ConversationSummary {
  id: string
  title: string
  provider: string
  model: string
  updated_at: string
}

export type DisplayMessage =
  | { role: 'user'; display: { text: string } }
  | { role: 'assistant'; display: { text: string; tool_calls: { id: string; name: string; input: unknown }[] } }
  | { role: 'tool'; display: { results: { id: string; ok: boolean; summary: string }[] } }

export interface ConversationDetail extends ConversationSummary {
  messages: DisplayMessage[]
  can_continue: boolean
}

export type ChatEvent =
  | { type: 'text'; delta: string }
  | { type: 'tool_started'; id: string; name: string; input: unknown }
  | { type: 'tool_finished'; id: string; name: string; ok: boolean; summary: string }
  | { type: 'done' }
  | { type: 'error'; message: string }

// --- anonymous client id ---

const CLIENT_ID_KEY = 'voltride.clientId'
let memoryClientId: string | null = null

/**
 * A random id that scopes this browser's conversations (not authentication).
 * Kept in localStorage; falls back to memory where storage is unavailable.
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

async function chatRequest<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      ...init,
      headers: { Accept: 'application/json', 'X-Client-Id': clientId(), ...init?.headers },
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the server.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, typeof body?.detail === 'string' ? body.detail : response.statusText)
  }
  return (response.status === 204 ? undefined : await response.json()) as T
}

// --- queries ---

export const useChatStatus = () =>
  useQuery({ queryKey: ['chat', 'status'], queryFn: () => chatRequest<ChatStatus>('/api/chat/status') })

export const useConversations = (enabled: boolean) =>
  useQuery({
    queryKey: ['chat', 'conversations'],
    queryFn: () => chatRequest<ConversationSummary[]>('/api/chat/conversations'),
    enabled,
  })

export const fetchConversation = (id: string) => chatRequest<ConversationDetail>(`/api/chat/conversations/${id}`)

export const createConversation = () =>
  chatRequest<ConversationSummary>('/api/chat/conversations', { method: 'POST' })

export const deleteConversation = (id: string) =>
  chatRequest<void>(`/api/chat/conversations/${id}`, { method: 'DELETE' })

/**
 * Send a message and read the reply as Server-Sent Events.
 *
 * EventSource only supports GET, so this reads the POST response body as a
 * stream and splits it into `data: {...}` events itself.
 */
export async function streamMessage(
  conversationId: string,
  text: string,
  onEvent: (event: ChatEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response
  try {
    response = await fetch(`/api/chat/conversations/${conversationId}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Client-Id': clientId() },
      body: JSON.stringify({ text }),
      signal,
    })
  } catch {
    if (signal?.aborted) return
    throw new ApiError(0, 'Cannot reach the server.')
  }
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => null)
    throw new ApiError(response.status, typeof body?.detail === 'string' ? body.detail : response.statusText)
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    // Events are separated by a blank line.
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      for (const line of raw.split('\n')) {
        if (line.startsWith('data: ')) onEvent(JSON.parse(line.slice(6)) as ChatEvent)
      }
    }
  }
}
