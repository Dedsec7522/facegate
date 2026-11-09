import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { AlarmClockCheck, CalendarCheck2, CalendarDays, CheckCircle2, Clock, ClockArrowDown, ClockArrowUp, Hourglass, LogIn, LogOut, ScanFace, ShieldCheck, Timer, TriangleAlert, UserX, XCircle } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { fmtClock, fmtDate, fmtMinutes, fmtTime } from '../../lib/format'
import { itemVariants, listVariants, spring } from '../../lib/motion'
import type { AttendanceAction, AttendanceDay, AttendanceEvent, FrameFeedback, MyInsights, Page } from '../../lib/types'
import { Badge, StatusBadge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { Avatar, CountUp, EmptyState, PageHeader, Skeleton } from '../../components/ui/Misc'
import { CameraStage, type StageMode } from '../../components/camera/CameraStage'
import { useCamera } from '../../components/camera/useCamera'
import { useVerificationStream } from '../../components/camera/useVerificationStream'
import { cn } from '../../lib/cn'
import { Welcome } from '../kiosk/Kiosk'

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
  const insights = useQuery({ queryKey: ['me', 'insights'], queryFn: () => api.get<MyInsights>('/attendance/me/insights', { days: 30 }), enabled: status.isSuccess })
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
  const action: AttendanceAction = s?.next.next ?? 'check_in'

  return (
    <>
      {!s && <PageHeader title="My attendance" />}

      {status.isLoading ? <Skeleton className="h-64" /> : status.isError ? (
        <Card><EmptyState title="Could not load your status" description={(status.error as Error).message} /></Card>
      ) : s && (
        <motion.div variants={listVariants} initial="hidden" animate="show" className="space-y-4">
          {/* ---- Greeting + this-month summary band ---- */}
          <SummaryBand name={s.employee.name} workStart={s.work_start} workEnd={s.work_end} timezone={s.timezone} days={summary} loading={days.isLoading} />

          {/* ---- Today's attendance + insights (mirrors the HR portal layout) ---- */}
          <div className="grid gap-4 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            <motion.section variants={itemVariants} className="card flex flex-col overflow-hidden" aria-labelledby="today-h">
              <div className="flex items-center justify-between px-6 pt-5">
                <h2 id="today-h" className="text-lg font-semibold">Today's Attendance</h2>
                {isOpen ? <Badge tone="success">Present</Badge> : s.today?.last_out ? <Badge tone="info">Left office</Badge> : <Badge tone="neutral">Out of office</Badge>}
              </div>
              <div className="mx-6 mt-4 border-t border-line" />
              <motion.div layout className="mx-6 mt-5 grid h-44 place-items-center overflow-hidden rounded-xl bg-brand-100/70 dark:bg-brand-800/30">
                {photoOk && s.employee.enrolled ? (
                  <motion.img initial={{ opacity: 0, scale: 1.04 }} animate={{ opacity: 1, scale: 1 }} transition={spring.gentle} src="/api/v1/attendance/me/thumbnail" alt={`Enrolled photo of ${s.employee.name}`} className="h-full w-auto object-cover" onError={() => setPhotoOk(false)} />
                ) : (
                  <Avatar name={s.employee.name} size="xl" />
                )}
              </motion.div>
              <dl className="mx-6 mt-5 flex items-start justify-between gap-4 text-sm">
                <div><dt className="text-xs text-ink-3">Check In Time</dt><dd className="tabular mt-1 text-lg font-bold text-brand-700 dark:text-brand-200">{fmtTime(s.today?.first_in)}</dd></div>
                <div className="text-right"><dt className="text-xs text-ink-3">Check Out Time</dt><dd className="tabular mt-1 text-lg font-bold text-brand-700 dark:text-brand-200">{fmtTime(s.today?.last_out)}</dd></div>
              </dl>
              <div className="mx-6 mt-4 border-t border-line" />
              <div className="mx-6 mt-auto pt-4 pb-6">
                <p className="mb-3 text-center text-xs text-ink-3">{isOpen ? 'Worked so far' : 'Worked today'} <span className="tabular font-semibold text-ink">{fmtMinutes(liveMinutes)}</span></p>
                <Button size="xl" variant={action === 'check_in' ? 'primary' : 'accent'} className="w-full" onClick={() => setVerifyOpen(true)} disabled={!s.employee.enrolled}
                  leftIcon={action === 'check_in' ? <LogIn className="size-5" /> : <LogOut className="size-5" />}>
                  {action === 'check_in' ? 'Login from Office' : 'Logout from Office'}
                </Button>
                <p className="mt-3 flex items-center justify-center gap-1.5 text-center text-xs text-ink-3">
                  <ShieldCheck className="size-3.5 shrink-0" aria-hidden />
                  {s.employee.enrolled ? `Verified with your face — only ${s.employee.name.split(' ')[0]}'s enrolled face can log this account in or out.` : 'Your face is not enrolled yet. Ask an administrator to enrol you before using this button.'}
                </p>
              </div>
            </motion.section>

            <motion.section variants={itemVariants} className="card px-6 pt-5 pb-6" aria-labelledby="insights-h">
              <div className="flex items-baseline justify-between gap-3">
                <h2 id="insights-h" className="text-lg font-semibold">Your Attendance Insights</h2>
                <span className="text-xs text-ink-3">Last {insights.data?.window_days ?? 30} days</span>
              </div>
              {insights.isLoading ? (
                <div className="mt-5 grid gap-4 sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-20 rounded-2xl" />)}</div>
              ) : insights.isError ? (
                <EmptyState title="Insights unavailable" description={(insights.error as Error).message} />
              ) : insights.data && <InsightTiles data={insights.data} />}
            </motion.section>
          </div>

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


/** Gradient greeting band with four quick figures for the current month (mirrors the HR dashboard header). */
function SummaryBand({ name, workStart, workEnd, timezone, days, loading }: { name: string; workStart: string; workEnd: string; timezone: string; days: AttendanceDay[]; loading: boolean }) {
  const present = days.filter((d) => d.status !== 'absent' && d.first_in)
  const stats: { label: string; icon: ReactNode; value: ReactNode }[] = [
    { label: 'Days present', icon: <CalendarCheck2 className="size-5" />, value: <CountUp value={present.length} /> },
    { label: 'Hours this month', icon: <Hourglass className="size-5" />, value: fmtMinutes(present.reduce((a, d) => a + d.worked_minutes, 0)) },
    { label: 'Late arrivals', icon: <Timer className="size-5" />, value: <CountUp value={present.filter((d) => d.late_minutes > 0).length} /> },
    { label: 'Missed logouts', icon: <TriangleAlert className="size-5" />, value: <CountUp value={days.filter((d) => d.status === 'missing_checkout').length} /> },
  ]
  return (
    <motion.section variants={itemVariants} aria-labelledby="hello-h"
      className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-brand-700 via-brand-600 to-accent-500 px-6 py-6 text-white shadow-pop">
      <div aria-hidden className="pointer-events-none absolute -right-16 -top-24 size-72 rounded-full bg-white/10 blur-2xl" />
      <div aria-hidden className="pointer-events-none absolute -bottom-28 left-1/3 size-72 rounded-full bg-accent-300/20 blur-3xl" />
      <div className="relative flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-white/70">My attendance</p>
          <h1 id="hello-h" className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">Hello, {name.split(' ')[0]}</h1>
          <p className="mt-1 text-sm text-white/80">Working hours {workStart}–{workEnd} · {timezone}</p>
        </div>
        <ul className="grid gap-3 grid-cols-2 sm:grid-cols-4 lg:min-w-[560px]">
          {stats.map((st, i) => (
            <motion.li key={st.label} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ ...spring.gentle, delay: 0.08 + 0.05 * i }}
              className="flex flex-col items-start gap-2 rounded-xl bg-white/12 px-3.5 py-3 ring-1 ring-white/20 backdrop-blur-sm sm:flex-row sm:items-center sm:gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-full bg-white/15 text-white" aria-hidden>{st.icon}</span>
              <div className="min-w-0">
                <p className="text-[11px] font-medium uppercase leading-tight tracking-wide text-white/70">{st.label}</p>
                <p className="tabular text-xl font-bold leading-tight">{loading ? '—' : st.value}</p>
              </div>
            </motion.li>
          ))}
        </ul>
      </div>
    </motion.section>
  )
}

type InsightTone = 'purple' | 'sky' | 'indigo' | 'green' | 'red'
const TILE_TONES: Record<InsightTone, { bg: string; icon: string; value: string; label: string }> = {
  purple: { bg: 'bg-brand-100/70 dark:bg-brand-800/30', icon: 'text-brand-700 dark:text-brand-200', value: 'text-brand-800 dark:text-brand-100', label: 'text-brand-700/80 dark:text-brand-200/80' },
  sky: { bg: 'bg-sky-100/70 dark:bg-sky-900/30', icon: 'text-sky-600 dark:text-sky-300', value: 'text-sky-600 dark:text-sky-200', label: 'text-sky-700/80 dark:text-sky-200/80' },
  indigo: { bg: 'bg-indigo-100/70 dark:bg-indigo-900/30', icon: 'text-indigo-600 dark:text-indigo-300', value: 'text-indigo-600 dark:text-indigo-200', label: 'text-indigo-700/80 dark:text-indigo-200/80' },
  green: { bg: 'bg-emerald-100/70 dark:bg-emerald-900/30', icon: 'text-emerald-700 dark:text-emerald-300', value: 'text-emerald-700 dark:text-emerald-200', label: 'text-emerald-800/80 dark:text-emerald-200/80' },
  red: { bg: 'bg-red-100/70 dark:bg-red-900/30', icon: 'text-red-600 dark:text-red-300', value: 'text-red-600 dark:text-red-200', label: 'text-red-700/80 dark:text-red-200/80' },
}

function InsightTile({ tone, icon, label, children, hint, index }: { tone: InsightTone; icon: ReactNode; label: string; children: ReactNode; hint?: string; index: number }) {
  const t = TILE_TONES[tone]
  return (
    <motion.div
      initial={{ opacity: 0, y: 14, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ ...spring.gentle, delay: 0.05 * index }}
      whileHover={{ y: -3 }} title={hint}
      className={cn('flex items-center gap-3.5 rounded-2xl p-4 shadow-[0_1px_0_rgba(109,40,217,0.04)]', t.bg)}
    >
      <motion.span initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ ...spring.snappy, delay: 0.05 * index + 0.12 }}
        className={cn('grid size-12 shrink-0 place-items-center rounded-full bg-white shadow-sm dark:bg-surface', t.icon)} aria-hidden>
        {icon}
      </motion.span>
      <div className="min-w-0">
        <p className={cn('text-[13px] font-medium leading-snug', t.label)}>{label}</p>
        <p className={cn('mt-0.5 text-2xl font-bold leading-tight tracking-tight', t.value)}>{children}</p>
      </div>
    </motion.div>
  )
}

function InsightTiles({ data }: { data: MyInsights }) {
  const avgH = data.avg_daily_minutes === null ? null : Math.floor(data.avg_daily_minutes / 60)
  const avgM = data.avg_daily_minutes === null ? null : data.avg_daily_minutes % 60
  const n = data.days_present
  return (
    <div className="mt-5 grid gap-3.5 sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2">
      <InsightTile index={0} tone="purple" icon={<Clock className="size-6" />} label="Average Daily Hours" hint={`Across ${n} completed day${n === 1 ? '' : 's'}`}>
        {avgH === null ? '—' : <>{avgH}h {String(avgM).padStart(2, '0')}m</>}
      </InsightTile>
      <InsightTile index={1} tone="sky" icon={<ClockArrowUp className="size-6" />} label="Average Check-In Time" hint={`Local time (${data.timezone})`}>
        {fmtClock(data.avg_check_in_minutes)}
      </InsightTile>
      <InsightTile index={2} tone="indigo" icon={<ClockArrowDown className="size-6" />} label="Average Check-Out Time" hint={`Local time (${data.timezone})`}>
        {fmtClock(data.avg_check_out_minutes)}
      </InsightTile>
      <InsightTile index={3} tone="green" icon={<AlarmClockCheck className="size-6" />} label="On-Time Arrival Rate" hint={`${n - data.late_days} of ${n} days on time`}>
        {data.on_time_rate === null ? '—' : <CountUp value={Math.round(data.on_time_rate * 100)} suffix="%" />}
      </InsightTile>
      <InsightTile index={4} tone="red" icon={<TriangleAlert className="size-6" />} label="Black Points" hint={`${data.late_days} late arrival${data.late_days === 1 ? '' : 's'} + ${data.missing_checkouts} missed logout${data.missing_checkouts === 1 ? '' : 's'}`}>
        <CountUp value={data.black_points} />
      </InsightTile>
    </div>
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

  const stream = useVerificationStream({ purpose: 'attendance', selfBound: true, grabFrame: cam.grabFrame, fps: 10, onTerminal })
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
                <Welcome action={recorded.action} name={employeeName} className="mt-3 [&_h2]:text-2xl [&_p]:text-sm" />
                <p className="tabular mt-2 text-3xl font-semibold">{fmtTime(recorded.occurred_at)}</p>
                <p className="mt-1 text-xs text-ink-3">{recorded.action === 'check_in' ? 'Login time' : 'Logout time'}</p>
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
