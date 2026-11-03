import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

interface FieldShellProps {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  required?: boolean
  className?: string
  id: string
  children: ReactNode
}

function FieldShell({ label, hint, error, required, className, id, children }: FieldShellProps) {
  return (
    <div className={cn('flex flex-col gap-1.5', className)}>
      {label && (
        <label htmlFor={id} className="text-[13px] font-medium text-ink-2">
          {label}
          {required && <span className="ml-0.5 text-red-500" aria-hidden>*</span>}
        </label>
      )}
      {children}
      {error ? (
        <p id={`${id}-err`} role="alert" className="text-[13px] text-red-600 dark:text-red-400">{error}</p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-[13px] text-ink-3">{hint}</p>
      ) : null}
    </div>
  )
}

const inputCls =
  'h-10 w-full rounded-md border border-line-2 bg-surface px-3 text-ink placeholder:text-ink-3/70 transition-shadow ' +
  'focus:border-brand-500 focus:ring-2 focus:ring-brand-500/30 focus:outline-none disabled:opacity-60 disabled:bg-surface-3 ' +
  'aria-[invalid=true]:border-red-500 aria-[invalid=true]:focus:ring-red-500/30'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  wrapperClassName?: string
  leftIcon?: ReactNode
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ label, hint, error, required, wrapperClassName, className, leftIcon, id, ...props }, ref) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} className={wrapperClassName} id={fid}>
      <div className="relative">
        {leftIcon && <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-3">{leftIcon}</span>}
        <input
          ref={ref}
          id={fid}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? `${fid}-err` : hint ? `${fid}-hint` : undefined}
          required={required}
          className={cn(inputCls, leftIcon && 'pl-9', className)}
          {...props}
        />
      </div>
    </FieldShell>
  )
})

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  wrapperClassName?: string
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select({ label, hint, error, required, wrapperClassName, className, id, children, ...props }, ref) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} className={wrapperClassName} id={fid}>
      <select ref={ref} id={fid} aria-invalid={error ? true : undefined} required={required} className={cn(inputCls, 'pr-8', className)} {...props}>
        {children}
      </select>
    </FieldShell>
  )
})

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  wrapperClassName?: string
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea({ label, hint, error, required, wrapperClassName, className, id, ...props }, ref) {
  const auto = useId()
  const fid = id ?? auto
  return (
    <FieldShell label={label} hint={hint} error={error} required={required} className={wrapperClassName} id={fid}>
      <textarea ref={ref} id={fid} aria-invalid={error ? true : undefined} required={required} className={cn(inputCls, 'h-auto min-h-24 py-2', className)} {...props} />
    </FieldShell>
  )
})

export function Switch({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; description?: ReactNode; disabled?: boolean }) {
  const id = useId()
  return (
    <label htmlFor={id} className={cn('flex items-start justify-between gap-4 py-2', disabled && 'opacity-60')}>
      <span>
        <span className="block text-sm font-medium text-ink">{label}</span>
        {description && <span className="block text-[13px] text-ink-3">{description}</span>}
      </span>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={cn('relative mt-0.5 h-6 w-11 shrink-0 rounded-full transition-colors', checked ? 'bg-accent-600' : 'bg-line-2')}
      >
        <span className={cn('absolute top-0.5 left-0.5 size-5 rounded-full bg-white shadow transition-transform', checked && 'translate-x-5')} />
      </button>
    </label>
  )
}
