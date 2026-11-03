import { useEffect, useRef, type ReactNode } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { X } from 'lucide-react'
import { cn } from '../../lib/cn'
import { popVariants } from '../../lib/motion'
import { Button } from './Button'

export interface DialogProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  description?: ReactNode
  children?: ReactNode
  footer?: ReactNode
  size?: 'sm' | 'md' | 'lg'
}

export function Dialog({ open, onClose, title, description, children, footer, size = 'md' }: DialogProps) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    const prev = document.activeElement as HTMLElement | null
    setTimeout(() => ref.current?.querySelector<HTMLElement>('input,button,select,textarea,[tabindex]')?.focus(), 30)
    return () => {
      document.removeEventListener('keydown', onKey)
      prev?.focus?.()
    }
  }, [open, onClose])

  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 grid place-items-center p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.15 }}>
          <div className="absolute inset-0 bg-brand-950/50 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
          <motion.div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-labelledby="dlg-title"
            variants={popVariants}
            initial="hidden"
            animate="show"
            exit="exit"
            className={cn('relative w-full rounded-xl bg-surface shadow-pop border border-line', { sm: 'max-w-sm', md: 'max-w-lg', lg: 'max-w-2xl' }[size])}
          >
            <div className="flex items-start justify-between gap-4 px-6 pt-5 pb-3">
              <div>
                <h2 id="dlg-title" className="text-lg font-semibold">{title}</h2>
                {description && <p className="mt-1 text-sm text-ink-3">{description}</p>}
              </div>
              <Button variant="ghost" size="icon" aria-label="Close" onClick={onClose}><X className="size-4" /></Button>
            </div>
            {children && <div className="px-6 pb-5">{children}</div>}
            {footer && <div className="flex justify-end gap-2 border-t border-line px-6 py-4">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  )
}

export function ConfirmDialog({ open, onClose, onConfirm, title, description, confirmLabel = 'Confirm', danger, loading }: {
  open: boolean; onClose: () => void; onConfirm: () => void; title: ReactNode; description?: ReactNode; confirmLabel?: string; danger?: boolean; loading?: boolean
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title} description={description} size="sm" footer={
      <>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={onConfirm} loading={loading}>{confirmLabel}</Button>
      </>
    } />
  )
}
