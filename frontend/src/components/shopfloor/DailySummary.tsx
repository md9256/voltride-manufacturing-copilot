import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useState } from 'react'
import { useSummary, type SummaryLanguage } from '../../api/shopfloor'
import { Card } from '../Card'

const LANGUAGES: [SummaryLanguage, string][] = [
  ['en', 'English'],
  ['zh-Hans', '简体'],
  ['zh-Hant', '繁體'],
]

/** The AI daily briefing. Facts are computed by the server; the model only narrates them. */
export function DailySummary({ today }: { today: string }) {
  const [day, setDay] = useState(today)
  const [language, setLanguage] = useState<SummaryLanguage>('en')
  const summary = useSummary()
  const result = summary.data
  const stale = result && (result.day !== day || result.language !== language)

  const generate = (regenerate = false) => summary.mutate({ day, language, regenerate })

  return (
    <Card
      title="Daily production briefing"
      subtitle="Figures are computed from ERP data; AI writes the text, and every number in it is checked against those figures."
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs font-medium text-slate-600">
          Day
          <input
            type="date"
            value={day}
            onChange={(e) => setDay(e.target.value)}
            className="rounded-lg border border-slate-300 px-2 py-1.5 text-sm"
          />
        </label>
        <div className="flex rounded-lg border border-slate-300 p-0.5" role="group" aria-label="Language">
          {LANGUAGES.map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setLanguage(value)}
              aria-pressed={language === value}
              className={`rounded-md px-2.5 py-1 text-sm ${language === value ? 'bg-teal-700 text-white' : 'text-slate-600'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled={summary.isPending || !day}
          onClick={() => generate(false)}
          className="rounded-lg bg-teal-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-50"
        >
          {summary.isPending ? 'Writing…' : 'Generate'}
        </button>
        {result && !stale && (
          <button
            type="button"
            disabled={summary.isPending}
            onClick={() => generate(true)}
            className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
          >
            Regenerate
          </button>
        )}
      </div>

      {summary.isError && <p className="mt-4 rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{summary.error.message}</p>}

      {result && (
        <div className={`mt-4 space-y-3 ${stale || summary.isPending ? 'opacity-50' : ''}`}>
          {result.unverified_numbers.length > 0 ? (
            <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">
              ⚠ {result.unverified_numbers.length} figure{result.unverified_numbers.length > 1 ? 's' : ''} in this text could
              not be traced to the data: {result.unverified_numbers.join(', ')}. Check before relying on them.
            </p>
          ) : (
            <p className="text-xs text-emerald-700">✓ Every figure in this briefing matches the ERP data.</p>
          )}
          <div className="chat-markdown text-sm text-slate-800">
            <Markdown remarkPlugins={[remarkGfm]}>{result.text}</Markdown>
          </div>
          <p className="text-xs text-slate-400">
            {result.cached ? 'From cache' : 'Generated'} · {result.provider} · {result.model} ·{' '}
            {new Date(result.created_at).toLocaleString()}
          </p>
          <details className="text-xs">
            <summary className="cursor-pointer text-slate-500">Facts given to the AI</summary>
            <pre className="mt-1 max-h-72 overflow-auto rounded-md bg-slate-50 p-2 text-[11px] whitespace-pre-wrap">
              {JSON.stringify(result.facts, null, 2)}
            </pre>
          </details>
        </div>
      )}
    </Card>
  )
}
