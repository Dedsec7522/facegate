import type { HTMLAttributes, ReactNode } from 'react'
import { motion, useReducedMotion, useSpring, useTransform } from 'motion/react'
import { useEffect } from 'react'
import { cn } from '../../lib/cn'
import { initials } from '../../lib/format'

export function Skeleton({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('animate-pulse rounded-md bg-surface-3', className)} aria-hidden {...props} />
}

export function PageHeader({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow && <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-ink-3">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-ink-3">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function EmptyState({ icon, title, description, action }: { icon?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && <div className="mb-1 grid size-12 place-items-center rounded-full bg-surface-3 text-ink-3">{icon}</div>}
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="max-w-sm text-[13px] text-ink-3">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

export function Avatar({ name, src, size = 'md', className }: { name: string | null | undefined; src?: string | null; size?: 'sm' | 'md' | 'lg' | 'xl'; className?: string }) {
  const s = { sm: 'size-7 text-[11px]', md: 'size-9 text-xs', lg: 'size-12 text-sm', xl: 'size-20 text-xl' }[size]
  return (
    <span className={cn('inline-grid shrink-0 place-items-center overflow-hidden rounded-full bg-brand-100 font-semibold text-brand-700 dark:bg-brand-800 dark:text-brand-100', s, className)}>
      {src ? <img src={src} alt="" className="size-full object-cover" /> : initials(name)}
    </span>
  )
}

/** Animated number for KPI tiles. Respects reduced motion. */
export function CountUp({ value, decimals = 0, suffix = '', className }: { value: number; decimals?: number; suffix?: string; className?: string }) {
  const reduce = useReducedMotion()
  const spring = useSpring(reduce ? value : 0, { stiffness: 90, damping: 20, mass: 0.6 })
  const text = useTransform(spring, (v) => `${v.toFixed(decimals)}${suffix}`)
  useEffect(() => { spring.set(value) }, [value, spring])
  return <motion.span className={cn('tabular', className)}>{text}</motion.span>
}

export function Stat({ label, value, delta, tone = 'neutral', icon, decimals, suffix }: { label: string; value: number; delta?: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'danger'; icon?: ReactNode; decimals?: number; suffix?: string }) {
  const toneCls = { neutral: 'text-ink', success: 'text-accent-600', warning: 'text-amber-600', danger: 'text-red-600' }[tone]
  return (
    <div className="card flex items-center gap-4 p-5">
      {icon && <div className="grid size-11 shrink-0 place-items-center rounded-lg bg-surface-3 text-ink-2">{icon}</div>}
      <div className="min-w-0">
        <p className="text-[13px] font-medium text-ink-3">{label}</p>
        <p className={cn('mt-0.5 text-2xl font-semibold leading-none tracking-tight', toneCls)}>
          <CountUp value={value} decimals={decimals} suffix={suffix} />
        </p>
        {delta && <p className="mt-1 text-xs text-ink-3">{delta}</p>}
      </div>
    </div>
  )
}

export function Tabs<T extends string>({ value, onChange, items, className }: { value: T; onChange: (v: T) => void; items: Array<{ value: T; label: ReactNode; count?: number }>; className?: string }) {
  return (
    <div role="tablist" className={cn('inline-flex rounded-lg bg-surface-3 p-1', className)}>
      {items.map((it) => {
        const active = it.value === value
        return (
          <button key={it.value} role="tab" aria-selected={active} onClick={() => onChange(it.value)}
            className={cn('relative rounded-md px-3 py-1.5 text-sm font-medium transition-colors', active ? 'text-ink' : 'text-ink-3 hover:text-ink')}>
            {active && <motion.span layoutId="tab-pill" className="absolute inset-0 rounded-md bg-surface shadow-card" transition={{ type: 'spring', stiffness: 500, damping: 40 }} />}
            <span className="relative">{it.label}{it.count !== undefined && <span className="ml-1.5 text-xs text-ink-3">{it.count}</span>}</span>
          </button>
        )
      })}
    </div>
  )
}

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('overflow-x-auto scrollbar-thin', className)}>
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  )
}
export const Th = ({ children, className, ...p }: HTMLAttributes<HTMLTableCellElement>) => (
  <th className={cn('sticky top-0 bg-surface px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-ink-3 border-b border-line', className)} {...p}>{children}</th>
)
export const Td = ({ children, className, ...p }: HTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn('px-4 py-3 align-middle border-b border-line/70', className)} {...p}>{children}</td>
)

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <div className="flex items-center justify-between px-4 py-3 text-[13px] text-ink-3">
      <span>Page {page} of {pages} · {total} total</span>
      <div className="flex gap-1">
        <button disabled={page <= 1} onClick={() => onPage(page - 1)} className="rounded-md border border-line px-2.5 py-1 hover:bg-surface-3 disabled:opacity-40">Previous</button>
        <button disabled={page >= pages} onClick={() => onPage(page + 1)} className="rounded-md border border-line px-2.5 py-1 hover:bg-surface-3 disabled:opacity-40">Next</button>
      </div>
    </div>
  )
}
