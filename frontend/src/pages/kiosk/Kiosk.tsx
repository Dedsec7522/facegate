import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeft, ArrowRight, CheckCircle2, KeyRound, LogIn, LogOut, RefreshCw, ScanFace, ShieldCheck, XCircle } from 'lucide-react'
import { Logo } from '../../components/layout/Logo'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Field'
import { CameraStage, type StageMode } from '../../components/camera/CameraStage'
import { useCamera } from '../../components/camera/useCamera'
import { useVerificationStream } from '../../components/camera/useVerificationStream'
import { api, ApiError } from '../../lib/api'
import { fmtTime } from '../../lib/format'
import { popVariants, spring } from '../../lib/motion'
import type { AttendanceAction, AttendanceEvent, FrameFeedback } from '../../lib/types'
import { cn } from '../../lib/cn'

type Screen = 'welcome' | 'scanning' | 'identified' | 'recorded' | 'failed' | 'pin'

const REASON_TEXT: Record<string, string> = {
  spoof: 'Liveness check failed. Please use the live camera — not a photo, phone or screen.',
  challenge_failed: 'The head-turn check was not completed. Please try again and follow the instruction on screen.',
  unknown: 'We could not match your face to an enrolled employee. If you are new, ask an administrator to enrol you.',
  ambiguous: 'We could not confidently tell you apart from another enrolled person. Please try again in better light.',
  timeout: 'Verification timed out. Please try again.',
  inconsistent: 'The face changed during verification. Please try again with one person in view.',
}

export default function Kiosk() {
  const [screen, setScreen] = useState<Screen>('welcome')
  const [result, setResult] = useState<FrameFeedback | null>(null)
  const [recorded, setRecorded] = useState<AttendanceEvent | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyAction, setBusyAction] = useState<AttendanceAction | null>(null)
  const cameraOn = screen !== 'pin'  // keep the camera warm so 'Try again' is instant
  const cam = useCamera(cameraOn)
  const [clock, setClock] = useState(new Date())
  useEffect(() => { const t = setInterval(() => setClock(new Date()), 1000); return () => clearInterval(t) }, [])

  const onTerminal = useCallback((fb: FrameFeedback) => {
    setResult(fb)
    setScreen(fb.state === 'identified' ? 'identified' : 'failed')
  }, [])
  const stream = useVerificationStream({ purpose: 'attendance', grabFrame: cam.grabFrame, fps: 10, onTerminal })
  const { start: streamStart, stop: streamStop } = stream

  const begin = useCallback(() => {
    setResult(null); setRecorded(null); setActionError(null)
    setScreen('scanning')
    void streamStart()
  }, [streamStart])

  const reset = useCallback(() => { streamStop(); setScreen('welcome'); setResult(null); setRecorded(null); setActionError(null) }, [streamStop])

  // Auto-return to the welcome screen after a result so the kiosk is ready for the next person.
  useEffect(() => {
    if (screen === 'recorded' || screen === 'failed') { const t = setTimeout(reset, screen === 'recorded' ? 8000 : 12000); return () => clearTimeout(t) }
    if (screen === 'identified') { const t = setTimeout(reset, 60000); return () => clearTimeout(t) }
  }, [screen, reset])

  const record = async (action: AttendanceAction) => {
    if (!result?.token) return
    setBusyAction(action); setActionError(null)
    try {
      const ev = await api.post<AttendanceEvent>('/attendance/events', { token: result.token, action, device_label: 'kiosk-web' })
      setRecorded(ev); setScreen('recorded')
    } catch (e) {
      setActionError(e instanceof ApiError ? e.message : 'Could not record attendance')
    } finally { setBusyAction(null) }
  }

  const fb = stream.feedback
  const stageMode: StageMode = screen === 'recorded' || screen === 'identified' ? 'success' : screen === 'failed' ? 'failure' : screen === 'scanning' ? 'scanning' : 'idle'

  return (
    <div className="theme-dark min-h-dvh bg-surface text-ink">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
        <Link to="/" className="flex items-center gap-2.5"><Logo className="size-8" /><span className="text-[15px] font-semibold">FaceGate</span></Link>
        <div className="text-right">
          <p className="text-2xl font-semibold tabular leading-none">{clock.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</p>
          <p className="text-xs text-ink-3">{clock.toLocaleDateString([], { weekday: 'long', day: 'numeric', month: 'long' })}</p>
        </div>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 px-5 pb-10 lg:grid-cols-[1.2fr_0.8fr]">
        <CameraStage videoRef={cam.videoRef} status={cam.status} error={cam.error} feedback={screen === 'scanning' ? fb : null} mode={stageMode} sentSize={stream.sentSize} className="aspect-[4/3] w-full lg:aspect-auto lg:min-h-[560px]"
          overlay={screen === 'scanning' && <ScanHud fb={fb} elapsed={stream.elapsedMs} />} />

        <section className="flex flex-col">
          <AnimatePresence mode="wait">
            {screen === 'welcome' && (
              <Panel key="welcome">
                <ScanFace className="size-10 text-accent-400" aria-hidden />
                <h1 className="mt-4 text-3xl font-semibold leading-tight">Check in or out with your face</h1>
                <p className="mt-2 text-ink-2">Stand in front of the camera, press start, and follow the on-screen instruction. Identification takes a few seconds.</p>
                <div className="relative mt-8">
                  {cam.status === 'ready' && <motion.span aria-hidden className="pointer-events-none absolute inset-0 rounded-xl bg-accent-500/40" animate={{ scale: [1, 1.04, 1], opacity: [0.5, 0, 0.5] }} transition={{ duration: 2.4, repeat: Infinity, ease: 'easeInOut' }} />}
                  <Button size="xl" variant="accent" className="relative w-full" onClick={begin} disabled={cam.status !== 'ready'} rightIcon={<ArrowRight className="size-5" />}>
                    {cam.status === 'ready' ? 'Start verification' : 'Waiting for camera…'}
                  </Button>
                </div>
                <button onClick={() => setScreen('pin')} className="mt-4 inline-flex items-center gap-2 self-start text-sm text-ink-3 hover:text-ink"><KeyRound className="size-4" /> Use employee code and PIN instead</button>
                <p className="mt-auto pt-8 text-xs text-ink-3"><ShieldCheck className="mr-1 inline size-3.5" />Your face is matched against encrypted templates on this organisation's own server. No images are stored from this scan.</p>
              </Panel>
            )}

            {screen === 'scanning' && (
              <Panel key="scanning">
                <p className="text-xs font-semibold uppercase tracking-wider text-accent-400">Verifying</p>
                <h2 className="mt-2 text-2xl font-semibold leading-tight" aria-live="polite">{guidanceFor(fb, stream.phase, stream.error)}</h2>
                <Steps fb={fb} />
                <Button variant="ghost" className="mt-auto self-start text-ink-3" onClick={reset} leftIcon={<ArrowLeft className="size-4" />}>Cancel</Button>
              </Panel>
            )}

            {screen === 'identified' && result?.employee && (
              <Panel key="identified">
                <motion.div initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={spring.snappy} className="grid size-14 place-items-center rounded-full bg-accent-500/15 text-accent-400"><CheckCircle2 className="size-8" /></motion.div>
                <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-accent-400">Identified</p>
                <h2 className="mt-1 text-3xl font-semibold leading-tight">Hello, {result.employee.name.split(' ')[0]}</h2>
                <p className="text-ink-3">{result.employee.name} · {result.employee.code}</p>
                <TimesRow firstIn={result.today?.first_in} lastOut={result.today?.last_out} />
                <div className="mt-6 grid gap-3">
                  <ActionButton action={result.next?.next ?? 'check_in'} suggested busy={busyAction} onClick={() => record(result.next?.next ?? 'check_in')} />
                </div>
                <p className="mt-3 text-xs text-ink-3">{result.next?.next === 'check_in' ? 'You are not logged in yet, so only Login is offered.' : 'You are logged in, so only Logout is offered.'}</p>
                {actionError && <p role="alert" className="mt-3 rounded-md border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">{actionError}</p>}
                <p className="mt-4 text-xs text-ink-3">Not you? <button className="underline hover:text-ink" onClick={reset}>Cancel</button></p>
              </Panel>
            )}

            {screen === 'recorded' && recorded && (
              <Panel key="recorded">
                <motion.div initial={{ scale: 0.5, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={spring.snappy} className="grid size-16 place-items-center rounded-full bg-accent-500 text-white"><CheckCircle2 className="size-9" /></motion.div>
                <Welcome action={recorded.action} name={recorded.employee_name ?? ''} />
                <p className="mt-4 text-5xl font-semibold tabular">{fmtTime(recorded.occurred_at)}</p>
                <TimesRow firstIn={recorded.action === 'check_in' ? recorded.occurred_at : result?.today?.first_in} lastOut={recorded.action === 'check_out' ? recorded.occurred_at : null} />
                <p className="mt-3 text-sm text-ink-3">Recorded on the server · {recorded.method === 'face' ? 'verified by face' : `method: ${recorded.method}`}</p>
                <Button variant="outline" className="mt-auto self-start border-line-2 bg-transparent text-ink" onClick={reset} leftIcon={<RefreshCw className="size-4" />}>Done</Button>
              </Panel>
            )}

            {screen === 'failed' && (
              <Panel key="failed">
                <motion.div initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={spring.snappy} className="grid size-14 place-items-center rounded-full bg-red-500/15 text-red-400"><XCircle className="size-8" /></motion.div>
                <p className="mt-4 text-xs font-semibold uppercase tracking-wider text-red-400">Not verified</p>
                <h2 className="mt-1 text-2xl font-semibold leading-tight">{result?.reason ? (REASON_TEXT[result.reason] ?? result.message) : stream.error ?? 'Verification could not be completed.'}</h2>
                <div className="mt-6 flex flex-wrap gap-3">
                  <Button variant="accent" size="lg" onClick={begin} leftIcon={<RefreshCw className="size-4" />}>Try again</Button>
                  <Button variant="outline" size="lg" className="border-line-2 bg-transparent text-ink" onClick={() => setScreen('pin')} leftIcon={<KeyRound className="size-4" />}>Use PIN</Button>
                </div>
                <p className="mt-auto pt-6 text-xs text-ink-3">This attempt has been logged for the administrator.</p>
              </Panel>
            )}

            {screen === 'pin' && <PinPanel key="pin" onBack={reset} onRecorded={(ev) => { setRecorded(ev); setScreen('recorded') }} />}
          </AnimatePresence>
        </section>
      </main>
    </div>
  )
}

function Panel({ children }: { children: ReactNode }) {
  return (
    <motion.div variants={popVariants} initial="hidden" animate="show" exit="exit" className="flex min-h-[420px] flex-1 flex-col rounded-2xl border border-line bg-surface-2/70 p-7">
      {children}
    </motion.div>
  )
}

function guidanceFor(fb: FrameFeedback | null, phase: string, error: string | null): string {
  if (error) return error
  if (phase === 'connecting' || !fb) return 'Connecting to the verification service…'
  if (fb.state === 'busy') return fb.guidance ?? 'Please hold on…'
  if (fb.challenge && fb.state !== 'no_face' && fb.challenge.state === 'pending' && fb.liveness && fb.liveness.frames >= 2) return fb.challenge.text
  if (fb.challenge?.state === 'turned') return 'Now look back at the camera'
  if (fb.state === 'collecting' && fb.challenge?.state === 'passed') return 'Hold still — almost there'
  return fb.guidance ?? 'Hold still'
}

function Steps({ fb }: { fb: FrameFeedback | null }) {
  const items = useMemo(() => {
    const faceOk = !!fb && fb.state !== 'no_face' && fb.state !== 'multiple_faces' && fb.state !== 'quality'
    const live = fb?.liveness
    const ch = fb?.challenge
    return [
      { label: 'Face detected', done: faceOk, active: !faceOk },
      { label: 'Liveness', done: !!live?.passed, active: faceOk && !live?.passed, detail: live ? `${Math.min(live.frames, live.needed ?? 4)}/${live.needed ?? 4} frames` : undefined },
      { label: 'Head-turn check', done: ch?.state === 'passed', active: faceOk && ch?.state !== 'passed', detail: ch?.state === 'turned' ? 'return to centre' : undefined },
      { label: 'Identity match', done: false, active: !!live?.passed && ch?.state === 'passed' },
    ]
  }, [fb])
  return (
    <ol className="mt-6 space-y-3">
      {items.map((it, i) => (
        <li key={it.label} className="flex items-center gap-3 text-sm">
          <span className={cn('grid size-6 place-items-center rounded-full border text-xs font-semibold transition-colors', it.done ? 'border-accent-400 bg-accent-500 text-white' : it.active ? 'border-accent-400 text-accent-400' : 'border-line-2 text-ink-3')}>
            {it.done ? <CheckCircle2 className="size-4" /> : i + 1}
          </span>
          <span className={cn(it.done || it.active ? 'text-ink' : 'text-ink-3')}>{it.label}</span>
          {it.detail && <span className="ml-auto text-xs text-ink-3 tabular">{it.detail}</span>}
          {it.active && !it.done && <motion.span className="ml-auto size-1.5 rounded-full bg-accent-400" animate={{ opacity: [0.3, 1, 0.3] }} transition={{ duration: 1.2, repeat: Infinity }} />}
        </li>
      ))}
    </ol>
  )
}

function ScanHud({ fb, elapsed }: { fb: FrameFeedback | null; elapsed: () => number }) {
  const [t, setT] = useState(0)
  useEffect(() => { const i = setInterval(() => setT(elapsed()), 250); return () => clearInterval(i) }, [elapsed])
  const live = fb?.liveness?.score ?? 0
  const perFrame = fb?.timings_ms ? Math.round(Object.values(fb.timings_ms).reduce((a, b) => a + b, 0)) : null
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 flex items-end justify-between p-4 text-xs text-white/80">
      <div className="rounded-md bg-black/45 px-2.5 py-1.5 backdrop-blur-sm tabular">{(t / 1000).toFixed(1)} s · {perFrame != null ? `${perFrame} ms/frame` : '—'}</div>
      <div className="rounded-md bg-black/45 px-2.5 py-1.5 backdrop-blur-sm">
        <span className="mr-2">Liveness</span>
        <span className="inline-block h-1.5 w-24 overflow-hidden rounded-full bg-white/20 align-middle"><motion.span className="block h-full rounded-full bg-accent-400" animate={{ width: `${Math.round(live * 100)}%` }} transition={{ duration: 0.25 }} /></span>
      </div>
    </div>
  )
}

function ActionButton({ action, suggested, busy, onClick }: { action: AttendanceAction; suggested: boolean; busy: AttendanceAction | null; onClick: () => void }) {
  const Icon = action === 'check_in' ? LogIn : LogOut
  return (
    <Button size="xl" variant={suggested ? 'accent' : 'outline'} className={cn('w-full justify-between', !suggested && 'border-line-2 bg-transparent text-ink')} onClick={onClick} loading={busy === action} disabled={!!busy && busy !== action}>
      <span className="flex items-center gap-3"><Icon className="size-5" />{action === 'check_in' ? 'Login from Office' : 'Logout from Office'}</span>
      <ArrowRight className="size-5 opacity-80" />
    </Button>
  )
}

function TimesRow({ firstIn, lastOut }: { firstIn?: string | null; lastOut?: string | null }) {
  return (
    <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
      <div className="rounded-xl border border-line bg-surface-3/60 px-4 py-3"><dt className="text-ink-3">Login time</dt><dd className="tabular mt-0.5 text-xl font-semibold">{fmtTime(firstIn)}</dd></div>
      <div className="rounded-xl border border-line bg-surface-3/60 px-4 py-3"><dt className="text-ink-3">Logout time</dt><dd className="tabular mt-0.5 text-xl font-semibold">{fmtTime(lastOut)}</dd></div>
    </dl>
  )
}

/** Word-by-word greeting so the employee's name arrives with a little lift. */
export function Welcome({ action, name, className }: { action: AttendanceAction; name: string; className?: string }) {
  const first = name.split(' ')[0] || name
  const words = (action === 'check_in' ? `Welcome, ${first}!` : `Goodbye, ${first} — see you soon`).split(' ')
  return (
    <div className={cn('mt-5', className)}>
      <motion.h2 className="text-3xl font-semibold leading-tight" initial="hidden" animate="show" variants={{ hidden: {}, show: { transition: { staggerChildren: 0.07, delayChildren: 0.15 } } }} aria-label={words.join(' ')}>
        {words.map((w, i) => (
          <motion.span key={i} className="mr-[0.3em] inline-block" variants={{ hidden: { opacity: 0, y: 14, filter: 'blur(4px)' }, show: { opacity: 1, y: 0, filter: 'blur(0px)', transition: { type: 'spring', stiffness: 320, damping: 26 } } }}>{w}</motion.span>
        ))}
      </motion.h2>
      <motion.p className="mt-1 text-lg text-ink-2" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }}>{name}</motion.p>
    </div>
  )
}

function PinPanel({ onBack, onRecorded }: { onBack: () => void; onRecorded: (ev: AttendanceEvent) => void }) {
  const [code, setCode] = useState('')
  const [pin, setPin] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState<AttendanceAction | null>(null)
  const codeRef = useRef<HTMLInputElement>(null)
  useEffect(() => { codeRef.current?.focus() }, [])
  const submit = async (action: AttendanceAction) => {
    setBusy(action); setErr(null)
    try { onRecorded(await api.post<AttendanceEvent>('/attendance/events/pin', { employee_code: code.trim(), pin, action, device_label: 'kiosk-web' })) }
    catch (e) { setErr(e instanceof ApiError ? e.message : 'Could not record attendance') }
    finally { setBusy(null) }
  }
  return (
    <Panel>
      <p className="text-xs font-semibold uppercase tracking-wider text-ink-3">Fallback</p>
      <h2 className="mt-1 text-2xl font-semibold">Employee code and PIN</h2>
      <p className="mt-1 text-sm text-ink-3">Only works if an administrator has enabled a PIN for you. These events are flagged as non-biometric.</p>
      <div className="mt-6 space-y-4">
        <Input ref={codeRef} label="Employee code" value={code} onChange={(e) => setCode(e.target.value)} autoComplete="off" />
        <Input label="PIN" type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value)} autoComplete="off" maxLength={8} />
        {err && <p role="alert" className="rounded-md border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-300">{err}</p>}
        <div className="grid grid-cols-2 gap-3">
          <Button size="lg" variant="accent" onClick={() => submit('check_in')} loading={busy === 'check_in'} disabled={!code || pin.length < 4}>Check in</Button>
          <Button size="lg" variant="outline" className="border-line-2 bg-transparent text-ink" onClick={() => submit('check_out')} loading={busy === 'check_out'} disabled={!code || pin.length < 4}>Check out</Button>
        </div>
      </div>
      <Button variant="ghost" className="mt-auto self-start text-ink-3" onClick={onBack} leftIcon={<ArrowLeft className="size-4" />}>Back to face check-in</Button>
    </Panel>
  )
}
