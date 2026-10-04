import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ownedPost, ownedRequest } from './client'

// Mirrors backend/app/schemas/actions.py

export interface ProposalLine {
  product_id: number
  code: string | null
  name: string
  quantity: number
  unit_price: number
  subtotal: number
  note: string | null
}

export interface ProposalOrder {
  supplier_id: number
  supplier: string
  partner_ref: string | null
  lead_days: number | null
  lines: ProposalLine[]
  total: number
}

export interface PurchaseProposal {
  kind: 'purchase_orders'
  summary: string
  currency: string
  orders: ProposalOrder[]
  total: number
  warnings: string[]
  quote: { review_id: string; quote_number: string | null; filename: string } | null
}

export interface CreatedPurchaseOrder {
  name: string
  supplier: string
  amount_total: number
  url: string | null
  simulated: boolean
}

export type ActionStatus = 'pending' | 'executing' | 'executed' | 'failed' | 'rejected' | 'expired'

export interface ActionView {
  id: string
  kind: string
  source: 'chat' | 'quote_intake'
  status: ActionStatus
  payload: PurchaseProposal
  created: CreatedPurchaseOrder[]
  error: string | null
  created_at: string
  expires_at: string
  decided_at: string | null
}

const key = (id: string) => ['action', id]

export const useAction = (id: string, initial?: ActionView) =>
  useQuery({
    queryKey: key(id),
    queryFn: () => ownedRequest<ActionView>(`/api/actions/${id}`),
    initialData: initial,
    staleTime: 10_000,
  })

/** Confirm or reject; the server's answer replaces the cached proposal. */
export function useDecideAction(id: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (decision: 'confirm' | 'reject') => ownedPost<ActionView>(`/api/actions/${id}/${decision}`),
    onSuccess: (action) => queryClient.setQueryData(key(id), action),
    // A 409 means someone (another tab) already decided: show the real state.
    onError: () => queryClient.invalidateQueries({ queryKey: key(id) }),
  })
}
