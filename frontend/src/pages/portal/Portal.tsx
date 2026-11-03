import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { motion } from 'motion/react'
import { CalendarDays, Clock, LogIn, LogOut, ScanFace, UserX } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { fmtDate, fmtMinutes, fmtTime } from '../../lib/format'
import { itemVariants, listVariants } from '../../lib/motion'
import type { AttendanceDay, AttendanceEvent, Page } from '../../lib/types'
import { Badge, StatusBadge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { EmptyState, PageHeader, Skeleton } from '../../components/ui/Misc'

interface MyStatus {
  employee: { id: string; name: string; code: string }
  next: { next: 'check_in' | 'check_out'; last_event: { id: string; action: string; occurred_at: string; method: string } | null; attendance_date: string }
  today: AttendanceDay | null
  work_start: string
  work_end: string
  timezone: string
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
  const status = useQuery({ queryKey: ['me', 'status'], queryFn: () => api.get<MyStatus>('/attendance/me/status'), refetchInterval: 60_000, retry: false })
  const monthStart = new Date()
  monthStart.setDate(1)
  const from = monthStart.toISOString().slice(0, 10)
  const days = useQuery({ queryKey: ['me', 'days', from], queryFn: () => api.get<Page<AttendanceDay>>('/attendance/me/days', { date_from: from, page_size: 31 }), enabled: status.isSuccess })
  const [selected, setSelected] = useState<string | null>(null)
  const events = useQuery({ queryKey: ['me', 'events', selected], queryFn: () => api.get<AttendanceEvent[]>('/attendance/me/events', { attendance_date: selected }), enabled: !!selected })

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

  return (
    <>
      <PageHeader title={s ? `Hello, ${s.employee.name.split(' ')[0]}` : 'My attendance'} description={s ? `Working hours ${s.work_start}–${s.work_end} (${s.timezone})` : undefined} actions={
        <Button variant="accent" leftIcon={<ScanFace className="size-4" />} onClick={() => { window.location.href = '/kiosk' }}>Go to kiosk</Button>
      } />

      {status.isLoading ? <Skeleton className="h-40" /> : status.isError ? (
        <Card><EmptyState title="Could not load your status" description={(status.error as Error).message} /></Card>
      ) : s && (
        <motion.div variants={listVariants} initial="hidden" animate="show" className="space-y-4">
          <motion.div variants={itemVariants} className="card overflow-hidden">
            <div className="grid gap-6 p-6 sm:grid-cols-[1fr_auto] sm:items-center">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-ink-3">{fmtDate(s.next.attendance_date, 'EEEE, d MMMM')}</p>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <h2 className="text-2xl font-semibold">{isOpen ? 'You are checked in' : s.today && s.today.last_out ? 'You have checked out' : 'Not checked in yet'}</h2>
                  {s.today && <StatusBadge status={s.today.status} />}
                </div>
                <dl className="mt-4 grid grid-cols-3 gap-4 text-sm">
                  <div><dt className="text-ink-3">First in</dt><dd className="tabular mt-0.5 text-lg font-medium">{fmtTime(s.today?.first_in)}</dd></div>
                  <div><dt className="text-ink-3">Last out</dt><dd className="tabular mt-0.5 text-lg font-medium">{fmtTime(s.today?.last_out)}</dd></div>
                  <div><dt className="text-ink-3">{isOpen ? 'Worked so far' : 'Worked today'}</dt><dd className="tabular mt-0.5 text-lg font-medium">{fmtMinutes(liveMinutes)}</dd></div>
                </dl>
              </div>
              <div className="flex flex-col items-start gap-2 rounded-lg bg-surface-3 p-4 text-sm sm:items-center sm:text-center">
                <span className="grid size-10 place-items-center rounded-full bg-surface text-brand-700">{s.next.next === 'check_in' ? <LogIn className="size-5" /> : <LogOut className="size-5" />}</span>
                <p className="text-ink-3">Next action</p>
                <p className="font-medium">{s.next.next === 'check_in' ? 'Check in' : 'Check out'}</p>
                <Link to="/kiosk" className="text-xs text-brand-600 dark:text-brand-300 hover:underline">Use the kiosk</Link>
              </div>
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
