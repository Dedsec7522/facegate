import { useEffect, useId, useRef } from 'react'
import { motion, useMotionValue, useSpring, useTransform } from 'motion/react'
import { ease } from '../../lib/motion'

export type ErrorKind = '404' | '403' | '500' | 'offline'

const TONE: Record<ErrorKind, { stroke: string; text: string }> = {
  '404': { stroke: 'stroke-brand-600 dark:stroke-brand-400', text: 'text-brand-500' },
  '403': { stroke: 'stroke-amber-500', text: 'text-amber-500' },
  '500': { stroke: 'stroke-red-500', text: 'text-red-500' },
  offline: { stroke: 'stroke-ink-3', text: 'text-ink-3' },
}

// The four viewfinder corners of the FaceGate logo, drawn around the face.
const BRACKETS = [
  'M10 52V34a24 24 0 0 1 24-24h18',
  'M148 10h18a24 24 0 0 1 24 24v18',
  'M190 148v18a24 24 0 0 1-24 24h-18',
  'M52 190H34a24 24 0 0 1-24-24v-18',
]
const EYES = [72, 128]
const CHEEKS = [54, 146]
const FEATURE = 'stroke-ink fill-none'

/**
 * The face scanner that could not find the page. Its pupils follow the pointer (and wander on their own on touch
 * screens), it blinks, and a scan line sweeps over it; pressing it scans again. The expression depends on the error:
 * puzzled (404), stern (403), knocked out and glitching (500), asleep (offline).
 */
export function ScannerFace({ kind, scanKey, onScan }: { kind: ErrorKind; scanKey: number; onScan: () => void }) {
  const ref = useRef<HTMLButtonElement>(null)
  const clip = useId()
  const grad = useId()
  const tx = useMotionValue(0)
  const ty = useMotionValue(0)
  const px = useSpring(tx, { stiffness: 260, damping: 20, mass: 0.6 })
  const py = useSpring(ty, { stiffness: 260, damping: 20, mass: 0.6 })
  const tilt = useTransform(px, [-8, 8], [-4, 4])
  const tone = TONE[kind]
  const looks = kind === '404' || kind === '403'

  useEffect(() => {
    if (!looks) return
    let last = 0
    const move = (e: PointerEvent) => {
      const el = ref.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const dx = e.clientX - (r.left + r.width / 2)
      const dy = e.clientY - (r.top + r.height / 2)
      const d = Math.hypot(dx, dy) || 1
      const reach = Math.min(1, d / 220)
      tx.set((dx / d) * 8 * reach)
      ty.set((dy / d) * 7 * reach)
      last = performance.now()
    }
    // Nothing to follow (touch screen, idle mouse): look around for the page instead.
    const idle = window.setInterval(() => {
      if (performance.now() - last < 2500) return
      const a = Math.random() * Math.PI * 2
      tx.set(Math.cos(a) * 7)
      ty.set(Math.sin(a) * 5)
    }, 1400)
    window.addEventListener('pointermove', move)
    return () => {
      window.removeEventListener('pointermove', move)
      window.clearInterval(idle)
    }
  }, [looks, tx, ty])

  return (
    <motion.button
      ref={ref}
      type="button"
      onClick={onScan}
      aria-label="Scan again"
      title="Scan again"
      whileHover={{ scale: 1.05 }}
      whileTap={{ scale: 0.92, rotate: -4 }}
      transition={{ type: 'spring', stiffness: 420, damping: 16 }}
      className="relative block aspect-square w-full rounded-[26%]"
    >
      <motion.svg viewBox="0 0 200 200" className="size-full overflow-visible" style={{ rotate: tilt }}>
        <defs>
          <clipPath id={clip}><rect x="22" y="22" width="156" height="156" rx="40" /></clipPath>
          <linearGradient id={grad} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor="currentColor" stopOpacity="0" />
            <stop offset="1" stopColor="currentColor" stopOpacity="0.32" />
          </linearGradient>
        </defs>

        <rect x="22" y="22" width="156" height="156" rx="40" className="fill-surface stroke-line-2" strokeWidth="2" />

        <motion.g
          animate={kind === '500' ? { x: [0, -3, 4, -2, 0], y: [0, 2, -2, 1, 0] } : { scale: [1, 1.035, 1] }}
          transition={kind === '500' ? { duration: 0.35, repeat: Infinity, repeatDelay: 1.9 } : { duration: 3.2, repeat: Infinity, ease: 'easeInOut' }}
        >
          {BRACKETS.map((d, i) => (
            <motion.path key={d} d={d} className={tone.stroke} strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" fill="none"
              initial={{ pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 1 }}
              transition={{ delay: 0.3 + i * 0.09, duration: 0.55, ease: ease.out }} />
          ))}
        </motion.g>

        <g clipPath={`url(#${clip})`}>
          {kind !== '500' && CHEEKS.map((x) => <circle key={x} cx={x} cy="122" r="9" className="fill-pink-300/45" />)}

          {looks && (
            <>
              <motion.g animate={{ scaleY: [1, 1, 0.08, 1] }} transition={{ duration: 4.2, times: [0, 0.93, 0.965, 1], repeat: Infinity }}>
                {EYES.map((x) => (
                  <g key={x}>
                    <circle cx={x} cy="94" r="17" className="fill-white stroke-line-2" strokeWidth="2" />
                    <motion.circle cx={x} cy="94" r={kind === '403' ? 6 : 7.5} fill="#1e1b2e" style={{ x: px, y: py }} />
                    <motion.circle cx={x + 2.5} cy="91.5" r="2.2" fill="#fff" style={{ x: px, y: py }} />
                  </g>
                ))}
              </motion.g>
              {kind === '404' ? (
                <>
                  <motion.path d="M56 66q14-9 28-4" className={FEATURE} strokeWidth="5" strokeLinecap="round"
                    animate={{ y: [0, -5, 0], rotate: [0, -6, 0] }} transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }} />
                  <path d="M116 68q14-3 28 4" className={FEATURE} strokeWidth="5" strokeLinecap="round" />
                  <motion.ellipse cx="100" cy="140" rx="7" className="fill-ink" animate={{ ry: [8, 5, 8] }} transition={{ duration: 2.6, repeat: Infinity, ease: 'easeInOut' }} />
                </>
              ) : (
                <>
                  <path d="M54 70l32 9M146 70l-32 9" className={FEATURE} strokeWidth="6" strokeLinecap="round" />
                  <motion.path d="M80 142h40" className={FEATURE} strokeWidth="5" strokeLinecap="round"
                    animate={{ x: [0, -4, 4, -4, 4, 0] }} transition={{ duration: 0.7, repeat: Infinity, repeatDelay: 2.4 }} />
                </>
              )}
            </>
          )}

          {kind === '500' && (
            <>
              {EYES.map((x, i) => (
                <motion.path key={x} d={`M${x - 11} 83l22 22M${x + 11} 83l-22 22`} className={FEATURE} strokeWidth="6" strokeLinecap="round"
                  animate={{ rotate: [0, i ? -14 : 14, 0] }} transition={{ duration: 1.4, repeat: Infinity, ease: 'easeInOut', delay: i * 0.2 }} />
              ))}
              <motion.path d="M70 142l10-8 10 8 10-8 10 8 10-8 10 8" className={FEATURE} strokeWidth="5" strokeLinecap="round" strokeLinejoin="round"
                animate={{ x: [0, 3, -3, 0] }} transition={{ duration: 0.5, repeat: Infinity, repeatDelay: 1.2 }} />
            </>
          )}

          {kind === 'offline' && (
            <>
              <path d="M58 94q14 11 28 0M114 94q14 11 28 0" className={FEATURE} strokeWidth="5" strokeLinecap="round" />
              <motion.ellipse cx="100" cy="140" className="fill-ink" animate={{ rx: [5, 8, 5], ry: [3, 7, 3] }} transition={{ duration: 3.4, repeat: Infinity, ease: 'easeInOut' }} />
            </>
          )}

          {kind !== 'offline' && (
            <motion.g key={scanKey} className={tone.text} initial={{ y: -60 }} animate={{ y: 190 }}
              transition={{ duration: 1.3, ease: 'linear', repeat: Infinity, repeatDelay: 2.4 }}>
              <rect x="22" y="0" width="156" height="40" fill={`url(#${grad})`} />
              <rect x="22" y="39" width="156" height="2.5" fill="currentColor" />
            </motion.g>
          )}
        </g>
      </motion.svg>
    </motion.button>
  )
}
