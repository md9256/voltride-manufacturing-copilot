import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  createConversation,
  deleteConversation,
  fetchConversation,
  streamMessage,
  useChatStatus,
  useConversations,
} from '../../api/chat'
import { ChatMessages } from './ChatMessages'
import { applyEvent, fromStored, type TranscriptItem } from './transcript'

const SUGGESTIONS = [
  'Can we build 10 mid-drive kits? What are we short of?',
  'Which components are below their reorder minimum?',
  'How have confirmed sales trended over the last 8 weeks?',
  '高功率套件（KIT-HP）由哪些零件组成？',
  '目前有哪些製造訂單正在進行中？',
  'Draft purchase orders for what we are short of to build 5 high-power kits.',
]

type AssistantTurn = Extract<TranscriptItem, { kind: 'assistant' }>

export default function ChatPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const status = useChatStatus()
  const enabled = status.data?.enabled ?? false
  const conversations = useConversations(enabled)
  const queryClient = useQueryClient()

  const [conversationId, setConversationId] = useState<string | null>(null)
  const [items, setItems] = useState<TranscriptItem[]>([])
  const [canContinue, setCanContinue] = useState(true)
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [items])
  useEffect(() => {
    if (open) inputRef.current?.focus()
  }, [open])

  const openConversation = async (id: string | null) => {
    setLoadError(null)
    setConversationId(id)
    setCanContinue(true)
    if (!id) return setItems([])
    try {
      const detail = await fetchConversation(id)
      setItems(fromStored(detail.messages))
      setCanContinue(detail.can_continue)
    } catch (e) {
      setLoadError((e as Error).message)
    }
  }

  const updateLastTurn = (fn: (turn: AssistantTurn) => AssistantTurn) =>
    setItems((prev) => {
      const last = prev.at(-1)
      return last?.kind === 'assistant' ? [...prev.slice(0, -1), fn(last)] : prev
    })

  const send = async (text: string) => {
    const question = text.trim()
    if (!question || busy) return
    setBusy(true)
    setInput('')
    setItems((prev) => [
      ...prev,
      { kind: 'user', text: question },
      { kind: 'assistant', text: '', tools: [], actions: [], streaming: true },
    ])
    try {
      let id = conversationId
      if (!id) {
        id = (await createConversation()).id
        setConversationId(id)
      }
      await streamMessage(id, question, (event) => updateLastTurn((turn) => applyEvent(turn, event)))
    } catch (e) {
      updateLastTurn((turn) => ({ ...turn, streaming: false, error: (e as Error).message }))
    } finally {
      updateLastTurn((turn) => ({ ...turn, streaming: false }))
      setBusy(false)
      queryClient.invalidateQueries({ queryKey: ['chat', 'conversations'] })
    }
  }

  const remove = async () => {
    if (!conversationId || !window.confirm('Delete this conversation?')) return
    await deleteConversation(conversationId).catch(() => undefined)
    await openConversation(null)
    queryClient.invalidateQueries({ queryKey: ['chat', 'conversations'] })
  }

  return (
    <aside
      className={`fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l border-slate-200 bg-white shadow-2xl transition-transform duration-200 sm:w-[440px] ${
        open ? 'translate-x-0' : 'pointer-events-none translate-x-full'
      }`}
      aria-label="VoltRide Copilot assistant"
      aria-hidden={!open}
    >
      <header className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold">Copilot</h2>
          <p className="truncate text-xs text-slate-500">
            {status.data ? `${status.data.provider} · ${status.data.model} · read-only` : 'Connecting…'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => openConversation(null)}
          disabled={busy}
          className="rounded-md border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          New chat
        </button>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md px-2 py-1 text-lg leading-none text-slate-500 hover:bg-slate-100"
          aria-label="Close assistant"
        >
          ×
        </button>
      </header>

      {enabled && (conversations.data?.length ?? 0) > 0 && (
        <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2">
          <select
            className="min-w-0 flex-1 rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700"
            value={conversationId ?? ''}
            onChange={(e) => openConversation(e.target.value || null)}
            disabled={busy}
            aria-label="Previous conversations"
          >
            <option value="">— Previous conversations —</option>
            {conversations.data?.map((c) => (
              <option key={c.id} value={c.id}>
                {c.title}
              </option>
            ))}
          </select>
          {conversationId && (
            <button type="button" onClick={remove} disabled={busy} className="text-xs text-slate-500 hover:text-rose-600">
              Delete
            </button>
          )}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
        {status.data && !enabled ? (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            The assistant is not available on this server: {status.data.reason}
          </p>
        ) : status.isError ? (
          <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">Cannot reach the server.</p>
        ) : items.length === 0 ? (
          <div className="space-y-3">
            <p className="text-sm text-slate-600">
              Ask about stock, shortages, bills of materials, sales or manufacturing orders. Answers come from live
              ERP data through read-only tools. English and 中文 both work.
            </p>
            <div className="flex flex-col gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  disabled={!enabled || busy}
                  className="rounded-lg border border-slate-200 px-3 py-2 text-left text-sm text-slate-700 hover:border-teal-300 hover:bg-teal-50 disabled:opacity-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <ChatMessages items={items} />
        )}
        {loadError && <p className="mt-3 text-sm text-rose-600">Could not load conversation: {loadError}</p>}
      </div>

      <form
        className="border-t border-slate-200 p-3"
        onSubmit={(e) => {
          e.preventDefault()
          send(input)
        }}
      >
        {!canContinue && (
          <p className="mb-2 text-xs text-amber-700">
            This conversation used a different AI provider. Start a new chat to continue.
          </p>
        )}
        <div className="flex items-end gap-2">
          <textarea
            ref={inputRef}
            rows={2}
            maxLength={4000}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends; Shift+Enter adds a line. Ignore Enter while an IME
              // (Chinese input) is composing, or picking a character would send.
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                send(input)
              }
            }}
            placeholder="Ask about stock, shortages, orders…"
            disabled={!enabled || !canContinue}
            className="min-h-[44px] flex-1 resize-none rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-teal-600 focus:outline-none disabled:bg-slate-50"
          />
          <button
            type="submit"
            disabled={!enabled || !canContinue || busy || !input.trim()}
            className="h-[44px] rounded-lg bg-teal-700 px-4 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-40"
          >
            {busy ? '…' : 'Send'}
          </button>
        </div>
      </form>
    </aside>
  )
}
