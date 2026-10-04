import { Link } from 'react-router'
import { useSummary } from '../api/dashboard'
import { useBomTree, useProducts } from '../api/planning'
import { BomFlow } from '../components/BomFlow'
import { QueryState } from '../components/Card'
import { PlanControls } from '../components/PlanControls'
import { NodeStatusBadge } from '../components/StateBadge'
import { formatMoney } from '../components/format'
import { usePlanParams } from '../hooks/usePlanParams'

export function BomExplorerPage() {
  const products = useProducts('manufactured')
  const { product, quantity, update } = usePlanParams(products.data)
  const tree = useBomTree(product?.id ?? null, quantity)
  const currency = useSummary().data?.currency

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">BOM explorer</h1>
        <p className="mt-0.5 text-sm text-slate-500">Multi-level bill of materials with stock, cost and shortage status for each part.</p>
      </div>
      <PlanControls productId={product?.id ?? null} quantity={quantity} onChange={update}>
        {product && (
          <Link
            to={`/planner?product=${product.id}&qty=${quantity}`}
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Plan this build →
          </Link>
        )}
      </PlanControls>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-slate-500">
        <span>Status for building the quantity above, after netting shared parts against free stock:</span>
        {(['ok', 'build', 'incoming', 'short'] as const).map((s) => (
          <NodeStatusBadge key={s} status={s} />
        ))}
      </div>

      <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
        {tree.data && (
          <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-slate-100 px-5 py-3">
            <h2 className="text-sm font-semibold text-slate-800">
              {tree.data.name} <span className="font-normal text-slate-400">{tree.data.code}</span>
            </h2>
            <p className="text-xs text-slate-500">
              Rolled-up unit cost (material + labour):{' '}
              <span className="font-medium text-slate-800">{formatMoney(tree.data.unit_cost, currency)}</span>
            </p>
          </header>
        )}
        <div className="h-[70vh] min-h-[420px] p-1">
          {tree.isSuccess ? (
            <BomFlow key={tree.data.product_id} tree={tree.data} currency={currency} />
          ) : (
            <div className="p-4">
              {/* The tree query waits for the product list, so surface that list's error too. */}
              {products.isError ? (
                <QueryState query={products}>{() => null}</QueryState>
              ) : (
                <QueryState query={tree}>{() => null}</QueryState>
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

