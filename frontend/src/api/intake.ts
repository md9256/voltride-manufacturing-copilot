import { ApiError, clientId, errorFrom, ownedPost } from './client'
import type { ActionView } from './actions'

// Mirrors backend/app/schemas/intake.py

export interface Flag {
  severity: 'error' | 'warning'
  field: string
  message: string
}

export interface Option {
  id: number
  code: string | null
  name: string
}

export interface LineReview {
  index: number
  description: string
  supplier_product_code: string | null
  quantity: number | null
  unit_price: number | null
  line_total: number | null
  include: boolean
  product: Option | null
  match: 'code' | 'name' | 'manual' | 'none'
  candidates: Option[]
  agreed_price: number | null
  flags: Flag[]
}

export interface QuoteReview {
  id: string
  filename: string
  document_type: string
  supplier_name: string | null
  supplier: Option | null
  supplier_match: 'exact' | 'fuzzy' | 'manual' | 'none'
  supplier_candidates: Option[]
  quote_number: string | null
  quote_date: string | null
  currency: string | null
  company_currency: string
  lines: LineReview[]
  subtotal: number | null
  tax: number | null
  total: number | null
  computed_total: number
  flags: Flag[]
  can_propose: boolean
}

export interface LineCorrection {
  product_id?: number
  quantity?: number
  unit_price?: number
  line_total?: number
  include?: boolean
}

export interface Corrections {
  supplier_id?: number
  lines: Record<number, LineCorrection>
}

export async function uploadQuote(file: File): Promise<QuoteReview> {
  const form = new FormData()
  form.append('file', file)
  let response: Response
  try {
    response = await fetch('/api/intake/quotes', { method: 'POST', body: form, headers: { 'X-Client-Id': clientId() } })
  } catch {
    throw new ApiError(0, 'Cannot reach the server.')
  }
  if (!response.ok) throw await errorFrom(response)
  return response.json()
}

export const recheckQuote = (id: string, corrections: Corrections) =>
  ownedPost<QuoteReview>(`/api/intake/quotes/${id}/review`, corrections)

export const proposeQuote = (id: string, corrections: Corrections) =>
  ownedPost<ActionView>(`/api/intake/quotes/${id}/propose`, corrections)
