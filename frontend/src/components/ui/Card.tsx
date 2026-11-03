import type { HTMLAttributes, ReactNode } from 'react'
import { motion } from 'motion/react'
import { cn } from '../../lib/cn'
import { itemVariants } from '../../lib/motion'

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('card', className)} {...props} />
}

export function MotionCard({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <motion.div variants={itemVariants} className={cn('card', className)}>
      {children}
    </motion.div>
  )
}

export function CardHeader({ title, description, action, className }: { title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-start justify-between gap-4 px-5 pt-5 pb-3', className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold leading-tight">{title}</h2>
        {description && <p className="mt-1 text-sm text-ink-3">{description}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  )
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 pb-5', className)} {...props} />
}
