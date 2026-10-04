import type { ActionView } from '../../api/actions'
import type { ChatEvent, DisplayMessage } from '../../api/chat'

export interface ToolChip {
  id: string
  name: string
  input: unknown
  status: 'running' | 'ok' | 'error'
  summary?: string
}

/** One user message, or everything the assistant did in reply to it. */
export type TranscriptItem =
  | { kind: 'user'; text: string }
  | {
      kind: 'assistant'
      text: string
      tools: ToolChip[]
      // Proposed write actions, rendered as confirmation cards. `initial` is the
      // streamed snapshot; stored conversations fetch the current state by id.
      actions: { id: string; initial?: ActionView }[]
      error?: string
      streaming?: boolean
    }

/**
 * Fold stored steps into display turns: an assistant reply may span several
 * steps (tool calls, tool results, final text), shown as one bubble.
 */
export function fromStored(messages: DisplayMessage[]): TranscriptItem[] {
  const items: TranscriptItem[] = []
  const current = () => {
    const last = items.at(-1)
    if (last?.kind === 'assistant') return last
    const fresh: TranscriptItem = { kind: 'assistant', text: '', tools: [], actions: [] }
    items.push(fresh)
    return fresh
  }
  for (const m of messages) {
    if (m.role === 'user') {
      items.push({ kind: 'user', text: m.display.text })
    } else if (m.role === 'assistant') {
      const turn = current()
      turn.text = joinText(turn.text, m.display.text)
      for (const call of m.display.tool_calls) turn.tools.push({ ...call, status: 'running' })
    } else {
      const turn = current()
      for (const r of m.display.results) {
        const chip = turn.tools.find((t) => t.id === r.id)
        if (chip) Object.assign(chip, { status: r.ok ? 'ok' : 'error', summary: r.summary })
        if (r.action_id) turn.actions.push({ id: r.action_id })
      }
    }
  }
  // A stored chip that never got a result belongs to an interrupted turn.
  for (const item of items) {
    if (item.kind === 'assistant') for (const t of item.tools) if (t.status === 'running') t.status = 'error'
  }
  return items
}

/** Apply one streamed event to the in-progress assistant turn (immutably). */
export function applyEvent(
  turn: Extract<TranscriptItem, { kind: 'assistant' }>,
  event: ChatEvent,
): Extract<TranscriptItem, { kind: 'assistant' }> {
  switch (event.type) {
    case 'text':
      return { ...turn, text: turn.text + event.delta }
    case 'tool_started':
      return {
        ...turn,
        // Separate any text written before this tool round from what follows.
        text: turn.text && !turn.text.endsWith('\n\n') ? turn.text + '\n\n' : turn.text,
        tools: [...turn.tools, { id: event.id, name: event.name, input: event.input, status: 'running' }],
      }
    case 'tool_finished':
      return {
        ...turn,
        tools: turn.tools.map((t) =>
          t.id === event.id ? { ...t, status: event.ok ? 'ok' : 'error', summary: event.summary } : t,
        ),
      }
    case 'action_proposed':
      return { ...turn, actions: [...turn.actions, { id: event.action.id, initial: event.action }] }
    case 'done':
      return { ...turn, streaming: false }
    case 'error':
      return { ...turn, streaming: false, error: event.message }
  }
}

function joinText(a: string, b: string): string {
  if (!b) return a
  return a ? `${a}\n\n${b}` : b
}
