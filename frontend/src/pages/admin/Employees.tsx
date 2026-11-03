import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { Building2, Plus, Search, Trash2, UserPlus, Users } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import type { Department, Employee, Page } from '../../lib/types'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card } from '../../components/ui/Card'
import { ConfirmDialog, Dialog } from '../../components/ui/Dialog'
import { Input, Select } from '../../components/ui/Field'
import { Avatar, EmptyState, PageHeader, Pagination, Skeleton, Table, Td, Th } from '../../components/ui/Misc'
import { useToast } from '../../components/ui/Toast'

const employeeSchema = z.object({
  employee_code: z.string().min(1, 'Required').max(32),
  first_name: z.string().min(1, 'Required').max(80),
  last_name: z.string().min(1, 'Required').max(80),
  email: z.string().regex(/^[^@\s]+@[^@\s]+\.[^@\s]+$/, 'Enter a valid email'),
  job_title: z.string().max(120).optional(),
  department_id: z.string().optional(),
})
type EmployeeForm = z.infer<typeof employeeSchema>

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value)
  useEffect(() => { const t = setTimeout(() => setV(value), ms); return () => clearTimeout(t) }, [value, ms])
  return v
}

export default function Employees() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const toast = useToast()
  const qc = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [q, setQ] = useState(params.get('q') ?? '')
  const dq = useDebounced(q)
  const department = params.get('department_id') ?? ''
  const status = params.get('status') ?? ''
  const enrolled = params.get('enrolled') ?? ''
  const page = Number(params.get('page') ?? '1')
  const setParam = (k: string, v: string) => setParams((p) => { if (v) p.set(k, v); else p.delete(k); if (k !== 'page') p.delete('page'); return p })

  const deps = useQuery({ queryKey: ['departments'], queryFn: () => api.get<Department[]>('/departments') })
  const list = useQuery({
    queryKey: ['employees', { q: dq, department, status, enrolled, page }],
    queryFn: () => api.get<Page<Employee>>('/employees', { q: dq, department_id: department, status, enrolled: enrolled === '' ? undefined : enrolled === 'true', page, page_size: 25 }),
    placeholderData: (prev) => prev,
  })

  const [addOpen, setAddOpen] = useState(false)
  const [depsOpen, setDepsOpen] = useState(false)

  const form = useForm<EmployeeForm>({ resolver: zodResolver(employeeSchema) })
  const create = useMutation({
    mutationFn: (body: EmployeeForm) => api.post<Employee>('/employees', { ...body, department_id: body.department_id || null, job_title: body.job_title || null }),
    onSuccess: (e) => { toast.success('Employee created', `${e.first_name} ${e.last_name} · ${e.employee_code}`); setAddOpen(false); form.reset(); void qc.invalidateQueries({ queryKey: ['employees'] }); void qc.invalidateQueries({ queryKey: ['departments'] }) },
    onError: (e: ApiError) => toast.error('Could not create employee', e.message),
  })

  return (
    <>
      <PageHeader title="Employees" description={list.data ? `${list.data.total} people in the directory` : 'Directory of all employees, their accounts and enrolment status.'} actions={
        <>
          {isAdmin && <Button variant="outline" leftIcon={<Building2 className="size-4" />} onClick={() => setDepsOpen(true)}>Departments</Button>}
          <Button leftIcon={<UserPlus className="size-4" />} onClick={() => setAddOpen(true)}>Add employee</Button>
        </>
      } />

      <Card>
        <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-[1fr_auto_auto_auto]">
          <Input aria-label="Search employees" placeholder="Search by name, email or code" leftIcon={<Search className="size-4" />} value={q} onChange={(e) => { setQ(e.target.value); setParam('q', e.target.value) }} />
          <Select aria-label="Department" value={department} onChange={(e) => setParam('department_id', e.target.value)}>
            <option value="">All departments</option>
            {deps.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
          <Select aria-label="Status" value={status} onChange={(e) => setParam('status', e.target.value)}>
            <option value="">Any status</option><option value="active">Active</option><option value="inactive">Inactive</option>
          </Select>
          <Select aria-label="Enrolment" value={enrolled} onChange={(e) => setParam('enrolled', e.target.value)}>
            <option value="">Any enrolment</option><option value="true">Enrolled</option><option value="false">Not enrolled</option>
          </Select>
        </div>

        {list.isLoading ? <div className="space-y-2 p-4">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
        : list.isError ? <EmptyState title="Could not load employees" description={(list.error as Error).message} />
        : !list.data?.items.length ? <EmptyState icon={<Users className="size-5" />} title="No employees match" description="Try a different search or add a new employee." action={<Button size="sm" onClick={() => setAddOpen(true)} leftIcon={<Plus className="size-4" />}>Add employee</Button>} />
        : (
          <>
            <Table>
              <thead><tr><Th>Employee</Th><Th>Department</Th><Th>Role</Th><Th>Status</Th><Th>Biometrics</Th><Th>Login</Th></tr></thead>
              <tbody>
                {list.data.items.map((e) => (
                  <tr key={e.id} onClick={() => navigate(`/admin/employees/${e.id}`)} className="cursor-pointer transition-colors hover:bg-surface-3" tabIndex={0} onKeyDown={(ev) => ev.key === 'Enter' && navigate(`/admin/employees/${e.id}`)}>
                    <Td>
                      <div className="flex items-center gap-3">
                        <Avatar name={`${e.first_name} ${e.last_name}`} size="sm" />
                        <div className="min-w-0"><p className="truncate font-medium">{e.first_name} {e.last_name}</p><p className="truncate text-xs text-ink-3">{e.employee_code} · {e.email}</p></div>
                      </div>
                    </Td>
                    <Td className="text-ink-2">{e.department_name ?? <span className="text-ink-3">—</span>}</Td>
                    <Td className="text-ink-2">{e.job_title ?? <span className="text-ink-3">—</span>}</Td>
                    <Td><Badge tone={e.status === 'active' ? 'success' : 'neutral'} dot>{e.status === 'active' ? 'Active' : 'Inactive'}</Badge></Td>
                    <Td>{e.enrolled ? <Badge tone="brand" dot>Enrolled</Badge> : <Badge tone="warning" dot>Not enrolled</Badge>}</Td>
                    <Td>{e.has_account ? <Badge tone="neutral">Account</Badge> : <span className="text-xs text-ink-3">None</span>}{e.pin_fallback_enabled && <Badge tone="info" className="ml-1">PIN</Badge>}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Pagination page={list.data.page} pageSize={list.data.page_size} total={list.data.total} onPage={(p) => setParam('page', String(p))} />
          </>
        )}
      </Card>

      <Dialog open={addOpen} onClose={() => setAddOpen(false)} title="Add employee" description="Create the profile first; face enrolment is a separate, consented step." footer={
        <><Button variant="ghost" onClick={() => setAddOpen(false)}>Cancel</Button><Button form="add-employee" type="submit" loading={create.isPending}>Create employee</Button></>
      }>
        <form id="add-employee" className="grid gap-4 sm:grid-cols-2" onSubmit={form.handleSubmit((v) => create.mutate(v))} noValidate>
          <Input label="First name" required error={form.formState.errors.first_name?.message} {...form.register('first_name')} autoComplete="given-name" />
          <Input label="Last name" required error={form.formState.errors.last_name?.message} {...form.register('last_name')} autoComplete="family-name" />
          <Input label="Work email" type="email" required error={form.formState.errors.email?.message} {...form.register('email')} wrapperClassName="sm:col-span-2" autoComplete="off" />
          <Input label="Employee code" required hint="Unique ID, e.g. E1042" error={form.formState.errors.employee_code?.message} {...form.register('employee_code')} />
          <Input label="Job title" error={form.formState.errors.job_title?.message} {...form.register('job_title')} />
          <Select label="Department" {...form.register('department_id')} wrapperClassName="sm:col-span-2">
            <option value="">No department</option>
            {deps.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </Select>
        </form>
      </Dialog>

      <DepartmentsDialog open={depsOpen} onClose={() => setDepsOpen(false)} departments={deps.data ?? []} />
    </>
  )
}

function DepartmentsDialog({ open, onClose, departments }: { open: boolean; onClose: () => void; departments: Department[] }) {
  const toast = useToast()
  const qc = useQueryClient()
  const [name, setName] = useState('')
  const [code, setCode] = useState('')
  const [editing, setEditing] = useState<Department | null>(null)
  const [del, setDel] = useState<Department | null>(null)
  const invalidate = () => { void qc.invalidateQueries({ queryKey: ['departments'] }); void qc.invalidateQueries({ queryKey: ['employees'] }) }
  const create = useMutation({ mutationFn: () => api.post<Department>('/departments', { name, code }), onSuccess: () => { toast.success('Department created'); setName(''); setCode(''); invalidate() }, onError: (e: ApiError) => toast.error('Could not create department', e.message) })
  const rename = useMutation({ mutationFn: (d: Department) => api.patch<Department>(`/departments/${d.id}`, { name: d.name, code: d.code }), onSuccess: () => { toast.success('Department updated'); setEditing(null); invalidate() }, onError: (e: ApiError) => toast.error('Could not update department', e.message) })
  const remove = useMutation({ mutationFn: (id: string) => api.del(`/departments/${id}`), onSuccess: () => { toast.success('Department deleted'); setDel(null); invalidate() }, onError: (e: ApiError) => toast.error('Could not delete department', e.message) })

  return (
    <Dialog open={open} onClose={onClose} title="Departments" description="Employees keep their profile if a department is deleted.">
      <ul className="divide-y divide-line rounded-lg border border-line">
        {departments.length === 0 && <li className="p-4 text-sm text-ink-3">No departments yet.</li>}
        {departments.map((d) => (
          <li key={d.id} className="flex items-center gap-2 p-2.5">
            {editing?.id === d.id ? (
              <>
                <Input aria-label="Name" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} wrapperClassName="flex-1" />
                <Input aria-label="Code" value={editing.code} onChange={(e) => setEditing({ ...editing, code: e.target.value })} wrapperClassName="w-24" />
                <Button size="sm" onClick={() => rename.mutate(editing)} loading={rename.isPending}>Save</Button>
                <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
              </>
            ) : (
              <>
                <div className="min-w-0 flex-1"><p className="text-sm font-medium">{d.name}</p><p className="text-xs text-ink-3">{d.code} · {d.employee_count} employees</p></div>
                <Button size="sm" variant="ghost" onClick={() => setEditing(d)}>Rename</Button>
                <Button size="sm" variant="ghost" aria-label={`Delete ${d.name}`} onClick={() => setDel(d)}><Trash2 className="size-4 text-red-600" /></Button>
              </>
            )}
          </li>
        ))}
      </ul>
      <form className="mt-4 flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name && code) create.mutate() }}>
        <Input label="New department" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)} wrapperClassName="flex-1" />
        <Input label="Code" placeholder="ENG" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} wrapperClassName="w-28" maxLength={20} />
        <Button type="submit" loading={create.isPending} leftIcon={<Plus className="size-4" />}>Add</Button>
      </form>
      <ConfirmDialog open={!!del} onClose={() => setDel(null)} onConfirm={() => del && remove.mutate(del.id)} title={`Delete ${del?.name}?`} description="Employees in this department will be left without a department." confirmLabel="Delete" danger loading={remove.isPending} />
    </Dialog>
  )
}
