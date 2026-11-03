import { motion } from 'motion/react'
import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme, type Theme } from '../../lib/theme'
import { cn } from '../../lib/cn'

const items: Array<{ value: Theme; label: string; icon: typeof Sun }> = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme()
  return (
    <div role="radiogroup" aria-label="Colour theme" className={cn('inline-flex rounded-full border border-line bg-surface-2 p-0.5', className)}>
      {items.map((it) => {
        const active = it.value === theme
        return (
          <button key={it.value} role="radio" aria-checked={active} aria-label={it.label} title={it.label} onClick={() => setTheme(it.value)}
            className={cn('relative grid size-7 place-items-center rounded-full text-ink-3 transition-colors hover:text-ink', active && 'text-ink')}>
            {active && <motion.span layoutId="theme-pill" className="absolute inset-0 rounded-full bg-surface shadow-card" transition={{ type: 'spring', stiffness: 500, damping: 38 }} />}
            <motion.span className="relative" animate={{ rotate: active ? 0 : -15, scale: active ? 1 : 0.9 }} transition={{ type: 'spring', stiffness: 400, damping: 24 }}>
              <it.icon className="size-3.5" />
            </motion.span>
          </button>
        )
      })}
    </div>
  )
}
