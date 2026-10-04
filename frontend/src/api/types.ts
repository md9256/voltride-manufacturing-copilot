// Mirrors backend/app/schemas. Datetimes arrive as ISO strings in UTC.

export type SaleState = 'draft' | 'sent' | 'sale' | 'cancel'
export type DeliveryStatus = 'pending' | 'started' | 'partial' | 'full'
export type ProductionState = 'draft' | 'confirmed' | 'progress' | 'to_close' | 'done' | 'cancel'

export interface SaleOrder {
  id: number
  name: string
  customer: string
  state: SaleState
  delivery_status: DeliveryStatus | null
  date_order: string
  commitment_date: string | null
  amount_total: number
}

export interface ManufacturingOrder {
  id: number
  name: string
  product_code: string | null
  product_name: string
  quantity: number
  state: ProductionState
  date_start: string
  date_finished: string | null
  origin: string | null
}

export interface StockLevel {
  product_id: number
  product_code: string | null
  product_name: string
  on_hand: number
  min_qty: number
  max_qty: number
}

export interface WeeklyOrders {
  week_start: string // YYYY-MM-DD, a Monday
  order_count: number
  revenue: number
}

export interface DashboardSummary {
  currency: string
  open_sales_count: number
  open_sales_value: number
  quotations_count: number
  manufacturing_by_state: Partial<Record<ProductionState, number>>
  active_manufacturing_count: number
  low_stock_count: number
}

export interface Health {
  status: 'ok' | 'degraded'
  odoo: { mode: string; reachable: boolean; version: string | null; error: string | null }
}
