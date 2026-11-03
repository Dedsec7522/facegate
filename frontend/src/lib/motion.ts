/** Shared motion tokens so every transition in the product shares one rhythm. */
import type { Transition, Variants } from 'motion/react'

export const ease = {
  out: [0.25, 1, 0.5, 1] as const,
  inOut: [0.76, 0, 0.24, 1] as const,
}

export const spring = {
  snappy: { type: 'spring', stiffness: 520, damping: 38, mass: 0.8 } satisfies Transition,
  gentle: { type: 'spring', stiffness: 220, damping: 28 } satisfies Transition,
  card: { type: 'spring', visualDuration: 0.35, bounce: 0.12 } satisfies Transition,
}

export const duration = { fast: 0.15, base: 0.24, slow: 0.4 }

export const pageVariants: Variants = {
  initial: { opacity: 0, y: 8 },
  enter: { opacity: 1, y: 0, transition: { duration: duration.base, ease: ease.out } },
  exit: { opacity: 0, y: -6, transition: { duration: duration.fast, ease: ease.inOut } },
}

export const listVariants: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.045, delayChildren: 0.03 } },
}

export const itemVariants: Variants = {
  hidden: { opacity: 0, y: 10, scale: 0.985 },
  show: { opacity: 1, y: 0, scale: 1, transition: spring.card },
}

export const fadeVariants: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: duration.base } },
  exit: { opacity: 0, transition: { duration: duration.fast } },
}

export const popVariants: Variants = {
  hidden: { opacity: 0, scale: 0.96, y: 6 },
  show: { opacity: 1, scale: 1, y: 0, transition: spring.snappy },
  exit: { opacity: 0, scale: 0.98, y: 4, transition: { duration: duration.fast } },
}
