import { useManufacturingOrders } from '../api/dashboard'
import { Card, QueryState } from './Card'
import { formatDate, formatQty } from './format'
import { ProductionBadge } from './StateBadge'

export function ManufacturingOrdersTable() {
  const query = useManufacturingOrders()
  return (
    <Card title="Manufacturing orders" subtitle="Newest planned start first">
      <QueryState query={query} empty="No manufacturing orders.">
        {(orders) => (
          <div className="-mx-5 -my-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="px-5 py-2 font-medium">Order</th>
                  <th className="px-2 py-2 font-medium">Product</th>
                  <th className="px-2 py-2 text-right font-medium">Qty</th>
                  <th className="px-2 py-2 font-medium">Start</th>
                  <th className="px-5 py-2 font-medium">State</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td className="px-5 py-2 font-medium whitespace-nowrap">{o.name}</td>
                    <td className="px-2 py-2">
                      <span className="text-slate-700">{o.product_name}</span>
                      {o.product_code && <span className="ml-1.5 text-xs text-slate-400">{o.product_code}</span>}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{formatQty(o.quantity)}</td>
                    <td className="px-2 py-2 whitespace-nowrap text-slate-500">{formatDate(o.date_start)}</td>
                    <td className="px-5 py-2">
                      <ProductionBadge state={o.state} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </QueryState>
    </Card>
  )
}
