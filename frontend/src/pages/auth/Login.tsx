import { useEffect, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeft, FlaskConical, KeyRound, ShieldCheck, UserRound } from 'lucide-react'
import { Logo } from '../../components/layout/Logo'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Field'
import { isMfaRequired, useAuth } from '../../lib/auth'
import { API, ApiError } from '../../lib/api'
import { cn } from '../../lib/cn'
import { popVariants } from '../../lib/motion'

type Who = 'admin' | 'employee'
type TestAccount = { username: string; role: 'admin' | 'hr' | 'employee'; name: string; code: string | null }
const SEED_PASSWORD = 'Welcome123'

/**
 * One sign-in endpoint for everyone (the server decides the landing page by role). The Administrator / Employee
 * tabs only change the wording and placeholders, and `?as=employee` preselects the employee tab so the landing
 * page can link straight to it.
 *
 * In a development environment the page also offers one-click test accounts (`GET /auth/test-accounts`, which
 * only answers when ENVIRONMENT=development), as seeded by `tools/seed.py --demo --employee-logins`.
 */
export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const loc = useLocation()
  const [params, setParams] = useSearchParams()
  const who: Who = params.get('as') === 'employee' ? 'employee' : 'admin'
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<'credentials' | 'mfa'>('credentials')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [testAccounts, setTestAccounts] = useState<TestAccount[]>([])

  useEffect(() => {
    let cancelled = false
    fetch(`${API}/auth/test-accounts`).then((r) => (r.ok ? r.json() : [])).then((rows: TestAccount[]) => { if (!cancelled) setTestAccounts(rows) }).catch(() => undefined)
    return () => { cancelled = true }
  }, [])

  const setWho = (w: Who) => { setParams(w === 'employee' ? { as: 'employee' } : {}, { replace: true }); setError(null) }

  const signIn = async (identifier: string, pw: string, mfa?: string) => {
    setBusy(true)
    setError(null)
    try {
      const u = await login(identifier.trim(), pw, mfa)
      const from = (loc.state as { from?: string } | null)?.from
      const home = u.role === 'employee' ? '/portal' : '/admin'
      // Return to the page that asked for sign-in only if it belongs to this role's area; otherwise an admin
      // signing in after an employee on a shared browser would be sent to the employee portal (and vice versa).
      navigate(from && from.startsWith(home) ? from : home, { replace: true })
    } catch (err) {
      if (isMfaRequired(err) && step === 'credentials') { setStep('mfa'); return }
      setError(err instanceof ApiError ? err.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void signIn(email, password, step === 'mfa' ? code : undefined) }
  const signInAsTestAccount = (u: string, p: string) => { setEmail(u); setPassword(p); void signIn(u, p) }

  const tests = testAccounts.filter((t) => (who === 'employee' ? t.role === 'employee' : t.role !== 'employee')).slice(0, 4)

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1fr]">
      <div className="theme-dark relative hidden overflow-hidden bg-surface p-10 text-ink lg:flex lg:flex-col lg:justify-between">
        <div className="glow-fade pointer-events-none absolute inset-0" aria-hidden />
        <Link to="/" className="relative flex items-center gap-2.5"><Logo className="size-8" /><span className="font-semibold">FaceGate</span></Link>
        <div className="relative max-w-md">
          <ShieldCheck className="mb-4 size-8 text-accent-400" aria-hidden />
          <h2 className="text-2xl font-semibold">One sign-in for everyone</h2>
          <p className="mt-2 text-ink-2">Employees land on their attendance portal; administrators and HR land on the console. Your username (employee code) or work email decides which.</p>
        </div>
        <p className="relative text-xs text-ink-3">Every action is role-checked on the server and written to the audit log.</p>
      </div>

      <div className="flex items-center justify-center px-6 py-10">
        <motion.div variants={popVariants} initial="hidden" animate="show" className="w-full max-w-sm">
          <Link to="/" className="mb-8 inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink lg:hidden"><ArrowLeft className="size-4" /> Back</Link>
          <h1 className="text-2xl font-semibold">Sign in</h1>

          <div role="tablist" aria-label="Who is signing in" className="mt-4 grid grid-cols-2 rounded-lg border border-line bg-surface-2 p-1 text-sm font-medium">
            {([['admin', 'Administrator / HR', ShieldCheck], ['employee', 'Employee', UserRound]] as const).map(([w, label, Icon]) => (
              <button key={w} type="button" role="tab" aria-selected={who === w} onClick={() => setWho(w)}
                className={cn('flex items-center justify-center gap-2 rounded-md px-3 py-2 transition-colors', who === w ? 'bg-surface text-ink shadow-sm' : 'text-ink-3 hover:text-ink')}>
                <Icon className="size-4" aria-hidden />{label}
              </button>
            ))}
          </div>
          <p className="mt-3 text-sm text-ink-3">
            {who === 'employee' ? 'Your username is your employee code (for example e1001) or your work email. You will land on your attendance dashboard.' : 'Username or work email, and your password. You will land on the admin console.'}
          </p>

          <form onSubmit={submit} className="mt-5 space-y-4" noValidate>
            <AnimatePresence mode="wait" initial={false}>
              {step === 'credentials' ? (
                <motion.div key="cred" className="space-y-4" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} transition={{ duration: 0.18 }}>
                  <Input label={who === 'employee' ? 'Employee code or email' : 'Username or email'} type="text" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus placeholder={who === 'employee' ? 'e1001 or you@company.com' : 'admin or you@company.com'} />
                  <Input label="Password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
                </motion.div>
              ) : (
                <motion.div key="mfa" className="space-y-4" initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: 10 }} transition={{ duration: 0.18 }}>
                  <div className="flex items-center gap-3 rounded-lg border border-line bg-surface-3 p-3 text-sm">
                    <KeyRound className="size-5 text-brand-500" aria-hidden />
                    <span>Two-factor authentication is on for <strong>{email}</strong>. Enter the 6-digit code from your authenticator app.</span>
                  </div>
                  <Input label="Authentication code" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]*" maxLength={8} value={code} onChange={(e) => setCode(e.target.value)} required autoFocus className="text-center text-lg tracking-[0.4em]" />
                  <button type="button" onClick={() => { setStep('credentials'); setCode('') }} className="text-sm text-ink-3 hover:text-ink">Use a different account</button>
                </motion.div>
              )}
            </AnimatePresence>
            {error && <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">{error}</p>}
            <Button type="submit" size="lg" className="w-full" loading={busy}>{step === 'mfa' ? 'Verify and sign in' : who === 'employee' ? 'Open my dashboard' : 'Continue'}</Button>
          </form>

          {tests.length > 0 && step === 'credentials' && (
            <section aria-label="Test accounts" className="mt-6 rounded-lg border border-dashed border-amber-400/60 bg-amber-500/10 p-3 text-sm">
              <p className="flex items-center gap-2 font-medium text-amber-700 dark:text-amber-300"><FlaskConical className="size-4" aria-hidden /> Development test accounts</p>
              <p className="mt-1 text-xs text-ink-3">Seeded by <code>tools/seed.py --demo --employee-logins</code>. Password for all: <code>{SEED_PASSWORD}</code>. Hidden outside development.</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {tests.map((t) => (
                  <Button key={t.username} size="sm" variant="outline" disabled={busy} onClick={() => signInAsTestAccount(t.username, SEED_PASSWORD)}>
                    Sign in as {t.name}{t.code ? ` · ${t.code}` : ''}
                  </Button>
                ))}
              </div>
              {who === 'employee' && <p className="mt-2 text-xs text-ink-3">Any employee works the same way: username = employee code in lower case.</p>}
            </section>
          )}

          <p className="mt-6 text-center text-xs text-ink-3">Forgotten your password? Ask an administrator to reset it from the Users panel.</p>
        </motion.div>
      </div>
    </div>
  )
}
