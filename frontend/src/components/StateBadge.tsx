import type { DeliveryStatus, ProductionState, SaleState } from '../api/types'

const TONES = {
  grey: 'bg-slate-100 text-slate-700',
  blue: 'bg-sky-50 text-sky-700',
  amber: 'bg-amber-50 text-amber-700',
  green: 'bg-emerald-50 text-emerald-700',
  red: 'bg-rose-50 text-rose-700',
} as const

const PRODUCTION: Record<ProductionState, [string, keyof typeof TONES]> = {
  draft: ['Draft', 'grey'],
  confirmed: ['Confirmed', 'blue'],
  progress: ['In progress', 'amber'],
  to_close: ['To close', 'amber'],
  done: ['Done', 'green'],
  cancel: ['Cancelled', 'red'],
}

const SALE: Record<SaleState, [string, keyof typeof TONES]> = {
  draft: ['Quotation', 'grey'],
  sent: ['Quotation sent', 'grey'],
  sale: ['Confirmed', 'blue'],
  cancel: ['Cancelled', 'red'],
}

const DELIVERY: Record<DeliveryStatus, string> = {
  pending: 'Not shipped',
  started: 'Shipping',
  partial: 'Partly shipped',
  full: 'Shipped',
}

function Badge({ label, tone }: { label: string; tone: keyof typeof TONES }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap ${TONES[tone]}`}>
      {label}
    </span>
  )
}

export const ProductionBadge = ({ state }: { state: ProductionState }) => {
  const [label, tone] = PRODUCTION[state]
  return <Badge label={label} tone={tone} />
}

export const SaleBadge = ({ state, delivery }: { state: SaleState; delivery: DeliveryStatus | null }) => {
  const [label, tone] = SALE[state]
  // For confirmed orders the delivery status is the more useful signal.
  if (state === 'sale' && delivery) return <Badge label={DELIVERY[delivery]} tone={delivery === 'full' ? 'green' : 'blue'} />
  return <Badge label={label} tone={tone} />
}

