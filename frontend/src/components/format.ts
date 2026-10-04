export function formatMoney(value: number, currency: string | undefined, compact = false): string {
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: currency || 'USD',
    notation: compact ? 'compact' : 'standard',
    maximumFractionDigits: compact ? 1 : 0,
  }).format(value)
}

export function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' })
}

export function formatQty(value: number): string {
  return Number.isInteger(value) ? String(value) : value.toFixed(1)
}
