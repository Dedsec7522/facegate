import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, ShieldCheck, ShieldOff } from 'lucide-react'
import { api, ApiError } from '../../lib/api'
import { useAuth } from '../../lib/auth'
import { fmtDateTime } from '../../lib/format'
import type { AuditEntry, OrgSettings } from '../../lib/types'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Input, Switch } from '../../components/ui/Field'
import { EmptyState, PageHeader, Pagination, Skeleton, Table, Tabs, Td, Th } from '../../components/ui/Misc'
import { useToast } from '../../components/ui/Toast'

type Tab = 'rules' | 'verification' | 'security' | 'users' | 'audit'

interface UserRow { id: string; email: string; role: string; is_active: boolean; mfa_enabled: boolean; employee_id: string | null; last_login_at: string | null; locked_until: string | null }

export default function SettingsPage() {
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [tab, setTab] = useState<Tab>('rules')
  const items: Array<{ value: Tab; label: string }> = [{ value: 'rules', label: 'Attendance rules' }, { value: 'verification', label: 'Verification' }, { value: 'security', label: 'My security' }]
  if (isAdmin) items.push({ value: 'users', label: 'Users' }, { value: 'audit', label: 'Audit log' })
  return (
    <>
      <PageHeader title="Settings & security" description={isAdmin ? 'Organisation rules, verification thresholds, accounts and the audit trail.' : 'Read-only view of organisation rules; manage your own security below.'} />
      <Tabs className="mb-4" value={tab} onChange={setTab} items={items} />
      {(tab === 'rules' || tab === 'verification') && <OrgSettingsForm section={tab} readOnly={!isAdmin} />}
      {tab === 'security' && <SecurityTab />}
      {tab === 'users' && isAdmin && <UsersTab />}
      {tab === 'audit' && isAdmin && <AuditTab />}
    </>
  )
}

function OrgSettingsForm({ section, readOnly }: { section: 'rules' | 'verification'; readOnly: boolean }) {
  const toast = useToast()
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['settings'], queryFn: () => api.get<OrgSettings>('/settings') })
  const [form, setForm] = useState<OrgSettings | null>(null)
  useEffect(() => { if (q.data) setForm(q.data) }, [q.data])
  const save = useMutation({ mutationFn: (body: Partial<OrgSettings>) => api.patch<OrgSettings>('/settings', body), onSuccess: (s) => { toast.success('Settings saved'); qc.setQueryData(['settings'], s) }, onError: (e: ApiError) => toast.error('Could not save settings', e.message) })
  if (q.isLoading || !form) return <Skeleton className="h-80" />
  const set = <K extends keyof OrgSettings>(k: K, v: OrgSettings[K]) => setForm({ ...form, [k]: v })
  const dirty = JSON.stringify(form) !== JSON.stringify(q.data)
  const footer = !readOnly && (
    <div className="flex justify-end gap-2 border-t border-line px-5 py-4">
      <Button variant="ghost" onClick={() => setForm(q.data!)} disabled={!dirty}>Reset</Button>
      <Button onClick={() => save.mutate(form)} loading={save.isPending} disabled={!dirty}>Save changes</Button>
    </div>
  )
  if (section === 'rules') return (
    <Card>
      <CardHeader title="Attendance rules" description="Apply to every employee. Times are in the organisation timezone." />
      <CardBody className="grid gap-4 sm:grid-cols-2">
        <Input label="Organisation timezone" hint="IANA name, e.g. Europe/London" value={form.timezone} onChange={(e) => set('timezone', e.target.value)} disabled={readOnly} wrapperClassName="sm:col-span-2" />
        <Input label="Attendance day starts at" type="time" hint="Events before this belong to the previous day (overnight shifts)." value={form.day_start} onChange={(e) => set('day_start', e.target.value)} disabled={readOnly} />
        <Input label="Late grace (minutes)" type="number" min={0} max={180} value={form.late_grace_minutes} onChange={(e) => set('late_grace_minutes', Number(e.target.value))} disabled={readOnly} />
        <Input label="Work start" type="time" value={form.work_start} onChange={(e) => set('work_start', e.target.value)} disabled={readOnly} />
        <Input label="Work end" type="time" value={form.work_end} onChange={(e) => set('work_end', e.target.value)} disabled={readOnly} />
        <Input label="Duplicate scan window (seconds)" type="number" min={0} max={3600} hint="Repeated events inside this window are rejected." value={form.duplicate_scan_seconds} onChange={(e) => set('duplicate_scan_seconds', Number(e.target.value))} disabled={readOnly} />
        <Input label="Flag missing check-out after (hours)" type="number" min={1} max={48} value={form.auto_close_after_hours} onChange={(e) => set('auto_close_after_hours', Number(e.target.value))} disabled={readOnly} />
      </CardBody>
      {footer}
    </Card>
  )
  return (
    <Card>
      <CardHeader title="Verification thresholds" description="Conservative defaults; tune only with measured data from the Failed verifications view." />
      <CardBody className="space-y-6">
        <div>
          <label className="flex items-center justify-between text-sm font-medium" htmlFor="thr-match">Face match acceptance <span className="tabular text-ink-2">{form.match_accept_threshold.toFixed(2)}</span></label>
          <input id="thr-match" type="range" min={0.2} max={0.9} step={0.01} value={form.match_accept_threshold} onChange={(e) => set('match_accept_threshold', Number(e.target.value))} disabled={readOnly} className="mt-2 w-full accent-brand-700" />
          <p className="mt-1 text-[13px] text-ink-3">Minimum cosine similarity to accept an identity. Higher = fewer false accepts, more "not recognised" results. A second candidate within the margin always yields "ambiguous" instead of a guess.</p>
        </div>
        <div>
          <label className="flex items-center justify-between text-sm font-medium" htmlFor="thr-pad">Liveness threshold <span className="tabular text-ink-2">{form.pad_live_threshold.toFixed(2)}</span></label>
          <input id="thr-pad" type="range" min={0.3} max={0.99} step={0.01} value={form.pad_live_threshold} onChange={(e) => set('pad_live_threshold', Number(e.target.value))} disabled={readOnly} className="mt-2 w-full accent-brand-700" />
          <p className="mt-1 text-[13px] text-ink-3">Average presentation-attack-detection score (over several frames) required before matching. Lower values make printed photos and screens more likely to pass.</p>
        </div>
        <Switch checked={form.require_challenge} onChange={(v) => set('require_challenge', v)} disabled={readOnly} label="Require head-turn challenge" description="Server-chosen active liveness check in addition to passive detection. Recommended." />
        <Input label="Consent notice version" hint="Recorded with every enrolment; bump it when the privacy notice changes." value={form.consent_version} onChange={(e) => set('consent_version', e.target.value)} disabled={readOnly} />
      </CardBody>
      {footer}
    </Card>
  )
}

function SecurityTab() {
  const { user, refresh } = useAuth()
  const toast = useToast()
  const [cur, setCur] = useState('')
  const [next, setNext] = useState('')
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string; qr_svg: string } | null>(null)
  const [code, setCode] = useState('')
  const pw = useMutation({ mutationFn: () => api.post('/auth/password', { current_password: cur, new_password: next }), onSuccess: () => { toast.success('Password changed'); setCur(''); setNext('') }, onError: (e: ApiError) => toast.error('Could not change password', e.message) })
  const start = useMutation({ mutationFn: () => api.post<{ secret: string; otpauth_uri: string; qr_svg: string }>('/auth/mfa/setup'), onSuccess: setSetup, onError: (e: ApiError) => toast.error('Could not start MFA setup', e.message) })
  const confirm = useMutation({ mutationFn: () => api.post('/auth/mfa/confirm', { code }), onSuccess: async () => { toast.success('MFA enabled', 'You will be asked for a code at every sign-in.'); setSetup(null); setCode(''); await refresh() }, onError: (e: ApiError) => toast.error('Code not accepted', e.message) })
  const disable = useMutation({ mutationFn: () => api.post('/auth/mfa/disable', { code }), onSuccess: async () => { toast.success('MFA disabled'); setCode(''); await refresh() }, onError: (e: ApiError) => toast.error('Code not accepted', e.message) })
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Change password" description={user?.email} />
        <CardBody>
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); pw.mutate() }}>
            <Input label="Current password" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required />
            <Input label="New password" type="password" autoComplete="new-password" hint="At least 10 characters" value={next} onChange={(e) => setNext(e.target.value)} required minLength={10} />
            <Button type="submit" leftIcon={<KeyRound className="size-4" />} loading={pw.isPending} disabled={next.length < 10 || !cur}>Update password</Button>
          </form>
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Multi-factor authentication" description="Time-based one-time codes from an authenticator app." action={user?.mfa_enabled ? <Badge tone="success" dot>Enabled</Badge> : <Badge tone="warning" dot>Off</Badge>} />
        <CardBody className="space-y-4">
          {user?.mfa_enabled ? (
            <>
              <p className="flex items-center gap-2 text-sm text-ink-2"><ShieldCheck className="size-4 text-accent-600" /> Your account requires a code at sign-in.</p>
              <div className="flex items-end gap-2">
                <Input label="Current code to disable" inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} wrapperClassName="w-40" />
                <Button variant="danger" leftIcon={<ShieldOff className="size-4" />} onClick={() => disable.mutate()} loading={disable.isPending} disabled={code.length < 6}>Disable MFA</Button>
              </div>
            </>
          ) : setup ? (
            <>
              <p className="text-sm text-ink-2">1. Scan this code with Google Authenticator, Microsoft Authenticator, 1Password or similar.</p>
              <div className="w-48 rounded-lg border border-line bg-white p-2 [&_svg]:size-full" dangerouslySetInnerHTML={{ __html: setup.qr_svg }} />
              <p className="text-xs text-ink-3">Or enter the key manually: <code className="rounded bg-surface-3 px-1 font-mono">{setup.secret}</code></p>
              <p className="text-sm text-ink-2">2. Enter the 6-digit code shown in the app.</p>
              <div className="flex items-end gap-2">
                <Input label="Code" inputMode="numeric" autoComplete="one-time-code" value={code} onChange={(e) => setCode(e.target.value)} wrapperClassName="w-40" />
                <Button onClick={() => confirm.mutate()} loading={confirm.isPending} disabled={code.length < 6}>Verify & enable</Button>
                <Button variant="ghost" onClick={() => setSetup(null)}>Cancel</Button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-ink-2">Strongly recommended for every administrator and HR account.</p>
              <Button leftIcon={<ShieldCheck className="size-4" />} onClick={() => start.mutate()} loading={start.isPending}>Set up MFA</Button>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

function UsersTab() {
  const q = useQuery({ queryKey: ['users'], queryFn: () => api.get<UserRow[]>('/users') })
  return (
    <Card>
      <CardHeader title="Login accounts" description="Accounts are created from an employee's profile page." />
      {q.isLoading ? <Skeleton className="m-5 h-48" /> : !q.data?.length ? <EmptyState title="No accounts" /> : (
        <Table>
          <thead><tr><Th>Email</Th><Th>Role</Th><Th>Status</Th><Th>MFA</Th><Th>Last login</Th></tr></thead>
          <tbody>
            {q.data.map((u) => (
              <tr key={u.id}>
                <Td className="font-medium">{u.email}</Td>
                <Td><Badge tone={u.role === 'admin' ? 'brand' : u.role === 'hr' ? 'info' : 'neutral'}>{u.role}</Badge></Td>
                <Td>{u.locked_until && new Date(u.locked_until) > new Date() ? <Badge tone="danger">Locked</Badge> : u.is_active ? <Badge tone="success" dot>Active</Badge> : <Badge tone="neutral">Disabled</Badge>}</Td>
                <Td>{u.mfa_enabled ? <Badge tone="success">On</Badge> : <Badge tone="warning">Off</Badge>}</Td>
                <Td className="text-ink-2">{fmtDateTime(u.last_login_at)}</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
    </Card>
  )
}

function AuditTab() {
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [page, setPage] = useState(1)
  const q = useQuery({ queryKey: ['audit', { action, actor, page }], queryFn: () => api.get<{ items: AuditEntry[]; total: number; page: number; page_size: number }>('/audit', { action, actor, page, page_size: 50 }), placeholderData: (p) => p })
  return (
    <Card>
      <div className="grid gap-3 border-b border-line p-4 sm:grid-cols-2">
        <Input aria-label="Action prefix" placeholder="Action prefix, e.g. employee. or auth." value={action} onChange={(e) => { setAction(e.target.value); setPage(1) }} />
        <Input aria-label="Actor" placeholder="Actor email contains…" value={actor} onChange={(e) => { setActor(e.target.value); setPage(1) }} />
      </div>
      {q.isLoading ? <Skeleton className="m-4 h-64" /> : !q.data?.items.length ? <EmptyState title="No audit entries match" /> : (
        <>
          <Table>
            <thead><tr><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th>Target</Th><Th>IP</Th><Th>Detail</Th></tr></thead>
            <tbody>
              {q.data.items.map((a) => (
                <tr key={a.id}>
                  <Td className="tabular whitespace-nowrap">{fmtDateTime(a.created_at)}</Td>
                  <Td className="text-ink-2">{a.actor_email ?? <span className="text-ink-3">system</span>}</Td>
                  <Td><code className="rounded bg-surface-3 px-1.5 py-0.5 font-mono text-xs">{a.action}</code></Td>
                  <Td className="text-xs text-ink-3">{a.target_type && `${a.target_type} ${a.target_id?.slice(0, 8)}`}</Td>
                  <Td className="font-mono text-xs text-ink-3">{a.ip ?? '—'}</Td>
                  <Td>{a.detail ? <details><summary className="cursor-pointer text-xs text-brand-600">View</summary><pre className="mt-1 max-w-md overflow-auto rounded bg-surface-3 p-2 text-[11px]">{JSON.stringify(a.detail, null, 2)}</pre></details> : '—'}</Td>
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
