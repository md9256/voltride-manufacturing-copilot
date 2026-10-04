import { useState, type ReactNode } from 'react'
import { useProducts } from '../api/planning'
import { MAX_QUANTITY } from '../hooks/usePlanParams'

interface PlanControlsProps {
  productId: number | null
  quantity: number
  onChange: (next: { product?: number; quantity?: number }) => void
  children?: ReactNode
}

// Keyed by the applied quantity: when it changes (e.g. via the URL) the form
// remounts with fresh input text instead of syncing state in an effect.
export const PlanControls = (props: PlanControlsProps) => <PlanControlsForm key={props.quantity} {...props} />

function PlanControlsForm({ children, onChange, productId, quantity }: PlanControlsProps) {
  const products = useProducts('manufactured')
  // Keep the typed text separate from the applied quantity, so half-typed or
  // invalid input never triggers a request.
  const [qtyText, setQtyText] = useState(String(quantity))
  const parsed = Number(qtyText)
  const valid = qtyText.trim() !== '' && Number.isFinite(parsed) && parsed > 0 && parsed <= MAX_QUANTITY

  return (
    <form
      className="flex flex-wrap items-end gap-3 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"
      onSubmit={(e) => {
        e.preventDefault()
        if (valid) onChange({ quantity: parsed })
      }}
    >
      <label className="flex min-w-0 flex-1 basis-64 flex-col gap-1 text-xs font-medium text-slate-600">
        Product
        <select
          className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
          value={productId ?? ''}
          disabled={!products.data}
          onChange={(e) => onChange({ product: Number(e.target.value) })}
        >
          {!products.data && <option>Loading products…</option>}
          {products.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.code ? `${p.code} · ` : ''}
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex w-28 flex-col gap-1 text-xs font-medium text-slate-600">
        Quantity
        <input
          type="number"
          inputMode="decimal"
          min={1}
          max={MAX_QUANTITY}
          step="any"
          className={`rounded-lg border px-3 py-2 text-sm tabular-nums text-slate-900 ${
            valid ? 'border-slate-300' : 'border-rose-400'
          }`}
          value={qtyText}
          onChange={(e) => setQtyText(e.target.value)}
          aria-invalid={!valid}
        />
      </label>
      <button
        type="submit"
        disabled={!valid || parsed === quantity}
        className="rounded-lg bg-teal-700 px-4 py-2 text-sm font-medium text-white hover:bg-teal-800 disabled:cursor-not-allowed disabled:opacity-40"
      >
        Update
      </button>
      {children}
      {!valid && <p className="w-full text-xs text-rose-600">Enter a quantity between 1 and {MAX_QUANTITY.toLocaleString()}.</p>}
    </form>
  )
}
