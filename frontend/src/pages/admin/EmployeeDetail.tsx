import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Fingerprint, KeyRound, ScanFace, ShieldAlert, Trash2, UserCog } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { fmtDate, fmtDateTime, fmtMinutes, fmtTime } from '../../lib/format'
import type { AttendanceDay, Department, Employee, EnrolmentRecord, Page } from '../../lib/types'
import { Badge, StatusBadge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog'
import { Input, Select } from '../../components/ui/Field'
import { Avatar, EmptyState, PageHeader, Skeleton, Table, Td, Th } from '../../components/ui/Misc'
import { useToast } from '../../components/ui/Toast'

export default function EmployeeDetail() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const qc = useQueryClient()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'

  const emp = useQuery({ queryKey: ['employee', id], queryFn: () => api.get<Employee>(`/employees/${id}`) })
  const deps = useQuery({ queryKey: ['departments'], queryFn: () => api.get<Department[]>('/departments') })
  const history = useQuery({ queryKey: ['enrolments', id], queryFn: () => api.get<EnrolmentRecord[]>(`/employees/${id}/enrolments`) })
  const days = useQuery({ queryKey: ['days', { employee_id: id }], queryFn: () => api.get<Page<AttendanceDay>>('/attendance/days', { employee_id: id, page_size: 14 }) })

  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['employee', id] }); void qc.invalidateQueries({ queryKey: ['employees'] }); void qc.invalidateQueries({ queryKey: ['enrolments', id] }) }
  const onErr = (title: string) => (e: ApiError) => toast.error(title, e.message)

  const [edit, setEdit] = useState<Partial<Employee> | null>(null)
  const [statusConfirm, setStatusConfirm] = useState(false)
  const [bioConfirm, setBioConfirm] = useState<'revoke' | 'purge' | null>(null)
  const [pinOpen, setPinOpen] = useState(false)
  const [pin, setPin] = useState('')
  const [accountOpen, setAccountOpen] = useState(false)
  const [password, setPassword] = useState('')
  const [role, setRole] = useState('employee')

  const update = useMutation({ mutationFn: (body: Record<string, unknown>) => api.patch<Employee>(`/employees/${id}`, body), onSuccess: () => { toast.success('Profile updated'); setEdit(null); setStatusConfirm(false); invalidate() }, onError: onErr('Could not update') })
  const bio = useMutation({ mutationFn: (purge: boolean) => api.del<{ removed: number }>(`/employees/${id}/biometrics`, { purge }), onSuccess: (r, purge) => { toast.success(purge ? 'Biometric data permanently deleted' : 'Enrolment revoked', `${r.removed} template${r.removed === 1 ? '' : 's'} removed`); setBioConfirm(null); invalidate() }, onError: onErr('Could not remove biometrics') })
  const setPin_ = useMutation({ mutationFn: () => api.post(`/employees/${id}/pin`, { pin }), onSuccess: () => { toast.success('PIN fallback enabled'); setPinOpen(false); setPin(''); invalidate() }, onError: onErr('Could not set PIN') })
  const clearPin = useMutation({ mutationFn: () => api.del(`/employees/${id}/pin`), onSuccess: () => { toast.success('PIN fallback disabled'); invalidate() }, onError: onErr('Could not disable PIN') })
  const createAccount = useMutation({ mutationFn: () => api.post(`/employees/${id}/account`, { password, role }), onSuccess: () => { toast.success('Login account created'); setAccountOpen(false); setPassword(''); invalidate() }, onError: onErr('Could not create account') })

  if (emp.isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-64" /><Skeleton className="h-48" /><Skeleton className="h-64" /></div>
  if (emp.isError || !emp.data) return <Card><EmptyState title="Employee not found" action={<Link to="/admin/employees"><Button variant="outline">Back to directory</Button></Link>} /></Card>
  const e = emp.data
  const name = `${e.first_name} ${e.last_name}`

  return (
    <>
      <Link to="/admin/employees" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-3 hover:text-ink"><ArrowLeft className="size-4" /> Employees</Link>
      <PageHeader title={<span className="flex items-center gap-3"><Avatar name={name} src={e.enrolled ? `/api/v1/employees/${e.id}/thumbnail` : null} size="lg" />{name}</span>} description={`${e.employee_code} · ${e.email}`} actions={
        <>
          <Badge tone={e.status === 'active' ? 'success' : 'neutral'} dot>{e.status === 'active' ? 'Active' : 'Inactive'}</Badge>
          <Button variant="outline" leftIcon={<UserCog className="size-4" />} onClick={() => setEdit({ first_name: e.first_name, last_name: e.last_name, email: e.email, job_title: e.job_title ?? '', department_id: e.department_id ?? '' })}>Edit profile</Button>
          <Button variant={e.status === 'active' ? 'danger' : 'accent'} onClick={() => setStatusConfirm(true)}>{e.status === 'active' ? 'Deactivate' : 'Activate'}</Button>
        </>
      } />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader title="Profile" />
          <CardBody>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <dt className="text-ink-3">Department</dt><dd>{e.department_name ?? '—'}</dd>
              <dt className="text-ink-3">Job title</dt><dd>{e.job_title ?? '—'}</dd>
              <dt className="text-ink-3">Employee code</dt><dd className="font-mono text-[13px]">{e.employee_code}</dd>
              <dt className="text-ink-3">Email</dt><dd className="break-all">{e.email}</dd>
              <dt className="text-ink-3">Created</dt><dd>{fmtDate(e.created_at, 'd MMM yyyy')}</dd>
              <dt className="text-ink-3">Login</dt><dd>{e.has_account ? <Badge tone="neutral">Account exists</Badge> : isAdmin ? <Button size="sm" variant="outline" onClick={() => setAccountOpen(true)}>Create account</Button> : 'None'}</dd>
              <dt className="text-ink-3">PIN fallback</dt>
              <dd className="flex flex-wrap items-center gap-2">
                {e.pin_fallback_enabled ? <Badge tone="info" dot>Enabled</Badge> : <span className="text-ink-3">Off</span>}
                {isAdmin && (e.pin_fallback_enabled
                  ? <Button size="sm" variant="ghost" onClick={() => clearPin.mutate()} loading={clearPin.isPending}>Disable</Button>
                  : <Button size="sm" variant="ghost" leftIcon={<KeyRound className="size-3.5" />} onClick={() => setPinOpen(true)}>Set PIN</Button>)}
              </dd>
            </dl>
          </CardBody>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="Biometric enrolment" description="Face templates are encrypted at rest and never leave this server." action={
            e.status === 'active' && <Button leftIcon={<ScanFace className="size-4" />} onClick={() => navigate(`/admin/employees/${e.id}/enrol`)}>{e.enrolled ? 'Re-enrol face' : 'Enrol face'}</Button>
          } />
          <CardBody>
            <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
              <div className="grid size-28 shrink-0 place-items-center overflow-hidden rounded-xl bg-surface-3">
                {e.enrolled ? <img src={`/api/v1/employees/${e.id}/thumbnail`} alt={`Enrolled face of ${name}`} className="size-full object-cover" onError={(ev) => { (ev.currentTarget as HTMLImageElement).style.display = 'none' }} /> : <Fingerprint className="size-8 text-ink-3" aria-hidden />}
              </div>
              <div className="min-w-0 flex-1 text-sm">
                {e.enrolled ? (
                  <>
                    <p className="flex items-center gap-2 font-medium"><Badge tone="brand" dot>Enrolled</Badge> <span className="text-ink-3">since {fmtDateTime(e.enrolment_at)}</span></p>
                    {history.data?.[0] && <p className="mt-2 text-ink-2">{history.data[0].template_count} pose templates · quality {history.data[0].quality_score?.toFixed(2)} · liveness {history.data[0].liveness_score?.toFixed(2)} · model {history.data[0].model_version}</p>}
                    {isAdmin && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        <Button size="sm" variant="outline" onClick={() => setBioConfirm('revoke')}>Revoke enrolment</Button>
                        <Button size="sm" variant="danger" leftIcon={<Trash2 className="size-3.5" />} onClick={() => setBioConfirm('purge')}>Delete all biometric data</Button>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="text-ink-3">No active enrolment. The employee cannot use face attendance until an administrator enrols them with their consent.</p>
                )}
              </div>
            </div>

            <h4 className="mt-6 mb-2 text-xs font-semibold uppercase tracking-wider text-ink-3">Enrolment history</h4>
            {history.isLoading ? <Skeleton className="h-16" /> : !history.data?.length ? <p className="text-sm text-ink-3">No enrolment records.</p> : (
              <ul className="divide-y divide-line rounded-lg border border-line text-sm">
                {history.data.map((h) => (
                  <li key={h.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                    <Badge tone={h.status === 'active' ? 'success' : h.status === 'revoked' ? 'danger' : 'neutral'}>{h.status}</Badge>
                    <span>{fmtDateTime(h.created_at)}</span>
                    <span className="text-ink-3">{h.template_count} templates · consent {h.consent_version}</span>
                    {h.revoked_at && <span className="text-ink-3">· ended {fmtDateTime(h.revoked_at)}</span>}
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Recent attendance" description="Last 14 recorded days" action={<Link to={`/admin/attendance?employee_id=${e.id}`} className="text-sm text-brand-600 hover:underline">View all</Link>} />
        {days.isLoading ? <Skeleton className="mx-5 mb-5 h-32" /> : !days.data?.items.length ? <EmptyState title="No attendance recorded yet" /> : (
          <Table>
            <thead><tr><Th>Date</Th><Th>First in</Th><Th>Last out</Th><Th>Worked</Th><Th>Late</Th><Th>Status</Th></tr></thead>
            <tbody>
              {days.data.items.map((d) => (
                <tr key={d.id}>
                  <Td className="font-medium">{fmtDate(d.attendance_date)}</Td>
                  <Td className="tabular">{fmtTime(d.first_in)}</Td>
                  <Td className="tabular">{fmtTime(d.last_out)}</Td>
                  <Td className="tabular">{fmtMinutes(d.worked_minutes)}</Td>
                  <Td className={d.late_minutes ? 'text-amber-600' : 'text-ink-3'}>{d.late_minutes ? `${d.late_minutes}m` : '—'}</Td>
                  <Td><StatusBadge status={d.status} /></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Dialog open={!!edit} onClose={() => setEdit(null)} title="Edit profile" footer={<><Button variant="ghost" onClick={() => setEdit(null)}>Cancel</Button><Button onClick={() => edit && update.mutate({ ...edit, department_id: edit.department_id || null, job_title: edit.job_title || null })} loading={update.isPending}>Save changes</Button></>}>
        {edit && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="First name" value={edit.first_name ?? ''} onChange={(ev) => setEdit({ ...edit, first_name: ev.target.value })} />
            <Input label="Last name" value={edit.last_name ?? ''} onChange={(ev) => setEdit({ ...edit, last_name: ev.target.value })} />
            <Input label="Email" type="email" value={edit.email ?? ''} onChange={(ev) => setEdit({ ...edit, email: ev.target.value })} wrapperClassName="sm:col-span-2" />
            <Input label="Job title" value={edit.job_title ?? ''} onChange={(ev) => setEdit({ ...edit, job_title: ev.target.value })} />
            <Select label="Department" value={edit.department_id ?? ''} onChange={(ev) => setEdit({ ...edit, department_id: ev.target.value })}>
              <option value="">No department</option>
              {deps.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </Select>
          </div>
        )}
      </Dialog>

      <ConfirmDialog open={statusConfirm} onClose={() => setStatusConfirm(false)} onConfirm={() => update.mutate({ status: e.status === 'active' ? 'inactive' : 'active' })} loading={update.isPending}
        title={e.status === 'active' ? `Deactivate ${name}?` : `Activate ${name}?`} danger={e.status === 'active'} confirmLabel={e.status === 'active' ? 'Deactivate' : 'Activate'}
        description={e.status === 'active' ? 'They will be removed from the recognition index immediately and cannot record attendance. Their data is kept.' : 'They will be able to record attendance again (if enrolled).'} />

      <ConfirmDialog open={!!bioConfirm} onClose={() => setBioConfirm(null)} onConfirm={() => bio.mutate(bioConfirm === 'purge')} loading={bio.isPending} danger confirmLabel={bioConfirm === 'purge' ? 'Delete permanently' : 'Revoke'}
        title={bioConfirm === 'purge' ? 'Delete all biometric data?' : 'Revoke the active enrolment?'}
        description={bioConfirm === 'purge' ? 'All face templates and thumbnails for this employee are erased irreversibly. Use this for data-subject erasure requests.' : 'The enrolment is marked revoked and removed from the index; the audit history is kept. You can re-enrol later.'} />

      <Dialog open={pinOpen} onClose={() => setPinOpen(false)} title="Set PIN fallback" description="A non-biometric alternative for this employee only. Every PIN check-in is logged as method = pin." size="sm"
        footer={<><Button variant="ghost" onClick={() => setPinOpen(false)}>Cancel</Button><Button onClick={() => setPin_.mutate()} loading={setPin_.isPending} disabled={!/^\d{4,8}$/.test(pin)}>Enable PIN</Button></>}>
        <Input label="PIN (4–8 digits)" inputMode="numeric" pattern="\d*" value={pin} onChange={(ev) => setPin(ev.target.value.replace(/\D/g, '').slice(0, 8))} autoComplete="off" />
      </Dialog>

      <Dialog open={accountOpen} onClose={() => setAccountOpen(false)} title="Create login account" description={`Uses ${e.email}. Share the password securely and ask them to change it.`} size="sm"
        footer={<><Button variant="ghost" onClick={() => setAccountOpen(false)}>Cancel</Button><Button onClick={() => createAccount.mutate()} loading={createAccount.isPending} disabled={password.length < 10}>Create account</Button></>}>
        <div className="space-y-4">
          <Input label="Temporary password" type="password" hint="At least 10 characters" value={password} onChange={(ev) => setPassword(ev.target.value)} autoComplete="new-password" />
          <Select label="Role" value={role} onChange={(ev) => setRole(ev.target.value)}>
            <option value="employee">Employee (self-service portal)</option>
            <option value="hr">HR (manage employees & attendance)</option>
            <option value="admin">Administrator (full access)</option>
          </Select>
          {role !== 'employee' && <p className="flex items-start gap-2 rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-200"><ShieldAlert className="mt-0.5 size-3.5 shrink-0" />Staff roles should enable MFA on first sign-in.</p>}
        </div>
      </Dialog>
    </>
  )
}
