import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '../../lib/cn'
import type { DayStatus } from '../../lib/types'

type Tone = 'neutral' | 'brand' | 'success' | 'warning' | 'danger' | 'info'

const tones: Record<Tone, string> = {
  neutral: 'bg-surface-3 text-ink-2 border-line',
  brand: 'bg-brand-50 text-brand-700 border-brand-100 dark:bg-brand-800/40 dark:text-brand-200 dark:border-brand-700',
  success: 'bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-900/30 dark:text-emerald-300 dark:border-emerald-800',
  warning: 'bg-amber-50 text-amber-700 border-amber-100 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800',
  danger: 'bg-red-50 text-red-700 border-red-100 dark:bg-red-900/30 dark:text-red-300 dark:border-red-800',
  info: 'bg-sky-50 text-sky-700 border-sky-100 dark:bg-sky-900/30 dark:text-sky-300 dark:border-sky-800',
}

export function Badge({ tone = 'neutral', className, dot, children, ...props }: HTMLAttributes<HTMLSpanElement> & { tone?: Tone; dot?: boolean; children: ReactNode }) {
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap', tones[tone], className)} {...props}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  )
}

export const dayStatusTone: Record<DayStatus, Tone> = { present: 'success', late: 'warning', missing_checkout: 'danger', absent: 'neutral', corrected: 'info' }
export const dayStatusLabel: Record<DayStatus, string> = { present: 'Present', late: 'Late', missing_checkout: 'Missing check-out', absent: 'Absent', corrected: 'Corrected' }

export function StatusBadge({ status }: { status: DayStatus }) {
  return <Badge tone={dayStatusTone[status]} dot>{dayStatusLabel[status]}</Badge>
}
