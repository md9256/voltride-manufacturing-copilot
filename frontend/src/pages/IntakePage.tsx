import { useMutation } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import type { ActionView } from '../api/actions'
import {
  proposeQuote,
  recheckQuote,
  uploadQuote,
  type Corrections,
  type Flag,
  type LineCorrection,
  type QuoteReview,
} from '../api/intake'
import { useProducts } from '../api/planning'
import { Card } from '../components/Card'
import { ProposalCard } from '../components/ProposalCard'
import { formatMoney } from '../components/format'

const NO_CORRECTIONS: Corrections = { lines: {} }

export function IntakePage() {
  const [review, setReview] = useState<QuoteReview | null>(null)
  const [corrections, setCorrections] = useState<Corrections>(NO_CORRECTIONS)
  const [proposal, setProposal] = useState<ActionView | null>(null)

  const upload = useMutation({
    mutationFn: uploadQuote,
    onSuccess: (r) => {
      setReview(r)
      setCorrections(NO_CORRECTIONS)
      setProposal(null)
    },
  })
  const recheck = useMutation({ mutationFn: (c: Corrections) => recheckQuote(review!.id, c), onSuccess: setReview })
  const propose = useMutation({ mutationFn: () => proposeQuote(review!.id, corrections), onSuccess: setProposal })

  // Every edit is re-checked by the server (debounced); the browser never
  // decides what is valid, it only displays the server's review.
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const correct = (update: (c: Corrections) => Corrections) => {
    const next = update(corrections)
    setCorrections(next)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => recheck.mutate(next), 400)
  }
  const setLine = (index: number, patch: LineCorrection) =>
    correct((c) => ({ ...c, lines: { ...c.lines, [index]: { ...c.lines[index], ...patch } } }))

  const reset = () => {
    setReview(null)
    setProposal(null)
    upload.reset()
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Quote intake</h1>
        <p className="mt-0.5 text-sm text-slate-500">
          Upload a supplier quote or invoice (PDF). AI reads it; the server checks totals, suppliers, products, prices
          and duplicates; you review and confirm a draft purchase order. The file itself is never stored.
        </p>
      </div>

      {!review && <UploadBox busy={upload.isPending} error={upload.error?.message} onFile={(f) => upload.mutate(f)} />}

      {review && (
        <>
          <ReviewView
            review={review}
            corrections={corrections}
            locked={proposal !== null}
            rechecking={recheck.isPending}
            onSupplier={(id) => correct((c) => ({ ...c, supplier_id: id }))}
            onLine={setLine}
          />
          {recheck.isError && <p className="text-sm text-rose-600">{recheck.error.message}</p>}
          <div className="flex flex-wrap items-center gap-3">
            {!proposal && (
              <button
                type="button"
                disabled={!review.can_propose || recheck.isPending || propose.isPending}
                onClick={() => propose.mutate()}
                className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800 disabled:opacity-40"
              >
                {propose.isPending ? 'Preparing…' : 'Prepare draft purchase order'}
              </button>
            )}
            <button
              type="button"
              onClick={reset}
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm text-slate-700 hover:bg-slate-50"
            >
              Upload another
            </button>
            {!review.can_propose && !proposal && (
              <span className="text-sm text-rose-600">Resolve the errors above first.</span>
            )}
            {propose.isError && <span className="text-sm text-rose-600">{propose.error.message}</span>}
          </div>
          {proposal && <ProposalCard id={proposal.id} initial={proposal} />}
        </>
      )}
    </div>
  )
}

function UploadBox({ busy, error, onFile }: { busy: boolean; error?: string; onFile: (f: File) => void }) {
  const [dragging, setDragging] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        const file = e.dataTransfer.files[0]
        if (file && !busy) onFile(file)
      }}
      className={`rounded-xl border-2 border-dashed bg-white px-6 py-12 text-center ${
        dragging ? 'border-teal-500 bg-teal-50' : 'border-slate-300'
      }`}
    >
      {busy ? (
        <p className="text-sm text-slate-600" aria-live="polite">
          <span className="animate-pulse">Reading the document with AI…</span> this takes 5–30 seconds.
        </p>
      ) : (
        <>
          <p className="text-sm text-slate-700">Drop a PDF here, or</p>
          <button
            type="button"
            onClick={() => input.current?.click()}
            className="mt-2 rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800"
          >
            Choose a file
          </button>
          <p className="mt-3 text-xs text-slate-400">
            PDF up to 10 MB / 20 pages. Samples: <code>backend/samples/quotes/</code>
          </p>
        </>
      )}
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onFile(file)
          e.target.value = ''
        }}
      />
      {error && <p className="mt-3 text-sm text-rose-600">{error}</p>}
    </div>
  )
}

function FlagList({ flags }: { flags: Flag[] }) {
  if (!flags.length) return null
  return (
    <ul className="space-y-1">
      {flags.map((f, i) => (
        <li
          key={i}
          className={`rounded-md px-2 py-1 text-xs ${f.severity === 'error' ? 'bg-rose-50 text-rose-700' : 'bg-amber-50 text-amber-800'}`}
        >
          {f.severity === 'error' ? '✕' : '⚠'} {f.message}
        </li>
      ))}
    </ul>
  )
}

const MATCH_LABEL = { code: 'by code', name: 'by name', manual: 'chosen', none: 'no match' } as const

function ReviewView({
  review,
  corrections,
  locked,
  rechecking,
  onSupplier,
  onLine,
}: {
  review: QuoteReview
  corrections: Corrections
  locked: boolean
  rechecking: boolean
  onSupplier: (id: number) => void
  onLine: (index: number, patch: LineCorrection) => void
}) {
  const purchased = useProducts('purchased')
  const currency = review.company_currency
  const productOptions = (line: QuoteReview['lines'][number]) => {
    const seen = new Set(line.candidates.map((c) => c.id))
    return [...line.candidates, ...(purchased.data ?? []).filter((p) => !seen.has(p.id))]
  }

  return (
    <div className={`space-y-6 transition-opacity ${rechecking ? 'opacity-70' : ''}`}>
      <Card title={review.filename} subtitle={`Read by AI as a ${review.document_type}; every value below was checked by the server.`}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
          <div className="col-span-2">
            <dt className="text-xs text-slate-500">Supplier (printed: {review.supplier_name ?? '—'})</dt>
            <dd>
              <select
                disabled={locked}
                className="mt-0.5 w-full rounded-md border border-slate-300 bg-white px-2 py-1"
                value={corrections.supplier_id ?? review.supplier?.id ?? ''}
                onChange={(e) => onSupplier(Number(e.target.value))}
              >
                {!review.supplier && <option value="">— choose a vendor —</option>}
                {review.supplier_candidates.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
              <span className="text-xs text-slate-500">match: {review.supplier_match}</span>
            </dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Quote number</dt>
            <dd className="font-medium">{review.quote_number ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-xs text-slate-500">Date · currency</dt>
            <dd>
              {review.quote_date ?? '—'} · {review.currency ?? '?'}
            </dd>
          </div>
        </dl>
        <div className="mt-4">
          <FlagList flags={review.flags} />
        </div>
      </Card>

      <Card title="Lines" subtitle="Correct a product match or a misread figure; changes are re-checked automatically.">
        <div className="-mx-5 -my-2 overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead>
              <tr className="text-left text-xs text-slate-500">
                <th className="px-5 py-2 font-medium">Use</th>
                <th className="px-2 py-2 font-medium">As printed</th>
                <th className="px-2 py-2 font-medium">Product</th>
                <th className="px-2 py-2 text-right font-medium">Qty</th>
                <th className="px-2 py-2 text-right font-medium">Unit price</th>
                <th className="px-2 py-2 text-right font-medium">Line total</th>
                <th className="px-5 py-2 text-right font-medium">Agreed</th>
              </tr>
            </thead>
            <tbody>
              {review.lines.map((line) => (
                <tr key={line.index} className={`border-t border-slate-100 align-top ${line.include ? '' : 'opacity-50'}`}>
                  <td className="px-5 py-2">
                    <input
                      type="checkbox"
                      disabled={locked}
                      checked={line.include}
                      onChange={(e) => onLine(line.index, { include: e.target.checked })}
                      aria-label={`Include line ${line.index + 1}`}
                    />
                  </td>
                  <td className="px-2 py-2">
                    <p className="text-slate-800">{line.description}</p>
                    {line.supplier_product_code && <p className="text-xs text-slate-400">{line.supplier_product_code}</p>}
                    <div className="mt-1">
                      <FlagList flags={line.flags} />
                    </div>
                  </td>
                  <td className="px-2 py-2">
                    <select
                      disabled={locked || !line.include}
                      className="w-56 rounded-md border border-slate-300 bg-white px-2 py-1"
                      value={line.product?.id ?? ''}
                      onChange={(e) => onLine(line.index, { product_id: Number(e.target.value) })}
                    >
                      {!line.product && <option value="">— choose —</option>}
                      {productOptions(line).map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.code} · {p.name}
                        </option>
                      ))}
                    </select>
                    <p className="text-xs text-slate-500">{MATCH_LABEL[line.match]}</p>
                  </td>
                  <NumberCell disabled={locked || !line.include} value={line.quantity} onCommit={(v) => onLine(line.index, { quantity: v })} />
                  <NumberCell disabled={locked || !line.include} value={line.unit_price} onCommit={(v) => onLine(line.index, { unit_price: v })} />
                  <NumberCell disabled={locked || !line.include} value={line.line_total} onCommit={(v) => onLine(line.index, { line_total: v })} />
                  <td className="px-5 py-2 text-right text-slate-500 tabular-nums">
                    {line.agreed_price != null ? formatMoney(line.agreed_price, currency) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <dl className="mt-4 flex flex-wrap justify-end gap-x-8 gap-y-1 text-sm">
          <Total label="Printed subtotal" value={review.subtotal} currency={currency} />
          <Total label="Tax" value={review.tax} currency={currency} />
          <Total label="Printed total" value={review.total} currency={currency} />
          <Total label="Order total (included lines)" value={review.computed_total} currency={currency} strong />
        </dl>
      </Card>
    </div>
  )
}

function Total({ label, value, currency, strong }: { label: string; value: number | null; currency: string; strong?: boolean }) {
  return (
    <div className="text-right">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className={`tabular-nums ${strong ? 'font-semibold' : ''}`}>{value != null ? formatMoney(value, currency) : '—'}</dd>
    </div>
  )
}

/** A numeric input that reports a value when editing finishes (blur or Enter). */
function NumberCell({ value, disabled, onCommit }: { value: number | null; disabled: boolean; onCommit: (v: number) => void }) {
  return (
    <td className="px-2 py-2 text-right">
      <input
        key={value ?? 'empty'}
        type="number"
        step="any"
        min={0}
        disabled={disabled}
        defaultValue={value ?? ''}
        onBlur={(e) => {
          const v = Number(e.target.value)
          if (e.target.value !== '' && Number.isFinite(v) && v !== value) onCommit(v)
        }}
        onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
        className="w-24 rounded-md border border-slate-300 px-2 py-1 text-right tabular-nums disabled:bg-slate-50"
      />
    </td>
  )
}
