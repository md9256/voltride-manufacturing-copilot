import { KpiTiles } from '../components/KpiTiles'
import { LowStockList } from '../components/LowStockList'
import { ManufacturingOrdersTable } from '../components/ManufacturingOrdersTable'
import { OrdersChart } from '../components/OrdersChart'
import { SalesOrdersTable } from '../components/SalesOrdersTable'

export function DashboardPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Production overview</h1>
      </div>
      <KpiTiles />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <OrdersChart />
        </div>
        <LowStockList />
      </div>
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <SalesOrdersTable />
        <ManufacturingOrdersTable />
      </div>
    </div>
  )
}
