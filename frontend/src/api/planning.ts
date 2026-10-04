import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { getJson, postJson } from './client'
import type { BomTreeNode, PlanRequest, PlanResult, ProductKind, ProductSummary } from './types'

export const useProducts = (kind?: ProductKind) =>
  useQuery({
    queryKey: ['products', kind ?? 'all'],
    queryFn: () => getJson<ProductSummary[]>(kind ? `/api/products?kind=${kind}` : '/api/products'),
  })

export const useBomTree = (productId: number | null, quantity: number) =>
  useQuery({
    queryKey: ['bom-tree', productId, quantity],
    queryFn: () => getJson<BomTreeNode>(`/api/bom/${productId}/tree?quantity=${quantity}`),
    enabled: productId !== null,
    placeholderData: keepPreviousData,
  })

// The plan is a POST (it takes a JSON body) but it is a pure read, so it is
// modelled as a query: cached per input, refetched only when the input changes.
export const usePlan = (request: PlanRequest | null) =>
  useQuery({
    queryKey: ['plan', request],
    queryFn: () => postJson<PlanResult>('/api/planner/plan', request),
    enabled: request !== null,
    placeholderData: keepPreviousData,
  })
