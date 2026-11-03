import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ArrowDown, ArrowUp, Download, FileSpreadsheet } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api } from '../../lib/api'
import { daysAgoISO, fmtDate, fmtMinutes, todayISO } from '../../lib/format'
import type { Department, ReportSummary } from '../../lib/types'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Input, Select } from '../../components/ui/Field'
import { EmptyState, PageHeader, Skeleton, Stat, Table, Td, Th } from '../../components/ui/Misc'

type Preset = 'week' | '30d' | 'month' | 'custom'
type Row = ReportSummary['per_employee'][number]
type SortKey = keyof Row

function presetRange(p: Preset): [string, string] {
  const now = new Date()
  if (p === 'week') { const d = new Date(now); d.setDate(now.getDate() - ((now.getDay() + 6) % 7)); return [d.toISOString().slice(0, 10), todayISO()] }
  if (p === '30d') return [daysAgoISO(29), todayISO()]
  const d = new Date(now.getFullYear(), now.getMonth(), 1)
  return [`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`, todayISO()]
}

const tip = { contentStyle: { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, fontSize: 12 } }

export default function Reports() {
  const [preset, setPreset] = useState<Preset>('30d')
  const [range, setRange] = useState<[string, string]>(() => presetRange('30d'))
  const [dep, setDep] = useState('')
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'name', dir: 1 })
  const deps = useQuery({ queryKey: ['departments'], queryFn: () => api.get<Department[]>('/departments') })
  const rep = useQuery({ queryKey: ['report', range, dep], queryFn: () => api.get<ReportSummary>('/reports/summary', { date_from: range[0], date_to: range[1], department_id: dep }) })
  const choose = (p: Preset) => { setPreset(p); if (p !== 'custom') setRange(presetRange(p)) }
  const exportUrl = (fmt: string) => `/api/v1/attendance/export?fmt=${fmt}&date_from=${range[0]}&date_to=${range[1]}${dep ? `&department_id=${dep}` : ''}`

  const rows = useMemo(() => {
    const r = [...(rep.data?.per_employee ?? [])]
    r.sort((a, b) => { const x = a[sort.key], y = b[sort.key]; return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x ?? '').localeCompare(String(y ?? ''))) * sort.dir })
    return r
  }, [rep.data, sort])
  const exceptions = rows.filter((r) => r.missing_checkouts > 0 || r.days_late >= 3)
  const toggle = (key: SortKey) => setSort((s) => ({ key, dir: s.key === key ? (s.dir === 1 ? -1 : 1) : 1 }))
  const SortTh = ({ k, children, className }: { k: SortKey; children: string; className?: string }) => (
    <Th className={className} aria-sort={sort.key === k ? (sort.dir === 1 ? 'ascending' : 'descending') : 'none'}>
      <button onClick={() => toggle(k)} className="inline-flex items-center gap-1 uppercase hover:text-ink">{children}{sort.key === k && (sort.dir === 1 ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />)}</button>
    </Th>
  )

  const d = rep.data
  return (
    <>
      <PageHeader title="Reports & analytics" description="Attendance trends, working hours, late arrivals and exceptions for a period." actions={
        <>
          <Button variant="outline" leftIcon={<Download className="size-4" />} onClick={() => window.open(exportUrl('csv'), '_blank')}>CSV</Button>
          <Button variant="outline" leftIcon={<FileSpreadsheet className="size-4" />} onClick={() => window.open(exportUrl('xlsx'), '_blank')}>Excel</Button>
        </>
      } />

      <Card className="mb-4 flex flex-wrap items-end gap-3 p-4">
        <div className="flex rounded-lg bg-surface-3 p-1">
          {([['week', 'This week'], ['30d', 'Last 30 days'], ['month', 'This month'], ['custom', 'Custom']] as [Preset, string][]).map(([p, l]) => (
            <button key={p} onClick={() => choose(p)} className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${preset === p ? 'bg-surface text-ink shadow-card' : 'text-ink-3 hover:text-ink'}`}>{l}</button>
          ))}
        </div>
        <Input label="From" type="date" value={range[0]} onChange={(e) => { setPreset('custom'); setRange([e.target.value, range[1]]) }} />
        <Input label="To" type="date" value={range[1]} onChange={(e) => { setPreset('custom'); setRange([range[0], e.target.value]) }} />
        <Select label="Department" value={dep} onChange={(e) => setDep(e.target.value)} wrapperClassName="min-w-48">
          <option value="">All departments</option>
          {deps.data?.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </Select>
      </Card>

      {rep.isLoading ? <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-24" />)}</div>
      : rep.isError ? <Card><EmptyState title="Report unavailable" description={(rep.error as Error).message} /></Card>
      : d && (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <Stat label="Present days" value={d.totals.present_days} delta={`${d.working_days} working days · ${d.active_employees} active`} />
            <Stat label="Hours worked" value={d.totals.worked_hours} decimals={1} suffix="h" delta={d.totals.present_days ? `${(d.totals.worked_hours / d.totals.present_days).toFixed(1)}h per present day` : undefined} />
            <Stat label="Late arrivals" value={d.totals.late_days} tone={d.totals.late_days ? 'warning' : 'neutral'} delta={d.totals.present_days ? `${Math.round((d.totals.late_days / d.totals.present_days) * 100)}% of present days` : undefined} />
            <Stat label="Missing check-outs" value={d.totals.missing_checkouts} tone={d.totals.missing_checkouts ? 'danger' : 'neutral'} delta="Need correction" />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="Daily attendance" description="Present vs late per day" />
              <CardBody>
                {d.per_day.length === 0 ? <EmptyState title="No data in range" /> : (
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={d.per_day} margin={{ left: -20, right: 8 }}>
                        <CartesianGrid stroke="var(--line)" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={(v: string) => fmtDate(v, 'd MMM')} tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} allowDecimals={false} />
                        <Tooltip {...tip} labelFormatter={(v) => fmtDate(String(v), 'EEE d MMM')} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Bar dataKey="present" name="Present" fill="#1e3a5f" radius={[4, 4, 0, 0]} />
                        <Bar dataKey="late" name="Late" fill="#d97706" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                )}
                <p className="mt-2 text-xs text-ink-3">{d.per_day.length} days with activity between {fmtDate(d.from, 'd MMM')} and {fmtDate(d.to, 'd MMM')}.</p>
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Worked hours" description="Total hours per day" />
              <CardBody>
                {d.per_day.length === 0 ? <EmptyState title="No data in range" /> : (
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <LineChart data={d.per_day.map((x) => ({ ...x, hours: +(x.worked_minutes / 60).toFixed(1) }))} margin={{ left: -20, right: 8 }}>
                        <CartesianGrid stroke="var(--line)" vertical={false} />
                        <XAxis dataKey="date" tickFormatter={(v: string) => fmtDate(v, 'd MMM')} tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} />
                        <YAxis tick={{ fontSize: 11, fill: 'var(--ink-3)' }} axisLine={false} tickLine={false} />
                        <Tooltip {...tip} labelFormatter={(v) => fmtDate(String(v), 'EEE d MMM')} formatter={(v) => [`${v} h`, 'Hours']} />
                        <Line type="monotone" dataKey="hours" stroke="#059669" strokeWidth={2} dot={false} />
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                )}
                <p className="mt-2 text-xs text-ink-3">{d.totals.worked_hours} hours in total over the period.</p>
              </CardBody>
            </Card>
          </div>

          {exceptions.length > 0 && (
            <Card className="border-amber-200 dark:border-amber-800">
              <CardHeader title={<span className="flex items-center gap-2"><AlertTriangle className="size-4 text-amber-600" />Exceptions</span>} description="Employees with missing check-outs or three or more late days" />
              <CardBody className="flex flex-wrap gap-2">
                {exceptions.map((r) => (
                  <span key={r.employee_id} className="inline-flex items-center gap-2 rounded-lg border border-line bg-surface-2 px-3 py-1.5 text-sm">
                    <span className="font-medium">{r.name}</span>
                    {r.missing_checkouts > 0 && <Badge tone="danger">{r.missing_checkouts} missing out</Badge>}
                    {r.days_late >= 3 && <Badge tone="warning">{r.days_late} late</Badge>}
                  </span>
                ))}
              </CardBody>
            </Card>
          )}

          <Card>
            <CardHeader title="Per employee" description="Click a column to sort" />
            {rows.length === 0 ? <EmptyState title="No attendance in this period" /> : (
              <Table>
                <thead><tr><SortTh k="name">Employee</SortTh><SortTh k="department">Department</SortTh><SortTh k="days_present">Days</SortTh><SortTh k="worked_minutes">Hours</SortTh><SortTh k="days_late">Late days</SortTh><SortTh k="late_minutes">Late min</SortTh><SortTh k="missing_checkouts">Missing out</SortTh></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.employee_id}>
                      <Td><p className="font-medium">{r.name}</p><p className="text-xs text-ink-3">{r.code}</p></Td>
                      <Td className="text-ink-2">{r.department ?? '—'}</Td>
                      <Td className="tabular">{r.days_present}</Td>
                      <Td className="tabular">{fmtMinutes(r.worked_minutes)}</Td>
                      <Td className={`tabular ${r.days_late >= 3 ? 'font-medium text-amber-600' : ''}`}>{r.days_late}</Td>
                      <Td className={`tabular ${r.late_minutes ? 'text-amber-600' : 'text-ink-3'}`}>{r.late_minutes || '—'}</Td>
                      <Td className={`tabular ${r.missing_checkouts ? 'font-medium text-red-600' : 'text-ink-3'}`}>{r.missing_checkouts || '—'}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      )}
    </>
  )
}
