import { useOpenSalesOrders, useSummary } from '../api/dashboard'
import { Card, QueryState } from './Card'
import { formatDate, formatMoney } from './format'
import { SaleBadge } from './StateBadge'

export function SalesOrdersTable() {
  const query = useOpenSalesOrders()
  const currency = useSummary().data?.currency
  return (
    <Card title="Open sales orders" subtitle="Quotations and confirmed orders not yet fully shipped">
      <QueryState query={query} empty="No open sales orders.">
        {(orders) => (
          <div className="-mx-5 -my-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-500">
                  <th className="px-5 py-2 font-medium">Order</th>
                  <th className="px-2 py-2 font-medium">Customer</th>
                  <th className="px-2 py-2 font-medium">Date</th>
                  <th className="px-2 py-2 font-medium">Status</th>
                  <th className="px-5 py-2 text-right font-medium">Total</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {orders.map((o) => (
                  <tr key={o.id}>
                    <td className="px-5 py-2 font-medium whitespace-nowrap">{o.name}</td>
                    <td className="px-2 py-2 text-slate-700">{o.customer}</td>
                    <td className="px-2 py-2 whitespace-nowrap text-slate-500">{formatDate(o.date_order)}</td>
                    <td className="px-2 py-2">
                      <SaleBadge state={o.state} delivery={o.delivery_status} />
                    </td>
                    <td className="px-5 py-2 text-right tabular-nums">{formatMoney(o.amount_total, currency)}</td>
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
