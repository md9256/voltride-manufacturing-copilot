import { useQuery } from '@tanstack/react-query'
import { getJson } from './client'
import type { DashboardSummary, Health, ManufacturingOrder, SaleOrder, StockLevel, WeeklyOrders } from './types'

// One hook per endpoint. TanStack Query fetches them in parallel and caches
// by key, so components can call the same hook without duplicate requests.

export const useHealth = () =>
  useQuery({ queryKey: ['health'], queryFn: () => getJson<Health>('/api/health'), refetchInterval: 60_000 })

export const useSummary = () =>
  useQuery({ queryKey: ['dashboard', 'summary'], queryFn: () => getJson<DashboardSummary>('/api/dashboard/summary') })

export const useOpenSalesOrders = () =>
  useQuery({ queryKey: ['dashboard', 'sales-orders'], queryFn: () => getJson<SaleOrder[]>('/api/dashboard/sales-orders') })

export const useManufacturingOrders = () =>
  useQuery({
    queryKey: ['dashboard', 'manufacturing-orders'],
    queryFn: () => getJson<ManufacturingOrder[]>('/api/dashboard/manufacturing-orders'),
  })

export const useLowStock = () =>
  useQuery({ queryKey: ['dashboard', 'low-stock'], queryFn: () => getJson<StockLevel[]>('/api/dashboard/low-stock') })

export const useOrdersOverTime = (weeks: number) =>
  useQuery({
    queryKey: ['dashboard', 'orders-over-time', weeks],
    queryFn: () => getJson<WeeklyOrders[]>(`/api/dashboard/orders-over-time?weeks=${weeks}`),
  })
