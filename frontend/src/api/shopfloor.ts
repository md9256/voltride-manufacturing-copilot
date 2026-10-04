import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { getJson, ownedPost } from './client'

// Mirrors backend/app/schemas/shopfloor.py

export type BarStatus = 'done' | 'in_progress' | 'planned' | 'late'

export interface TimelineBar {
  id: number
  operation: string
  production: string
  product_code: string | null
  quantity: number
  status: BarStatus
  start: string
  end: string
  planned_minutes: number
  actual_minutes: number
  variance_pct: number | null
}

export interface Timeline {
  start: string
  end: string
  now: string
  timezone: string
  rows: { workcenter_id: number; workcenter: string; bars: TimelineBar[] }[]
  unscheduled: { production: string; operation: string; workcenter: string; planned_minutes: number }[]
}

export interface WorkcenterVariance {
  workcenter_id: number
  workcenter: string
  finished: number
  planned_minutes: number
  actual_minutes: number
  variance_pct: number | null
}

export interface ShopfloorStats {
  since: string
  timezone: string
  overall: WorkcenterVariance
  by_workcenter: WorkcenterVariance[]
  top_overruns: {
    production: string
    product_code: string | null
    operation: string
    workcenter: string
    finished: string
    planned_minutes: number
    actual_minutes: number
    variance_pct: number
  }[]
  load: { day: string; workcenter_id: number; workcenter: string; planned_hours: number; capacity_hours: number }[]
}

export type SummaryLanguage = 'en' | 'zh-Hans' | 'zh-Hant'

export interface SummaryView {
  day: string
  language: SummaryLanguage
  text: string
  unverified_numbers: string[]
  facts: Record<string, unknown>
  cached: boolean
  provider: string
  model: string
  created_at: string
}

export const useTimeline = (daysBack: number, daysAhead: number) =>
  useQuery({
    queryKey: ['shopfloor', 'timeline', daysBack, daysAhead],
    queryFn: () => getJson<Timeline>(`/api/shopfloor/timeline?days_back=${daysBack}&days_ahead=${daysAhead}`),
    placeholderData: keepPreviousData,
  })

export const useShopfloorStats = (weeks: number) =>
  useQuery({
    queryKey: ['shopfloor', 'stats', weeks],
    queryFn: () => getJson<ShopfloorStats>(`/api/shopfloor/stats?weeks=${weeks}`),
  })

export const useSummary = () =>
  useMutation({
    mutationFn: (req: { day?: string; language: SummaryLanguage; regenerate?: boolean }) =>
      ownedPost<SummaryView>('/api/shopfloor/summary', req),
  })
