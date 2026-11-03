import { useQuery } from '@tanstack/react-query'
import { motion } from 'motion/react'
import { Link } from 'react-router-dom'
import { Activity, AlertTriangle, Clock, Cpu, ScanFace, UserCheck, Users, UserX } from 'lucide-react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../../lib/api'
import { fmtAgo, fmtDate, fmtTime } from '../../lib/format'
import { listVariants } from '../../lib/motion'
import type { AttendanceEvent, Dashboard as DashboardData } from '../../lib/types'
import { Badge } from '../../components/ui/Badge'
import { CardBody, CardHeader, MotionCard } from '../../components/ui/Card'
import { Avatar, EmptyState, PageHeader, Skeleton, Stat } from '../../components/ui/Misc'

interface Feed {
  events: AttendanceEvent[]
  failed_verifications: Array<{ id: string; outcome: string; reason: string | null; liveness_score: number | null; match_score: number | null; created_at: string; ip: string | null }>
}

const OUTCOME_COLOURS: Record<string, string> = {
  identified: '#059669', unknown: '#64748b', ambiguous: '#d97706', spoof: '#dc2626', challenge_failed: '#dc2626',
  timeout: '#94a3b8', quality: '#94a3b8', no_face: '#94a3b8', multiple_faces: '#d97706',
}

const outcomeLabel = (k: string) => k.replace(/_/g, ' ')

export default function Dashboard() {
  const dash = useQuery({ queryKey: ['dashboard'], queryFn: () => api.get<DashboardData>('/dashboard'), refetchInterval: 30_000 })
  const feed = useQuery({ queryKey: ['feed'], queryFn: () => api.get<Feed>('/attendance/feed', { limit: 12 }), refetchInterval: 10_000 })

  const d = dash.data
  const outcomes = d ? Object.entries(d.verification_7d).filter(([k, v]) => k !== 'total' && v > 0).map(([k, v]) => ({ name: outcomeLabel(k), key: k, value: v })) : []

  return (
    <>
      <PageHeader eyebrow={d ? fmtDate(d.date, 'EEEE, d MMMM yyyy') : undefined} title="Dashboard" description="Live attendance across the organisation, verification health and recent activity." />

      {dash.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      ) : dash.isError ? (
        <div className="card"><EmptyState icon={<AlertTriangle className="size-5" />} title="Dashboard unavailable" description={(dash.error as Error).message} /></div>
      ) : d ? (
        <motion.div variants={listVariants} initial="hidden" animate="show" className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Present today" value={d.kpis.present_today} icon={<UserCheck className="size-5" />} tone="success" delta={`${d.kpis.attendance_rate}% of ${d.kpis.employees} active`} />
            <Stat label="On site now" value={d.kpis.on_site_now} icon={<Activity className="size-5" />} delta="Open check-ins" />
            <Stat label="Late arrivals" value={d.kpis.late_today} icon={<Clock className="size-5" />} tone={d.kpis.late_today ? 'warning' : 'neutral'} delta="After grace period" />
            <Stat label="Absent" value={d.kpis.absent_today} icon={<UserX className="size-5" />} tone={d.kpis.absent_today ? 'danger' : 'neutral'} delta={`${d.kpis.enrolled} of ${d.kpis.employees} enrolled`} />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <MotionCard className="lg:col-span-2">
              <CardHeader title="Attendance trend" description="Present and late, last 14 days" />
              <CardBody>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={d.trend} margin={{ left: -20, right: 8, top: 8 }}>
                      <defs>
                        <linearGradient id="gPresent" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#1e3a5f" stopOpacity={0.35} /><stop offset="100%" stopColor="#1e3a5f" stopOpacity={0} /></linearGradient>
                        <linearGradient id="gLate" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#d97706" stopOpacity={0.35} /><stop offset="100%" stopColor="#d97706" stopOpacity={0} /></linearGradient>
                      </defs>
                      <CartesianGrid stroke="var(--line)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={(v: string) => fmtDate(v, 'd MMM')} tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <Tooltip labelFormatter={(v) => fmtDate(String(v), 'EEE d MMM')} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} />
                      <Area type="monotone" dataKey="present" name="Present" stroke="#1e3a5f" fill="url(#gPresent)" strokeWidth={2} />
                      <Area type="monotone" dataKey="late" name="Late" stroke="#d97706" fill="url(#gLate)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <p className="mt-2 text-xs text-ink-3">
                  Over the last 14 days: {d.trend.reduce((a, t) => a + t.present, 0)} present-days and {d.trend.reduce((a, t) => a + t.late, 0)} late arrivals.
                </p>
              </CardBody>
            </MotionCard>

            <MotionCard>
              <CardHeader title="Average hours" description="Per present employee" />
              <CardBody>
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={d.trend} margin={{ left: -20, right: 8, top: 8 }}>
                      <CartesianGrid stroke="var(--line)" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={(v: string) => fmtDate(v, 'd')} tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} />
                      <Tooltip labelFormatter={(v) => fmtDate(String(v), 'EEE d MMM')} formatter={(v) => [`${v} h`, 'Avg hours']} contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} />
                      <Line type="monotone" dataKey="avg_hours" stroke="#059669" strokeWidth={2} dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
                <p className="mt-2 text-xs text-ink-3">Latest day: {d.trend[d.trend.length - 1]?.avg_hours ?? 0} hours on average.</p>
              </CardBody>
            </MotionCard>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <MotionCard>
              <CardHeader title="Departments" description="Present today vs headcount" />
              <CardBody>
                {d.departments.length === 0 ? <EmptyState title="No departments yet" description="Create departments from the Employees page." /> : (
                  <>
                    <div className="h-48">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={d.departments} layout="vertical" margin={{ left: 8, right: 8 }}>
                          <CartesianGrid stroke="var(--line)" horizontal={false} />
                          <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                          <YAxis type="category" dataKey="name" width={90} tick={{ fontSize: 11, fill: 'var(--ink-2)' }} axisLine={false} tickLine={false} />
                          <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} />
                          <Bar dataKey="headcount" name="Headcount" fill="var(--line-2)" radius={4} barSize={10} />
                          <Bar dataKey="present_today" name="Present" fill="#059669" radius={4} barSize={10} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                    <ul className="mt-2 space-y-1 text-xs text-ink-3">
                      {d.departments.map((x) => <li key={x.id}>{x.name}: {x.present_today} of {x.headcount} present</li>)}
                    </ul>
                  </>
                )}
              </CardBody>
            </MotionCard>

            <MotionCard>
              <CardHeader title="Verification outcomes" description="Last 7 days" />
              <CardBody>
                {outcomes.length === 0 ? <EmptyState icon={<ScanFace className="size-5" />} title="No verifications yet" description="Outcomes appear once employees use the kiosk." /> : (
                  <div className="flex items-center gap-4">
                    <div className="h-40 w-40 shrink-0">
                      <ResponsiveContainer width="100%" height="100%">
                        <PieChart>
                          <Pie data={outcomes} dataKey="value" nameKey="name" innerRadius={42} outerRadius={64} paddingAngle={2} stroke="none">
                            {outcomes.map((o) => <Cell key={o.key} fill={OUTCOME_COLOURS[o.key] ?? '#94a3b8'} />)}
                          </Pie>
                          <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 }} />
                        </PieChart>
                      </ResponsiveContainer>
                    </div>
                    <ul className="min-w-0 flex-1 space-y-1.5 text-sm">
                      {outcomes.map((o) => (
                        <li key={o.key} className="flex items-center gap-2">
                          <span className="size-2.5 shrink-0 rounded-full" style={{ background: OUTCOME_COLOURS[o.key] ?? '#94a3b8' }} aria-hidden />
                          <span className="min-w-0 flex-1 truncate capitalize text-ink-2">{o.name}</span>
                          <span className="tabular font-medium">{o.value}</span>
                        </li>
                      ))}
                      <li className="pt-1 text-xs text-ink-3">{d.verification_7d.total} attempts in total</li>
                    </ul>
                  </div>
                )}
              </CardBody>
            </MotionCard>

            <MotionCard>
              <CardHeader title="Recognition engine" description="Server-side status" />
              <CardBody className="space-y-3">
                <div className="flex items-center gap-3 rounded-lg bg-surface-3 p-3">
                  <Cpu className="size-5 text-ink-2" aria-hidden />
                  <div className="text-sm">
                    <p className="font-medium">{d.engine.index_employees} employees indexed</p>
                    <p className="text-ink-3">{d.engine.index_templates} face templates · {d.engine.workers} inference workers</p>
                  </div>
                </div>
                <div className="flex items-center gap-3 rounded-lg bg-surface-3 p-3">
                  <Users className="size-5 text-ink-2" aria-hidden />
                  <div className="text-sm">
                    <p className="font-medium">{d.kpis.enrolled} of {d.kpis.employees} enrolled</p>
                    <p className="text-ink-3">{d.kpis.employees - d.kpis.enrolled > 0 ? <Link className="text-brand-600 hover:underline" to="/admin/employees?enrolled=false">{d.kpis.employees - d.kpis.enrolled} awaiting enrolment</Link> : 'Everyone is enrolled'}</p>
                  </div>
                </div>
              </CardBody>
            </MotionCard>
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <MotionCard className="lg:col-span-2">
              <CardHeader title="Live activity" description="Most recent check-ins and check-outs" action={<Badge tone="success" dot>Live</Badge>} />
              <CardBody className="px-0">
                {feed.isLoading ? <div className="space-y-2 px-5">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
                : !feed.data?.events.length ? <EmptyState icon={<Activity className="size-5" />} title="No activity yet today" description="Events will stream in as employees use the kiosk." />
                : (
                  <ul className="divide-y divide-line">
                    {feed.data.events.map((e) => (
                      <li key={e.id} className="flex items-center gap-3 px-5 py-2.5">
                        <Avatar name={e.employee_name} size="sm" />
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium">{e.employee_name ?? e.employee_id} <span className="font-normal text-ink-3">· {e.employee_code}</span></p>
                          <p className="text-xs text-ink-3">{e.department_name ?? 'No department'} · {fmtAgo(e.occurred_at)}</p>
                        </div>
                        <Badge tone={e.action === 'check_in' ? 'success' : 'brand'}>{e.action === 'check_in' ? 'Checked in' : 'Checked out'}</Badge>
                        <span className="tabular w-12 text-right text-sm text-ink-2">{fmtTime(e.occurred_at)}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </MotionCard>

            <MotionCard>
              <CardHeader title="Failed verifications" description="Recent rejections at the kiosk" />
              <CardBody className="px-0">
                {!feed.data?.failed_verifications.length ? <EmptyState icon={<AlertTriangle className="size-5" />} title="No failures recorded" /> : (
                  <ul className="divide-y divide-line">
                    {feed.data.failed_verifications.map((f) => (
                      <li key={f.id} className="flex items-center gap-3 px-5 py-2.5 text-sm">
                        <span className="size-2 shrink-0 rounded-full" style={{ background: OUTCOME_COLOURS[f.outcome] ?? '#94a3b8' }} aria-hidden />
                        <div className="min-w-0 flex-1">
                          <p className="capitalize">{outcomeLabel(f.outcome)}</p>
                          <p className="text-xs text-ink-3">{fmtAgo(f.created_at)}{f.liveness_score != null && ` · liveness ${f.liveness_score.toFixed(2)}`}</p>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardBody>
            </MotionCard>
          </div>
        </motion.div>
      ) : null}
    </>
  )
}
