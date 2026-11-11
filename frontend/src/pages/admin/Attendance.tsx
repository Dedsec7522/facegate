import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { AlertTriangle, Download, FileSpreadsheet, PencilLine, ScanFace } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { daysAgoISO, fmtDate, fmtDateTime, fmtMinutes, fmtTime, todayISO } from '../../lib/format'
import type { AttendanceDay, AttendanceEvent, Correction, Department, Employee, Page, TodayBoard, VerificationAttempt } from '../../lib/types'
import { Badge, StatusBadge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { Dialog } from '../../components/ui/Dialog'
import { Input, Select, Textarea } from '../../components/ui/Field'
import { Avatar, EmptyState, PageHeader, Pagination, Skeleton, Table, Tabs, Td, Th } from '../../components/ui/Misc'
import { useToast } from '../../components/ui/Toast'

type Tab = 'today' | 'days' | 'events' | 'corrections' | 'failed'
const tooltip = { background: 'var(--surface)' }
void tooltip

const methodTone = { face: 'brand', pin: 'info', manual: 'warning' } as const

export default function Attendance() {
  const [params, setParams] = useSearchParams()
  const [tab, setTab] = useState<Tab>((params.get('tab') as Tab) || (params.get('employee_id') ? 'days' : 'today'))
  const [from, setFrom] = useState(daysAgoISO(13))
  const [to, setTo] = useState(todayISO())
  const [dep, setDep] = useState('')
  const [employeeId, setEmployeeId] = useState(params.get('employee_id') ?? '')
  const deps = useQuery({ queryKey: ['departments'], queryFn: () => api.get<Department[]>('/departments') })
  useEffect(() => { setParams((p) => { p.set('tab', tab); return p }, { replace: true }) }, [tab, setParams])

  const exportUrl = (fmt: 'csv' | 'xlsx') => `/api/v1/attendance/export?fmt=${fmt}&date_from=${from}&date_to=${to}${dep ? `&department_id=${dep}` : ''}`

  return (
    <>
      <PageHeader title="Attendance" description="Live board, daily summaries, raw events, corrections and failed verifications." actions={
        <>
          <Button variant="outline" leftIcon={<Download className="size-4" />} onClick={() => window.open(exportUrl('csv'), '_blank')}>CSV</Button>
          <Button variant="outline" leftIcon={<FileSpreadsheet className="size-4" />} onClick={() => window.open(exportUrl('xlsx'), '_blank')}>Excel</Button>
        </>
      } />
      <Tabs className="mb-4" value={tab} onChange={setTab} items={[{ value: 'today', label: 'Today' }, { value: 'days', label: 'Days' }, { value: 'events', label: 'Events' }, { value: 'corrections', label: 'Corrections' }, { value: 'failed', label: 'Failed verifications' }]} />

      {tab !== 'today' && tab !== 'corrections' && (
        <Card className="mb-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-4">
          <Input label="From" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
          <Input label="To" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
          <Select label="Department" value={dep} onChange={(e) => setDep(e.target.value)}>
            <option value="">All departments</option>
            {deps.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          {tab !== 'failed' && <EmployeePicker label="Employee" value={employeeId} onChange={setEmployeeId} />}
        </Card>
      )}

      {tab === 'today' && <TodayTab />}
      {tab === 'days' && <DaysTab from={from} to={to} dep={dep} employeeId={employeeId} />}
      {tab === 'events' && <EventsTab from={from} to={to} dep={dep} employeeId={employeeId} />}
      {tab === 'corrections' && <CorrectionsTab />}
      {tab === 'failed' && <FailedTab from={from} />}
    </>
  )
}

function EmployeePicker({ label, value, onChange, required }: { label: string; value: string; onChange: (id: string) => void; required?: boolean }) {
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t) }, [q])
  const res = useQuery({ queryKey: ['employees', 'picker', dq], queryFn: () => api.get<Page<Employee>>('/employees', { q: dq, page_size: 50 }) })
  return (
    <div className="flex flex-col gap-1.5">
      <Select label={label} required={required} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{required ? 'Select an employee' : 'All employees'}</option>
        {res.data?.items.map((e) => <option key={e.id} value={e.id}>{e.first_name} {e.last_name} · {e.employee_code}</option>)}
      </Select>
      <input aria-label="Filter employee list" placeholder="Type to filter…" value={q} onChange={(e) => setQ(e.target.value)} className="h-8 rounded-md border border-line bg-surface px-2 text-xs" />
    </div>
  )
}

function TodayTab() {
  const board = useQuery({ queryKey: ['today'], queryFn: () => api.get<TodayBoard>('/attendance/today'), refetchInterval: 15_000 })
  const [filter, setFilter] = useState('')
  if (board.isLoading) return <Skeleton className="h-96" />
  if (!board.data) return <Card><EmptyState title="Board unavailable" /></Card>
  const s = board.data.summary
  const items = board.data.items.filter((i) => !filter || i.status === filter || (filter === 'on_site' && i.is_open))
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2 border-b border-line p-4">
        {[{ k: '', l: `All ${s.total}` }, { k: 'on_site', l: `On site ${s.on_site}` }, { k: 'present', l: `Present ${s.present}` }, { k: 'late', l: `Late ${s.late}` }, { k: 'missing_checkout', l: `Missing check-out ${s.missing_checkout}` }, { k: 'absent', l: `Absent ${s.absent}` }].map((c) => (
          <button key={c.k} onClick={() => setFilter(c.k)} className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${filter === c.k ? 'border-brand-700 bg-brand-700 text-white' : 'border-line hover:bg-surface-3'}`}>{c.l}</button>
        ))}
        <span className="ml-auto flex items-center gap-1.5 text-xs text-ink-3"><span className="size-1.5 animate-pulse rounded-full bg-accent-500" />Refreshes every 15s · {fmtDate(s.date, 'EEE d MMM')}</span>
      </div>
      {items.length === 0 ? <EmptyState title="Nobody in this group" /> : (
        <Table>
          <thead><tr><Th>Employee</Th><Th>Department</Th><Th>Status</Th><Th>First in</Th><Th>Last out</Th><Th>Worked</Th></tr></thead>
          <tbody>
            {items.map((i) => (
              <tr key={i.employee_id}>
                <Td><div className="flex items-center gap-3"><Avatar name={i.name} size="sm" /><div><p className="font-medium">{i.name}</p><p className="text-xs text-ink-3">{i.code}</p></div></div></Td>
                <Td className="text-ink-2">{i.department ?? '—'}</Td>
                <Td><span className="flex items-center gap-2"><StatusBadge status={i.status} />{i.is_open && <Badge tone="success">On site</Badge>}</span></Td>
                <Td className="tabular">{fmtTime(i.first_in)}</Td>
                <Td className="tabular">{fmtTime(i.last_out)}</Td>
                <Td className="tabular">{fmtMinutes(i.worked_minutes)}{i.late_minutes > 0 && <span className="ml-2 text-xs text-amber-600">+{i.late_minutes}m late</span>}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function DaysTab({ from, to, dep, employeeId }: { from: string; to: string; dep: string; employeeId: string }) {
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const q = useQuery({ queryKey: ['days', { from, to, dep, employeeId, status, page }], queryFn: () => api.get<Page<AttendanceDay>>('/attendance/days', { date_from: from, date_to: to, department_id: dep, employee_id: employeeId, status, page, page_size: 50 }), placeholderData: (p) => p })
  return (
    <Card>
      <div className="flex items-center gap-3 border-b border-line p-4">
        <Select aria-label="Status filter" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1) }} wrapperClassName="w-56">
          <option value="">Any status</option><option value="present">Present</option><option value="late">Late</option><option value="missing_checkout">Missing check-out</option><option value="corrected">Corrected</option><option value="absent">Absent</option>
        </Select>
        <span className="text-sm text-ink-3">{q.data?.total ?? 0} days</span>
      </div>
      {q.isLoading ? <Skeleton className="m-4 h-64" /> : !q.data?.items.length ? <EmptyState title="No attendance days in this range" /> : (
        <>
          <Table>
            <thead><tr><Th>Date</Th><Th>Employee</Th><Th>Department</Th><Th>First in</Th><Th>Last out</Th><Th>Worked</Th><Th>Late</Th><Th>Early leave</Th><Th>Status</Th></tr></thead>
            <tbody>
              {q.data.items.map((d) => (
                <tr key={d.id}>
                  <Td className="font-medium whitespace-nowrap">{fmtDate(d.attendance_date)}</Td>
                  <Td><p className="font-medium">{d.employee_name}</p><p className="text-xs text-ink-3">{d.employee_code}</p></Td>
                  <Td className="text-ink-2">{d.department_name ?? '—'}</Td>
                  <Td className="tabular">{fmtTime(d.first_in)}</Td>
                  <Td className="tabular">{fmtTime(d.last_out)}</Td>
                  <Td className="tabular">{fmtMinutes(d.worked_minutes)}</Td>
                  <Td className={d.late_minutes ? 'text-amber-600' : 'text-ink-3'}>{d.late_minutes ? `${d.late_minutes}m` : '—'}</Td>
                  <Td className={d.early_leave_minutes ? 'text-amber-600' : 'text-ink-3'}>{d.early_leave_minutes ? `${d.early_leave_minutes}m` : '—'}</Td>
                  <Td><StatusBadge status={d.status} /></Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pagination page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onPage={setPage} />
        </>
      )}
    </Card>
  )
}

function EventsTab({ from, to, dep, employeeId }: { from: string; to: string; dep: string; employeeId: string }) {
  const [page, setPage] = useState(1)
  const [method, setMethod] = useState('')
  const [voided, setVoided] = useState(false)
  const q = useQuery({ queryKey: ['events', { from, to, dep, employeeId, method, voided, page }], queryFn: () => api.get<Page<AttendanceEvent>>('/attendance/events', { date_from: from, date_to: to, department_id: dep, employee_id: employeeId, method, include_voided: voided, page, page_size: 50 }), placeholderData: (p) => p })
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-3 border-b border-line p-4">
        <Select aria-label="Method" value={method} onChange={(e) => { setMethod(e.target.value); setPage(1) }} wrapperClassName="w-44">
          <option value="">Any method</option><option value="face">Face</option><option value="pin">PIN</option><option value="manual">Manual</option>
        </Select>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={voided} onChange={(e) => setVoided(e.target.checked)} className="size-4 accent-brand-700" /> Include voided</label>
        <span className="ml-auto text-sm text-ink-3">{q.data?.total ?? 0} events</span>
      </div>
      {q.isLoading ? <Skeleton className="m-4 h-64" /> : !q.data?.items.length ? <EmptyState title="No events in this range" /> : (
        <>
          <Table>
            <thead><tr><Th>When</Th><Th>Employee</Th><Th>Action</Th><Th>Method</Th><Th>Match</Th><Th>Liveness</Th><Th>Day</Th></tr></thead>
            <tbody>
              {q.data.items.map((e) => (
                <tr key={e.id} className={e.voided ? 'opacity-50' : ''}>
                  <Td className="tabular whitespace-nowrap">{fmtDateTime(e.occurred_at)}</Td>
                  <Td><p className="font-medium">{e.employee_name}</p><p className="text-xs text-ink-3">{e.employee_code} · {e.department_name ?? '—'}</p></Td>
                  <Td><Badge tone={e.action === 'check_in' ? 'success' : 'brand'}>{e.action === 'check_in' ? 'Check in' : 'Check out'}</Badge>{e.voided && <Badge tone="danger" className="ml-1">Voided</Badge>}</Td>
                  <Td><Badge tone={methodTone[e.method]}>{e.method}</Badge></Td>
                  <Td className="tabular text-ink-2">{e.match_score?.toFixed(2) ?? '—'}</Td>
                  <Td className="tabular text-ink-2">{e.liveness_score?.toFixed(2) ?? '—'}</Td>
                  <Td className="whitespace-nowrap text-ink-3">{fmtDate(e.attendance_date)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pagination page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onPage={setPage} />
        </>
      )}
    </Card>
  )
}

function CorrectionsTab() {
  const toast = useToast()
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ['corrections'], queryFn: () => api.get<Correction[]>('/attendance/corrections', { limit: 200 }) })
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<'add' | 'void' | 'adjust' | 'leave' | 'clear_leave'>('add')
  const needsEvent = kind === 'void' || kind === 'adjust'
  const isLeave = kind === 'leave' || kind === 'clear_leave'
  const [employeeId, setEmployeeId] = useState('')
  const [eventId, setEventId] = useState('')
  const [action, setAction] = useState('check_in')
  const [when, setWhen] = useState('')
  const [reason, setReason] = useState('')
  const events = useQuery({ queryKey: ['events', 'for-correction', employeeId], queryFn: () => api.get<Page<AttendanceEvent>>('/attendance/events', { employee_id: employeeId, page_size: 50 }), enabled: !!employeeId && needsEvent })
  const create = useMutation({
    // Leave takes a date: send noon local time so the organisation's attendance day is the one picked.
    mutationFn: () => api.post<Correction>('/attendance/corrections', { employee_id: employeeId, kind, reason, event_id: needsEvent ? eventId : undefined, action: kind === 'add' || kind === 'adjust' ? action : undefined,
      occurred_at: kind === 'void' || !when ? undefined : isLeave ? new Date(`${when}T12:00:00`).toISOString() : new Date(when).toISOString() }),
    onSuccess: () => { toast.success('Correction recorded', 'The daily summary has been recomputed and the change is audited.'); setOpen(false); setReason(''); setEventId(''); setWhen(''); void qc.invalidateQueries({ queryKey: ['corrections'] }); void qc.invalidateQueries({ queryKey: ['days'] }); void qc.invalidateQueries({ queryKey: ['events'] }); void qc.invalidateQueries({ queryKey: ['today'] }) },
    onError: (e: ApiError) => toast.error('Correction rejected', e.message),
  })
  const valid = employeeId && reason.trim().length >= 5 && (kind === 'add' || isLeave ? !!when : !!eventId)
  const fmtChange = (x: Record<string, unknown> | null | undefined) => !x ? '—' : 'status' in x ? `status: ${String(x.status)}` : `${String(x.action)} ${fmtDateTime(String(x.occurred_at))}`
  return (
    <Card>
      <div className="flex items-center justify-between border-b border-line p-4">
        <p className="text-sm text-ink-3">Corrections never edit the original events; they void and add, with a reason, and are written to the audit log.</p>
        <Button leftIcon={<PencilLine className="size-4" />} onClick={() => setOpen(true)}>New correction</Button>
      </div>
      {list.isLoading ? <Skeleton className="m-4 h-48" /> : !list.data?.length ? <EmptyState title="No corrections yet" /> : (
        <Table>
          <thead><tr><Th>When</Th><Th>Kind</Th><Th>Day</Th><Th>Before</Th><Th>After</Th><Th>Reason</Th></tr></thead>
          <tbody>
            {list.data.map((c) => (
              <tr key={c.id}>
                <Td className="tabular whitespace-nowrap">{fmtDateTime(c.created_at)}</Td>
                <Td><Badge tone={c.kind === 'void' ? 'danger' : c.kind === 'add' ? 'success' : c.kind === 'leave' ? 'info' : 'warning'}>{c.kind.replace('_', ' ')}</Badge></Td>
                <Td className="whitespace-nowrap">{fmtDate(c.attendance_date)}</Td>
                <Td className="text-xs text-ink-2">{fmtChange(c.before)}</Td>
                <Td className="text-xs text-ink-2">{fmtChange(c.after)}</Td>
                <Td className="max-w-xs text-ink-2">{c.reason}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <Dialog open={open} onClose={() => setOpen(false)} title="New attendance correction" description="Choose the employee, what to change, and give an auditable reason." footer={<><Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={() => create.mutate()} disabled={!valid} loading={create.isPending}>Record correction</Button></>}>
        <div className="space-y-4">
          <EmployeePicker label="Employee" value={employeeId} onChange={(id) => { setEmployeeId(id); setEventId('') }} required />
          <Select label="Kind" value={kind} onChange={(e) => { setKind(e.target.value as typeof kind); setWhen('') }}>
            <option value="add">Add a missing event</option><option value="void">Void an incorrect event</option><option value="adjust">Adjust an event's time</option>
            <option value="leave">Mark a day as leave</option><option value="clear_leave">Clear a leave day</option>
          </Select>
          {isLeave && <Input label="Day" type="date" required value={when} onChange={(e) => setWhen(e.target.value)} hint="The day must have no attendance events. Shown in yellow on the employee's calendar." />}
          {needsEvent && (
            <Select label="Event" required value={eventId} onChange={(e) => setEventId(e.target.value)} hint={!employeeId ? 'Select an employee first' : undefined}>
              <option value="">Select the event</option>
              {events.data?.items.map((ev) => <option key={ev.id} value={ev.id}>{fmtDateTime(ev.occurred_at)} · {ev.action.replace('_', ' ')} · {ev.method}</option>)}
            </Select>
          )}
          {(kind === 'add' || kind === 'adjust') && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Select label="Action" value={action} onChange={(e) => setAction(e.target.value)}><option value="check_in">Check in</option><option value="check_out">Check out</option></Select>
              <Input label="Date & time" type="datetime-local" required={kind === 'add'} value={when} onChange={(e) => setWhen(e.target.value)} />
            </div>
          )}
          <Textarea label="Reason" required hint="Minimum 5 characters. Shown in the audit log." value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
      </Dialog>
    </Card>
  )
}

function FailedTab({ from }: { from: string }) {
  const [page, setPage] = useState(1)
  const [outcome, setOutcome] = useState('')
  const q = useQuery({ queryKey: ['attempts', { from, outcome, page }], queryFn: () => api.get<Page<VerificationAttempt>>('/attendance/verification-attempts', { date_from: from, outcome, page, page_size: 50 }), placeholderData: (p) => p })
  const tone = (o: string) => (o === 'identified' ? 'success' : o === 'spoof' || o === 'challenge_failed' ? 'danger' : o === 'ambiguous' ? 'warning' : 'neutral') as 'success' | 'danger' | 'warning' | 'neutral'
  return (
    <Card>
      <div className="flex items-center gap-3 border-b border-line p-4">
        <Select aria-label="Outcome" value={outcome} onChange={(e) => { setOutcome(e.target.value); setPage(1) }} wrapperClassName="w-56">
          <option value="">All outcomes</option>
          {['identified', 'unknown', 'ambiguous', 'spoof', 'challenge_failed', 'timeout', 'quality', 'no_face', 'multiple_faces'].map((o) => <option key={o} value={o}>{o.replace('_', ' ')}</option>)}
        </Select>
        <span className="flex items-center gap-1.5 text-sm text-ink-3"><AlertTriangle className="size-4" /> Spoof and challenge failures may indicate presentation attacks.</span>
      </div>
      {q.isLoading ? <Skeleton className="m-4 h-64" /> : !q.data?.items.length ? <EmptyState icon={<ScanFace className="size-5" />} title="No verification attempts" /> : (
        <>
          <Table>
            <thead><tr><Th>When</Th><Th>Outcome</Th><Th>Employee</Th><Th>Match</Th><Th>2nd</Th><Th>Liveness</Th><Th>Challenge</Th><Th>Frames</Th><Th>Duration</Th><Th>IP</Th></tr></thead>
            <tbody>
              {q.data.items.map((a) => (
                <tr key={a.id}>
                  <Td className="tabular whitespace-nowrap">{fmtDateTime(a.created_at)}</Td>
                  <Td><Badge tone={tone(a.outcome)}>{a.outcome.replace('_', ' ')}</Badge></Td>
                  <Td>{a.employee_name ?? <span className="text-ink-3">—</span>}</Td>
                  <Td className="tabular">{a.match_score?.toFixed(2) ?? '—'}</Td>
                  <Td className="tabular text-ink-3">{a.second_score?.toFixed(2) ?? '—'}</Td>
                  <Td className="tabular">{a.liveness_score?.toFixed(2) ?? '—'}</Td>
                  <Td className="text-ink-2">{a.challenge?.replace('_', ' ') ?? '—'}</Td>
                  <Td className="tabular">{a.frames}</Td>
                  <Td className="tabular">{a.duration_ms != null ? `${(a.duration_ms / 1000).toFixed(1)}s` : '—'}</Td>
                  <Td className="font-mono text-xs text-ink-3">{a.ip ?? '—'}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <Pagination page={q.data.page} pageSize={q.data.page_size} total={q.data.total} onPage={setPage} />
        </>
      )}
    </Card>
  )
}
