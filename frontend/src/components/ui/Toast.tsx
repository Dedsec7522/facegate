import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { cn } from '../../lib/cn'
import { spring } from '../../lib/motion'

type Tone = 'success' | 'error' | 'info' | 'warning'
interface Toast { id: number; tone: Tone; title: string; description?: string }
interface Api { toast: (t: Omit<Toast, 'id'>) => void; success: (title: string, description?: string) => void; error: (title: string, description?: string) => void; info: (title: string, description?: string) => void }

const Ctx = createContext<Api | null>(null)
const icons: Record<Tone, ReactNode> = {
  success: <CheckCircle2 className="size-5 text-accent-600" />,
  error: <XCircle className="size-5 text-red-600" />,
  info: <Info className="size-5 text-brand-500" />,
  warning: <AlertTriangle className="size-5 text-amber-600" />,
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([])
  const seq = useRef(0)
  const dismiss = useCallback((id: number) => setItems((l) => l.filter((t) => t.id !== id)), [])
  const toast = useCallback((t: Omit<Toast, 'id'>) => {
    const id = ++seq.current
    setItems((l) => [...l.slice(-3), { ...t, id }])
    setTimeout(() => dismiss(id), t.tone === 'error' ? 7000 : 4000)
  }, [dismiss])
  const api = useMemo<Api>(() => ({
    toast,
    success: (title, description) => toast({ tone: 'success', title, description }),
    error: (title, description) => toast({ tone: 'error', title, description }),
    info: (title, description) => toast({ tone: 'info', title, description }),
  }), [toast])

  return (
    <Ctx.Provider value={api}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-4 z-[100] flex flex-col items-center gap-2 px-4 sm:items-end sm:right-4">
        <AnimatePresence initial={false}>
          {items.map((t) => (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96, transition: { duration: 0.15 } }}
              transition={spring.snappy}
              className={cn('pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border border-line bg-surface p-3.5 shadow-pop')}
              role="status"
            >
              {icons[t.tone]}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-ink">{t.title}</p>
                {t.description && <p className="mt-0.5 text-[13px] text-ink-3">{t.description}</p>}
              </div>
              <button aria-label="Dismiss" onClick={() => dismiss(t.id)} className="rounded p-0.5 text-ink-3 hover:text-ink"><X className="size-4" /></button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </Ctx.Provider>
  )
}

export function useToast(): Api {
  const v = useContext(Ctx)
  if (!v) throw new Error('useToast outside ToastProvider')
  return v
}
