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

// --- Planning (backend/app/schemas/planning.py) ---

export type ProductKind = 'manufactured' | 'kit' | 'purchased'
export type NodeStatus = 'ok' | 'build' | 'incoming' | 'short'

export interface ProductSummary {
  id: number
  code: string | null
  name: string
  kind: ProductKind
  on_hand: number
  free_qty: number
  incoming_qty: number
  unit_cost: number
}

export interface BomTreeNode {
  product_id: number
  code: string | null
  name: string
  kind: ProductKind
  level: number
  qty_per_unit: number
  quantity: number
  on_hand: number
  free_qty: number
  unit_cost: number
  status: NodeStatus
  children: BomTreeNode[]
}

export interface PlanRequest {
  product_id: number
  quantity: number
  count_incoming: boolean
}

export interface Requirement {
  product_id: number
  code: string | null
  name: string
  kind: ProductKind
  level: number
  gross_qty: number
  from_stock: number
  to_build: number
  to_buy: number
  covered_by_incoming: number
  shortage: number
  status: NodeStatus
}

export interface PurchaseLine {
  product_id: number
  code: string | null
  name: string
  shortage: number
  order_qty: number
  unit_price: number
  total: number
  lead_days: number | null
  note: string | null
}

export interface SupplierPurchase {
  supplier: string | null
  lines: PurchaseLine[]
  total: number
  max_lead_days: number | null
}

export interface MaterialBottleneck {
  product_id: number
  code: string | null
  name: string
  shortage: number
  supplier: string | null
  lead_days: number | null
}

export interface CapacityLoad {
  workcenter_id: number
  code: string | null
  name: string
  hours: number
  hours_per_day: number
  days: number
}

export interface PlanResult {
  product: ProductSummary
  quantity: number
  count_incoming: boolean
  requirements: Requirement[]
  purchases: SupplierPurchase[]
  purchase_total: number
  short_count: number
  material_bottlenecks: MaterialBottleneck[]
  capacity: CapacityLoad[]
  capacity_bottleneck: CapacityLoad | null
  estimated_days: number
  notes: string[]
}
