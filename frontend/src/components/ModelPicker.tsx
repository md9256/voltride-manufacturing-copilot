import { useChatStatus } from '../api/chat'
import { selectModel, useSelectedModel } from '../api/model'

// Free-tier quotas differ a lot per model; a short hint helps people choose.
const HINTS: Record<string, string> = {
  'gemini-3.5-flash': 'balanced (default)',
  'gemini-3.8-flash': 'newest; small free quota',
  'gemini-3.5-flash-lite': 'fastest; largest free quota',
}

/**
 * Picks the AI model for new chats, quote reading and daily briefings.
 * Existing chats keep the model they started with.
 */
export function ModelPicker() {
  const status = useChatStatus()
  const picked = useSelectedModel()
  const models = status.data?.models ?? []
  if (!status.data?.enabled || models.length < 2) return null
  // A stored choice the server no longer offers falls back to its default.
  const current = models.some((m) => m.id === picked) ? picked! : status.data.model

  return (
    <label className="flex items-center gap-1.5 text-xs text-slate-500">
      <span className="hidden xl:inline">AI model</span>
      <select
        value={current}
        onChange={(e) => selectModel(e.target.value)}
        className="rounded-full border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700"
        aria-label="AI model"
        title={models.map((m) => `${m.label}: ${HINTS[m.id] ?? ''}`).join('\n')}
      >
        {models.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label.replace(/^Gemini /, '')}
          </option>
        ))}
      </select>
    </label>
  )
}
