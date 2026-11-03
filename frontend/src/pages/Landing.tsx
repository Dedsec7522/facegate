import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { ArrowRight, Fingerprint, Lock, ScanFace, ShieldCheck, Timer, UserCheck } from 'lucide-react'
import { Logo } from '../components/layout/Logo'
import { Button } from '../components/ui/Button'
import { itemVariants, listVariants } from '../lib/motion'
import { useAuth } from '../lib/auth'

const features = [
  { icon: ScanFace, title: 'Hands-free identification', text: 'Employees are recognised automatically from an enrolled facial template — no badges, IDs or passwords at the door.' },
  { icon: ShieldCheck, title: 'Liveness verified', text: 'Passive presentation-attack detection fused with a server-issued head-turn challenge rejects photos, screens and replays.' },
  { icon: Timer, title: 'Attendance engine', text: 'Server-side check-in / check-out rules, overnight shifts, duplicate-scan protection and late-arrival reporting.' },
  { icon: Lock, title: 'Your data, your servers', text: 'Runs entirely on your own infrastructure. Templates are encrypted at rest and never leave your network.' },
  { icon: UserCheck, title: 'Guided enrolment', text: 'Administrators enrol employees in under a minute with lighting checks, multi-pose capture and duplicate detection.' },
  { icon: Fingerprint, title: 'Audited end to end', text: 'Every verification attempt, correction and administrative action is written to an append-only audit log.' },
]

export default function Landing() {
  const { user } = useAuth()
  const portal = user ? (user.role === 'employee' ? '/portal' : '/admin') : '/login'
  return (
    <div className="theme-dark min-h-dvh bg-surface text-ink">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-2.5"><Logo className="size-8" /><span className="text-[15px] font-semibold tracking-tight">FaceGate</span></div>
        <nav className="flex items-center gap-2">
          <Link to="/kiosk" className="rounded-md px-3 py-2 text-sm text-ink-2 hover:text-ink">Attendance kiosk</Link>
          <Link to={portal}><Button variant="outline" size="sm" className="border-line-2 bg-transparent text-ink hover:bg-surface-3">{user ? 'Open console' : 'Sign in'}</Button></Link>
        </nav>
      </header>

      <section className="relative overflow-hidden">
        <div className="grid-fade pointer-events-none absolute inset-0" aria-hidden />
        <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-6 pb-20 pt-10 md:grid-cols-[1.1fr_0.9fr] md:pt-16">
          <motion.div initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.5, ease: [0.25, 1, 0.5, 1] }}>
            <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-line-2 px-3 py-1 text-xs font-medium text-ink-2">
              <span className="size-1.5 rounded-full bg-accent-400" /> Self-hosted · No cloud biometrics
            </p>
            <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight md:text-5xl">
              Corporate attendance that recognises people, <span className="text-accent-400">not badges</span>.
            </h1>
            <p className="mt-5 max-w-xl text-lg text-ink-2">
              FaceGate identifies enrolled employees in seconds, verifies they are physically present, and records a precise, auditable attendance event — all on your own servers.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link to="/kiosk"><Button size="lg" variant="accent" rightIcon={<ArrowRight className="size-4" />}>Check in with your face</Button></Link>
              <Link to={portal}><Button size="lg" variant="outline" className="border-line-2 bg-transparent text-ink hover:bg-surface-3">Administrator sign-in</Button></Link>
            </div>
            <dl className="mt-10 grid max-w-md grid-cols-3 gap-4 text-sm">
              {[['~50 ms', 'per frame on CPU'], ['300+', 'employees per site'], ['AES-256', 'template encryption']].map(([v, l]) => (
                <div key={l}><dt className="text-xl font-semibold tabular">{v}</dt><dd className="text-ink-3">{l}</dd></div>
              ))}
            </dl>
          </motion.div>

          <motion.div initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: 0.6, delay: 0.1, ease: [0.25, 1, 0.5, 1] }} className="relative mx-auto aspect-[4/5] w-full max-w-sm">
            <div className="absolute inset-0 rounded-3xl border border-line-2 bg-gradient-to-b from-surface-3 to-surface-2 shadow-pop" />
            <HeroScan />
          </motion.div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-6 pb-24">
        <motion.ul variants={listVariants} initial="hidden" whileInView="show" viewport={{ once: true, amount: 0.2 }} className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {features.map((f) => (
            <motion.li key={f.title} variants={itemVariants} className="rounded-xl border border-line bg-surface-2/60 p-5">
              <f.icon className="mb-3 size-5 text-accent-400" aria-hidden />
              <h3 className="text-[15px] font-semibold">{f.title}</h3>
              <p className="mt-1.5 text-sm text-ink-3">{f.text}</p>
            </motion.li>
          ))}
        </motion.ul>
        <p className="mt-10 text-center text-xs text-ink-3">Biometric data is processed under your organisation's privacy notice. Employees can request deletion of their facial template at any time.</p>
      </section>
    </div>
  )
}

function HeroScan() {
  return (
    <svg viewBox="0 0 320 400" className="absolute inset-0 size-full" aria-hidden>
      <defs>
        <linearGradient id="sweep" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#34d399" stopOpacity="0" /><stop offset="0.5" stopColor="#34d399" stopOpacity="0.55" /><stop offset="1" stopColor="#34d399" stopOpacity="0" />
        </linearGradient>
      </defs>
      <g stroke="rgba(255,255,255,0.12)" strokeWidth="1">{Array.from({ length: 9 }, (_, i) => <line key={i} x1={40 + i * 30} x2={40 + i * 30} y1="60" y2="340" />)}{Array.from({ length: 10 }, (_, i) => <line key={`h${i}`} y1={60 + i * 30} y2={60 + i * 30} x1="40" x2="280" />)}</g>
      <ellipse cx="160" cy="190" rx="62" ry="84" fill="none" stroke="rgba(255,255,255,0.35)" strokeDasharray="5 7" />
      <g stroke="#34d399" strokeWidth="3" strokeLinecap="round" fill="none">
        <path d="M88 118v-18h18M232 100h-18v18M88 262v18h18M232 280h-18v-18" />
      </g>
      <motion.rect x="92" width="136" height="26" fill="url(#sweep)" initial={{ y: 100 }} animate={{ y: [100, 256, 100] }} transition={{ duration: 3.2, repeat: Infinity, ease: 'easeInOut' }} />
      <g fill="rgba(255,255,255,0.85)">{[[136, 170], [184, 170], [160, 200], [142, 228], [178, 228]].map(([x, y]) => <circle key={`${x}${y}`} cx={x} cy={y} r="2.6" />)}</g>
      <motion.g initial={{ opacity: 0 }} animate={{ opacity: [0, 1, 1, 0] }} transition={{ duration: 3.2, repeat: Infinity, times: [0, 0.6, 0.9, 1] }}>
        <rect x="70" y="312" width="180" height="40" rx="10" fill="rgba(52,211,153,0.12)" stroke="rgba(52,211,153,0.5)" />
        <text x="160" y="337" textAnchor="middle" fontSize="13" fontFamily="Inter Variable, system-ui" fill="#d1fae5" fontWeight="600">Identified · Live</text>
      </motion.g>
    </svg>
  )
}
