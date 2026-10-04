import { useSearchParams } from 'react-router'
import type { ProductSummary } from '../api/types'

export const MAX_QUANTITY = 10_000

/**
 * Product + quantity selection, stored in the URL (?product=32&qty=5) so a
 * view can be shared and the explorer can link straight into the planner.
 */
export function usePlanParams(products: ProductSummary[] | undefined) {
  const [params, setParams] = useSearchParams()
  const requested = Number(params.get('product'))
  const product = products?.find((p) => p.id === requested) ?? products?.[0] ?? null
  const qty = Number(params.get('qty'))
  const quantity = Number.isFinite(qty) && qty > 0 && qty <= MAX_QUANTITY ? qty : 1
  const countIncoming = params.get('incoming') !== '0'

  const update = (next: { product?: number; quantity?: number; countIncoming?: boolean }) => {
    const p = new URLSearchParams(params)
    if (next.product !== undefined) p.set('product', String(next.product))
    if (next.quantity !== undefined) p.set('qty', String(next.quantity))
    if (next.countIncoming !== undefined) p.set('incoming', next.countIncoming ? '1' : '0')
    setParams(p, { replace: true })
  }
  return { product, quantity, countIncoming, update }
}
