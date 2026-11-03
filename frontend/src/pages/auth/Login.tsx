import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { ArrowLeft, KeyRound, ShieldCheck } from 'lucide-react'
import { Logo } from '../../components/layout/Logo'
import { Button } from '../../components/ui/Button'
import { Input } from '../../components/ui/Field'
import { isMfaRequired, useAuth } from '../../lib/auth'
import { ApiError } from '../../lib/api'
import { popVariants } from '../../lib/motion'

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const loc = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<'credentials' | 'mfa'>('credentials')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const u = await login(email.trim(), password, step === 'mfa' ? code : undefined)
      const from = (loc.state as { from?: string } | null)?.from
      navigate(from && from !== '/login' ? from : u.role === 'employee' ? '/portal' : '/admin', { replace: true })
    } catch (err) {
      if (isMfaRequired(err) && step === 'credentials') { setStep('mfa'); return }
      setError(err instanceof ApiError ? err.message : 'Sign-in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-[1fr_1fr]">
      <div className="theme-dark relative hidden overflow-hidden bg-surface p-10 text-ink lg:flex lg:flex-col lg:justify-between">
        <div className="grid-fade pointer-events-none absolute inset-0" aria-hidden />
        <Link to="/" className="relative flex items-center gap-2.5"><Logo className="size-8" /><span className="font-semibold">FaceGate</span></Link>
        <div className="relative max-w-md">
          <ShieldCheck className="mb-4 size-8 text-accent-400" aria-hidden />
          <h2 className="text-2xl font-semibold">Administration console</h2>
          <p className="mt-2 text-ink-2">Manage employees, enrol faces, review attendance and export reports. Access is role-based and every action is logged.</p>
        </div>
        <p className="relative text-xs text-ink-3">Employees do not need an account to check in — only to review their own history.</p>
      </div>

      <div className="flex items-center justify-center px-6 py-10">
        <motion.div variants={popVariants} initial="hidden" animate="show" className="w-full max-w-sm">
          <Link to="/" className="mb-8 inline-flex items-center gap-1.5 text-sm text-ink-3 hover:text-ink lg:hidden"><ArrowLeft className="size-4" /> Back</Link>
          <h1 className="text-2xl font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-ink-3">Use your username or work email, and your password.</p>

          <form onSubmit={submit} className="mt-6 space-y-4" noValidate>
            <AnimatePresence mode="wait" initial={false}>
              {step === 'credentials' ? (
                <motion.div key="cred" className="space-y-4" initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }} exit={{ opacity: 0, x: -10 }} transition={{ duration: 0.18 }}>
                  <Input label="Username or email" type="text" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus placeholder="admin or you@company.com" />
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
            <Button type="submit" size="lg" className="w-full" loading={busy}>{step === 'mfa' ? 'Verify and sign in' : 'Continue'}</Button>
          </form>
          <p className="mt-6 text-center text-xs text-ink-3">Forgotten your password? Ask an administrator to reset it from the Users panel.</p>
        </motion.div>
      </div>
    </div>
  )
}
