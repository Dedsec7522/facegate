import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeft, Home, RotateCw } from 'lucide-react'
import { Logo } from '../../components/layout/Logo'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../../lib/auth'
import { cn } from '../../lib/cn'
import { itemVariants, listVariants } from '../../lib/motion'
import { ScannerFace, type ErrorKind } from './ScannerFace'

type Copy = {
  digits: [string, string] | null
  glyph: string
  title: string
  body: (path: string) => ReactNode
  /** Scanner verdicts: the first on arrival, the next ones each time the visitor scans again. */
  verdicts: string[]
  chip: string
  dot: string
}

const Path = ({ children }: { children: string }) => (
  <code className="rounded-sm bg-surface-3 px-1.5 py-0.5 font-mono text-[0.9em] [overflow-wrap:anywhere] text-ink">{children}</code>
)

const COPY: Record<ErrorKind, Copy> = {
  '404': {
    digits: ['4', '4'], glyph: '?', title: 'This page isn’t enrolled',
    body: (path) => <>We scanned every corner of FaceGate and couldn’t match <Path>{path}</Path> to anything we know. It may have moved, or the link has a typo.</>,
    verdicts: ['No match · 404', 'Still no match', 'Checked twice. Nope.', 'It’s really not here.', 'You’re persistent. Still 404.'],
    chip: 'bg-brand-100 text-brand-800 dark:bg-brand-900/60 dark:text-brand-200', dot: 'bg-brand-500',
  },
  '403': {
    digits: ['4', '3'], glyph: '!', title: 'Your badge doesn’t open this door',
    body: () => <>You’re signed in, but this area belongs to a different role. If you think you should have access, ask an administrator.</>,
    verdicts: ['Access denied · 403', 'Still denied', 'The door stays shut.'],
    chip: 'bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200', dot: 'bg-amber-500',
  },
  '500': {
    digits: ['5', '0'], glyph: '×', title: 'Something tripped the sensor',
    body: () => <>This page hit an unexpected error. Reloading usually fixes it; if it keeps happening, tell your administrator what you were doing.</>,
    verdicts: ['Sensor fault · 500', 'Still faulty', 'A reload will help more.'],
    chip: 'bg-red-100 text-red-800 dark:bg-red-950/60 dark:text-red-200', dot: 'bg-red-500',
  },
  offline: {
    digits: null, glyph: 'z', title: 'You’re offline',
    body: () => <>FaceGate can’t reach the network, so this page couldn’t load. Check your connection and try again.</>,
    verdicts: ['No connection', 'Still offline'],
    chip: 'bg-surface-3 text-ink-2', dot: 'bg-ink-3',
  },
}

// Where the drifting glyphs sit around the scanner (percent of the hero box).
const FLOATERS = [
  { left: '4%', top: '8%', size: 28 }, { left: '90%', top: '2%', size: 22 }, { left: '96%', top: '62%', size: 30 },
  { left: '0%', top: '70%', size: 20 }, { left: '22%', top: '-10%', size: 18 }, { left: '72%', top: '96%', size: 24 },
]

function Digit({ ch, i }: { ch: string; i: number }) {
  return (
    <motion.span aria-hidden className="inline-block" initial={{ y: -90, opacity: 0, rotate: i ? 16 : -16 }} animate={{ y: 0, opacity: 1, rotate: 0 }}
      transition={{ type: 'spring', stiffness: 260, damping: 13, delay: 0.12 + i * 0.14 }}>
      <motion.span className="inline-block bg-linear-to-b from-brand-500 to-brand-800 bg-clip-text text-transparent dark:from-brand-300 dark:to-brand-500"
        animate={{ y: [0, -9, 0] }} transition={{ duration: 3.4, repeat: Infinity, ease: 'easeInOut', delay: i * 0.6 }}
        whileHover={{ rotate: i ? 9 : -9, scale: 1.07 }}>
        {ch}
      </motion.span>
    </motion.span>
  )
}

/**
 * Full-screen error page used for unknown URLs (404), forbidden areas (403), crashed pages (500) and failed loads
 * while offline. `detail` is the technical message and is only passed in development.
 */
export function ErrorPage({ kind = '404', detail }: { kind?: ErrorKind; detail?: string }) {
  const c = COPY[kind]
  const { user } = useAuth()
  const navigate = useNavigate()
  const loc = useLocation()
  const [scans, setScans] = useState(0)
  const [scanning, setScanning] = useState(true)
  const home = !user ? '/' : user.role === 'employee' ? '/portal' : '/admin'
  const label = scanning ? 'Scanning…' : c.verdicts[Math.min(scans, c.verdicts.length - 1)]

  useEffect(() => {
    const t = window.setTimeout(() => setScanning(false), 1300)
    return () => window.clearTimeout(t)
  }, [scans])

  useEffect(() => {
    const before = document.title
    document.title = `${c.title} · FaceGate`
    return () => { document.title = before }
  }, [c.title])

  const rescan = () => { setScanning(true); setScans((n) => n + 1) }
  const reload = () => window.location.reload()

  return (
    <main className="relative grid min-h-dvh place-items-center overflow-hidden bg-surface-2 px-6 py-16 text-ink">
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute inset-0 opacity-70"
          style={{ backgroundImage: 'radial-gradient(var(--line-2) 1px, transparent 1px)', backgroundSize: '22px 22px', maskImage: 'radial-gradient(60% 55% at 50% 42%, #000 35%, transparent 100%)' }} />
        <motion.div className="absolute top-[8%] left-[12%] size-80 rounded-full bg-brand-300/35 blur-3xl dark:bg-brand-700/25"
          animate={{ x: [0, 70, 0], y: [0, 40, 0] }} transition={{ duration: 16, repeat: Infinity, ease: 'easeInOut' }} />
        <motion.div className="absolute right-[10%] bottom-[6%] size-96 rounded-full bg-accent-300/30 blur-3xl dark:bg-accent-700/20"
          animate={{ x: [0, -60, 0], y: [0, -50, 0] }} transition={{ duration: 19, repeat: Infinity, ease: 'easeInOut' }} />
      </div>

      <Link to="/" className="absolute top-5 left-6 flex items-center gap-2.5 text-ink" aria-label="FaceGate home">
        <Logo className="size-8" /><span className="font-semibold">FaceGate</span>
      </Link>

      <motion.div variants={listVariants} initial="hidden" animate="show" className="relative flex w-full max-w-xl flex-col items-center text-center">
        <div className="relative flex items-center justify-center gap-[clamp(6px,2.5vw,22px)] text-[clamp(92px,25vw,188px)] leading-none font-bold tracking-tighter select-none">
          {FLOATERS.map((f, i) => (
            <motion.span key={f.left + f.top} aria-hidden className="absolute font-semibold text-brand-400 dark:text-brand-300"
              style={{ left: f.left, top: f.top, fontSize: f.size, letterSpacing: 0 }}
              animate={{ y: [0, -16, 0], rotate: [-10, 10, -10], opacity: [0.2, 0.75, 0.2] }}
              transition={{ duration: 4 + i * 0.7, repeat: Infinity, ease: 'easeInOut', delay: i * 0.45 }}>
              {c.glyph}
            </motion.span>
          ))}
          {c.digits && <Digit ch={c.digits[0]} i={0} />}
          <motion.div className="w-[clamp(118px,29vw,204px)] shrink-0" initial={{ scale: 0, rotate: -30 }} animate={{ scale: 1, rotate: 0 }}
            transition={{ type: 'spring', stiffness: 220, damping: 14, delay: 0.05 }}>
            <ScannerFace kind={kind} scanKey={scans} onScan={rescan} />
          </motion.div>
          {c.digits && <Digit ch={c.digits[1]} i={1} />}
        </div>

        <motion.div variants={itemVariants} aria-live="polite" className={cn('mt-7 inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium tabular', c.chip)}>
          <motion.span className={cn('size-1.5 rounded-full', c.dot)} animate={{ scale: [1, 1.7, 1], opacity: [1, 0.45, 1] }} transition={{ duration: 1.2, repeat: Infinity }} />
          <AnimatePresence mode="wait" initial={false}>
            <motion.span key={label} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.16 }}>{label}</motion.span>
          </AnimatePresence>
        </motion.div>

        <motion.h1 variants={itemVariants} className="mt-5 text-3xl font-semibold sm:text-4xl">
          {kind !== 'offline' && <span className="sr-only">Error {kind}: </span>}{c.title}
        </motion.h1>
        <motion.p variants={itemVariants} className="mt-3 max-w-md text-pretty text-ink-2">{c.body(loc.pathname)}</motion.p>

        <motion.div variants={itemVariants} className="mt-8 flex flex-wrap items-center justify-center gap-3">
          {kind === '500' || kind === 'offline' ? (
            <>
              <Button size="lg" leftIcon={<RotateCw className="size-4" />} onClick={reload}>{kind === 'offline' ? 'Try again' : 'Reload page'}</Button>
              {kind === '500' && <Button size="lg" variant="outline" leftIcon={<Home className="size-4" />} onClick={() => navigate(home)}>Go home</Button>}
            </>
          ) : (
            <>
              <Button size="lg" leftIcon={<Home className="size-4" />} onClick={() => navigate(home)}>Take me home</Button>
              <Button size="lg" variant="outline" leftIcon={<ArrowLeft className="size-4" />} onClick={() => navigate(-1)}>Go back</Button>
            </>
          )}
        </motion.div>

        {kind !== 'offline' && <motion.p variants={itemVariants} className="mt-6 text-xs text-ink-3">Psst: press the scanner to scan again.</motion.p>}

        {detail && (
          <motion.details variants={itemVariants} className="mt-5 w-full rounded-lg border border-line bg-surface p-3 text-left text-xs text-ink-2">
            <summary className="cursor-pointer font-medium">Technical details (development only)</summary>
            <pre className="scrollbar-thin mt-2 overflow-x-auto font-mono whitespace-pre-wrap">{detail}</pre>
          </motion.details>
        )}
      </motion.div>
    </main>
  )
}
