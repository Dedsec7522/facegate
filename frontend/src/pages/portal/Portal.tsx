import { useCallback, useEffect, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { CalendarDays, CheckCircle2, Clock, LogIn, LogOut, ScanFace, ShieldCheck, UserX, XCircle } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { fmtDate, fmtMinutes, fmtTime } from '../../lib/format'
import { itemVariants, listVariants, spring } from '../../lib/motion'
import type { AttendanceAction, AttendanceDay, AttendanceEvent, FrameFeedback, Page } from '../../lib/types'
import { Badge, StatusBadge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { Avatar, EmptyState, PageHeader, Skeleton } from '../../components/ui/Misc'
import { CameraStage, type StageMode } from '../../components/camera/CameraStage'
import { useCamera } from '../../components/camera/useCamera'
import { useVerificationStream } from '../../components/camera/useVerificationStream'
import { cn } from '../../lib/cn'

interface MyStatus {
  employee: { id: string; name: string; code: string; enrolled: boolean }
  next: { next: AttendanceAction; last_event: { id: string; action: string; occurred_at: string; method: string } | null; attendance_date: string }
  today: AttendanceDay | null
  work_start: string
  work_end: string
  timezone: string
}

const REASON_TEXT: Record<string, string> = {
  mismatch: 'This face does not match the face enrolled for your account. Only you can log in or out from your own portal.',
  not_enrolled: 'Your account has no enrolled face yet. Ask an administrator to enrol you.',
  spoof: 'Liveness check failed. Please use the live camera — not a photo or a screen.',
  challenge_failed: 'The head-turn check was not completed. Please try again and follow the instruction.',
  timeout: 'Verification timed out. Please try again.',
  inconsistent: 'The face changed during verification. Please try again with only you in view.',
}

function useNow(enabled: boolean) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!enabled) return
    const t = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [enabled])
  return now
}

export default function Portal() {
  const qc = useQueryClient()
  const status = useQuery({ queryKey: ['me', 'status'], queryFn: () => api.get<MyStatus>('/attendance/me/status'), refetchInterval: 60_000, retry: false })
  const monthStart = new Date()
  monthStart.setDate(1)
  const from = monthStart.toISOString().slice(0, 10)
  const days = useQuery({ queryKey: ['me', 'days', from], queryFn: () => api.get<Page<AttendanceDay>>('/attendance/me/days', { date_from: from, page_size: 31 }), enabled: status.isSuccess })
  const [selected, setSelected] = useState<string | null>(null)
  const events = useQuery({ queryKey: ['me', 'events', selected], queryFn: () => api.get<AttendanceEvent[]>('/attendance/me/events', { attendance_date: selected }), enabled: !!selected })
  const [verifyOpen, setVerifyOpen] = useState(false)
  const [photoOk, setPhotoOk] = useState(true)

  const s = status.data
  const isOpen = !!s?.today?.is_open
  const now = useNow(isOpen)
  const liveMinutes = (() => {
    if (!s?.today) return 0
    let m = s.today.worked_minutes
    if (s.today.is_open && s.next.last_event?.action === 'check_in') m += Math.max(0, Math.floor((now - new Date(s.next.last_event.occurred_at).getTime()) / 60_000))
    return m
  })()

  if (status.isError && status.error instanceof ApiError && status.error.status === 404) {
    return (
      <>
        <PageHeader title="My attendance" />
        <Card><EmptyState icon={<UserX className="size-5" />} title="No employee profile linked" description="Your login is not linked to an employee record. Ask an administrator to connect it." /></Card>
      </>
    )
  }

  const summary = days.data?.items ?? []
  const present = summary.filter((d) => d.status !== 'absent').length
  const late = summary.filter((d) => d.late_minutes > 0).length
  const hours = summary.reduce((a, d) => a + d.worked_minutes, 0)
  const action: AttendanceAction = s?.next.next ?? 'check_in'

  return (
    <>
      <PageHeader title={s ? `Hello, ${s.employee.name.split(' ')[0]}` : 'My attendance'} description={s ? `Working hours ${s.work_start}–${s.work_end} (${s.timezone})` : undefined} />

      {status.isLoading ? <Skeleton className="h-64" /> : status.isError ? (
        <Card><EmptyState title="Could not load your status" description={(status.error as Error).message} /></Card>
      ) : s && (
        <motion.div variants={listVariants} initial="hidden" animate="show" className="space-y-4">
          {/* ---- Today's attendance card (login / logout from office) ---- */}
          <motion.div variants={itemVariants} className="card overflow-hidden">
            <div className="flex items-center justify-between px-6 pt-5">
              <h2 className="text-lg font-semibold">Today's attendance</h2>
              {isOpen ? <Badge tone="success" dot>Present</Badge> : s.today?.last_out ? <Badge tone="info" dot>Left office</Badge> : <Badge tone="neutral" dot>Out of office</Badge>}
            </div>
            <div className="mx-6 mt-4 grid h-44 place-items-center overflow-hidden rounded-xl bg-brand-50 dark:bg-brand-800/30">
              {photoOk && s.employee.enrolled ? (
                <img src="/api/v1/attendance/me/thumbnail" alt={`Enrolled photo of ${s.employee.name}`} className="h-full w-auto object-cover" onError={() => setPhotoOk(false)} />
              ) : (
                <Avatar name={s.employee.name} size="xl" />
              )}
            </div>
            <dl className="mx-6 mt-5 grid grid-cols-3 gap-4 text-sm">
              <div><dt className="text-ink-3">Check-in time</dt><dd className="tabular mt-0.5 text-lg font-semibold text-brand-700 dark:text-brand-200">{fmtTime(s.today?.first_in)}</dd></div>
              <div><dt className="text-ink-3">Check-out time</dt><dd className="tabular mt-0.5 text-lg font-semibold text-brand-700 dark:text-brand-200">{fmtTime(s.today?.last_out)}</dd></div>
              <div><dt className="text-ink-3">{isOpen ? 'Worked so far' : 'Worked today'}</dt><dd className="tabular mt-0.5 text-lg font-semibold">{fmtMinutes(liveMinutes)}</dd></div>
            </dl>
            <div className="mx-6 mt-5 border-t border-line pt-5 pb-6">
              <Button size="xl" variant={action === 'check_in' ? 'primary' : 'accent'} className="w-full" onClick={() => setVerifyOpen(true)} disabled={!s.employee.enrolled}
                leftIcon={action === 'check_in' ? <LogIn className="size-5" /> : <LogOut className="size-5" />}>
                {action === 'check_in' ? 'Login from Office' : 'Logout from Office'}
              </Button>
              <p className="mt-3 flex items-center justify-center gap-1.5 text-center text-xs text-ink-3">
                <ShieldCheck className="size-3.5" aria-hidden />
                {s.employee.enrolled ? `Verified with your face — only ${s.employee.name.split(' ')[0]}'s enrolled face can log this account in or out.` : 'Your face is not enrolled yet. Ask an administrator to enrol you before using this button.'}
              </p>
            </div>
          </motion.div>

          <motion.div variants={itemVariants} className="grid gap-4 sm:grid-cols-3">
            {[{ l: 'Days present this month', v: String(present), i: <CalendarDays className="size-4" /> }, { l: 'Late arrivals', v: String(late), i: <Clock className="size-4" /> }, { l: 'Hours worked', v: fmtMinutes(hours), i: <Clock className="size-4" /> }].map((x) => (
              <div key={x.l} className="card flex items-center gap-3 p-4">
                <span className="grid size-9 place-items-center rounded-lg bg-surface-3 text-ink-2">{x.i}</span>
                <div><p className="text-xs text-ink-3">{x.l}</p><p className="tabular text-lg font-semibold">{x.v}</p></div>
              </div>
            ))}
          </motion.div>

          <motion.div variants={itemVariants}>
            <Card>
              <CardHeader title="This month" description="Tap a day to see its events" />
              <CardBody className="px-0">
                {days.isLoading ? <div className="space-y-2 px-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
                : summary.length === 0 ? <EmptyState icon={<CalendarDays className="size-5" />} title="No attendance recorded this month" />
                : (
                  <ul className="divide-y divide-line">
                    {summary.map((d) => (
                      <li key={d.id}>
                        <button onClick={() => setSelected(d.attendance_date)} className="flex w-full items-center gap-3 px-5 py-3 text-left hover:bg-surface-3">
                          <span className="w-24 shrink-0 text-sm font-medium">{fmtDate(d.attendance_date)}</span>
                          <span className="tabular hidden text-sm text-ink-2 sm:inline">{fmtTime(d.first_in)} – {fmtTime(d.last_out)}</span>
                          <span className="tabular ml-auto text-sm">{fmtMinutes(d.worked_minutes)}</span>
                          {d.late_minutes > 0 && <Badge tone="warning">+{d.late_minutes}m late</Badge>}
                          <StatusBadge status={d.status} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </Card>
          </motion.div>
        </motion.div>
      )}

      {s && (
        <VerifyDialog open={verifyOpen} action={action} employeeName={s.employee.name} onClose={() => setVerifyOpen(false)}
          onRecorded={() => { void qc.invalidateQueries({ queryKey: ['me'] }) }} />
      )}

      <Dialog open={!!selected} onClose={() => setSelected(null)} title={selected ? fmtDate(selected, 'EEEE d MMMM yyyy') : ''} description="Events recorded for this day" size="sm">
        {events.isLoading ? <Skeleton className="h-20" /> : !events.data?.length ? <p className="text-sm text-ink-3">No events.</p> : (
          <ol className="relative ml-2 border-l border-line pl-5">
            {events.data.map((e) => (
              <li key={e.id} className="relative pb-4 last:pb-0">
                <span className={`absolute -left-[26px] top-1 size-3 rounded-full ring-4 ring-surface ${e.action === 'check_in' ? 'bg-accent-500' : 'bg-brand-500'}`} aria-hidden />
                <p className="text-sm font-medium">{e.action === 'check_in' ? 'Checked in' : 'Checked out'} <span className="tabular text-ink-3">{fmtTime(e.occurred_at)}</span></p>
                <p className="text-xs text-ink-3">via {e.method}{e.voided && ' · voided'}</p>
              </li>
            ))}
          </ol>
        )}
      </Dialog>
    </>
  )
}

/** Face verification bound to the signed-in account; records the given action as soon as the server confirms identity. */
function VerifyDialog({ open, action, employeeName, onClose, onRecorded }: { open: boolean; action: AttendanceAction; employeeName: string; onClose: () => void; onRecorded: (ev: AttendanceEvent) => void }) {
  const cam = useCamera(open)
  const [phase, setPhase] = useState<'verify' | 'recording' | 'done' | 'failed'>('verify')
  const [result, setResult] = useState<FrameFeedback | null>(null)
  const [recorded, setRecorded] = useState<AttendanceEvent | null>(null)
  const [error, setError] = useState<string | null>(null)

  const onTerminal = useCallback(async (fb: FrameFeedback) => {
    setResult(fb)
    if (fb.state !== 'identified' || !fb.token) { setPhase('failed'); return }
    setPhase('recording')
    try {
      const ev = await api.post<AttendanceEvent>('/attendance/events', { token: fb.token, action, device_label: 'portal-web' })
      setRecorded(ev)
      setPhase('done')
      onRecorded(ev)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not record attendance')
      setPhase('failed')
    }
  }, [action, onRecorded])

  const stream = useVerificationStream({ purpose: 'attendance', selfBound: true, grabFrame: cam.grabFrame, fps: 6, onTerminal })
  const { start, stop, phase: streamPhase } = stream

  useEffect(() => {
    if (open && cam.status === 'ready' && streamPhase === 'idle' && phase === 'verify') void start()
  }, [open, cam.status, streamPhase, phase, start])
  useEffect(() => { if (!open) { stop(); setPhase('verify'); setResult(null); setRecorded(null); setError(null) } }, [open, stop])

  const retry = () => { setPhase('verify'); setResult(null); setError(null); void start() }
  const fb = stream.feedback
  const stageMode: StageMode = phase === 'done' ? 'success' : phase === 'failed' ? 'failure' : 'scanning'
  const title = action === 'check_in' ? 'Login from Office' : 'Logout from Office'

  const guidance = (() => {
    if (stream.error) return stream.error
    if (!fb || streamPhase === 'connecting') return 'Connecting…'
    if (fb.state === 'busy') return fb.guidance ?? 'Please hold on…'
    if (fb.challenge && fb.state !== 'no_face' && fb.challenge.state === 'pending' && fb.liveness && fb.liveness.frames >= 2) return fb.challenge.text
    if (fb.challenge?.state === 'turned') return 'Now look back at the camera'
    if (fb.state === 'collecting' && fb.challenge?.state === 'passed') return 'Hold still — verifying it is you'
    return fb.guidance ?? 'Hold still'
  })()

  return (
    <Dialog open={open} onClose={onClose} title={title} description={`Face verification for ${employeeName}'s account only`} size="lg">
      <div className="grid gap-4 sm:grid-cols-[1.2fr_1fr]">
        <div className="theme-dark"><CameraStage videoRef={cam.videoRef} status={cam.status} error={cam.error} feedback={phase === 'verify' ? fb : null} mode={stageMode} sentSize={stream.sentSize} className="aspect-[4/3]" /></div>
        <div className="flex min-h-[220px] flex-col">
          <AnimatePresence mode="wait">
            {(phase === 'verify' || phase === 'recording') && (
              <motion.div key="v" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
                <p className="text-xs font-semibold uppercase tracking-wider text-accent-600">{phase === 'recording' ? 'Recording…' : 'Verifying'}</p>
                <p className="mt-1 text-lg font-medium" aria-live="polite">{phase === 'recording' ? 'Identity confirmed — saving your attendance' : guidance}</p>
                <ul className="mt-4 space-y-2 text-sm">
                  {[['Face detected', !!fb && !['no_face', 'multiple_faces', 'quality'].includes(fb.state)], ['Liveness', !!fb?.liveness?.passed], ['Head-turn check', fb?.challenge?.state === 'passed'], ['Matches your enrolment', phase === 'recording']].map(([label, done]) => (
                    <li key={String(label)} className={cn('flex items-center gap-2', done ? 'text-ink' : 'text-ink-3')}>
                      <span className={cn('grid size-5 place-items-center rounded-full border text-[10px]', done ? 'border-accent-500 bg-accent-500 text-white' : 'border-line-2')}>{done && <CheckCircle2 className="size-3.5" />}</span>{label}
                    </li>
                  ))}
                </ul>
              </motion.div>
            )}
            {phase === 'done' && recorded && (
              <motion.div key="d" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={spring.snappy} className="text-center">
                <motion.span initial={{ scale: 0.5 }} animate={{ scale: 1 }} transition={spring.snappy} className="mx-auto grid size-16 place-items-center rounded-full bg-accent-500 text-white">
                  <svg viewBox="0 0 24 24" className="size-9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <motion.path d="M5 12.5l4.5 4.5L19 7.5" initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.45, ease: [0.25, 1, 0.5, 1], delay: 0.15 }} />
                  </svg>
                </motion.span>
                <p className="mt-3 text-xl font-semibold">{recorded.action === 'check_in' ? 'Logged in from office' : 'Logged out from office'}</p>
                <p className="tabular mt-1 text-3xl font-semibold">{fmtTime(recorded.occurred_at)}</p>
                <p className="mt-1 text-xs text-ink-3">Recorded on the server · verified by face</p>
                <Button className="mt-5" onClick={onClose}>Done</Button>
              </motion.div>
            )}
            {phase === 'failed' && (
              <motion.div key="f" initial={{ opacity: 0, scale: 0.96 }} animate={{ opacity: 1, scale: 1 }} transition={spring.snappy}>
                <span className="grid size-12 place-items-center rounded-full bg-red-500/15 text-red-500"><XCircle className="size-7" /></span>
                <p className="mt-3 text-xs font-semibold uppercase tracking-wider text-red-500">Not verified</p>
                <p className="mt-1 font-medium">{error ?? (result?.reason ? (REASON_TEXT[result.reason] ?? result.message) : stream.error ?? 'Verification could not be completed.')}</p>
                <div className="mt-4 flex gap-2">
                  <Button variant="accent" onClick={retry} leftIcon={<ScanFace className="size-4" />}>Try again</Button>
                  <Button variant="ghost" onClick={onClose}>Cancel</Button>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </Dialog>
  )
}
