import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { AnimatePresence, motion } from 'motion/react'
import { Activity, BarChart3, CalendarCheck2, LayoutDashboard, LogOut, Menu, ScanFace, Settings, ShieldCheck, Users, X } from 'lucide-react'
import { useAuth } from '../../lib/auth'
import { cn } from '../../lib/cn'
import { pageVariants, spring } from '../../lib/motion'
import { Avatar } from '../ui/Misc'
import { Logo } from './Logo'
import { ThemeToggle } from './ThemeToggle'

const nav = [
  { to: '/admin', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/admin/employees', label: 'Employees', icon: Users },
  { to: '/admin/attendance', label: 'Attendance', icon: CalendarCheck2 },
  { to: '/admin/reports', label: 'Reports', icon: BarChart3 },
  { to: '/admin/settings', label: 'Settings & Security', icon: Settings },
  { to: '/admin/load-test', label: 'Locust load test', icon: Activity },
]

export function AdminShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const loc = useLocation()
  const [open, setOpen] = useState(false)
  useEffect(() => { setOpen(false) }, [loc.pathname])
  useEffect(() => {
    // Move focus to main content on route change for screen-reader users.
    document.getElementById('main')?.focus({ preventScroll: true })
  }, [loc.pathname])

  const sidebar = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center gap-2.5 px-5">
        <Logo className="size-8" />
        <span className="text-[15px] font-semibold tracking-tight">FaceGate</span>
        <span className="ml-auto rounded-full border border-line px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-ink-3">Admin</span>
      </div>
      <nav className="flex-1 space-y-0.5 px-3 py-2" aria-label="Primary">
        {nav.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.end} className={({ isActive }) => cn('group relative flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors', isActive ? 'text-brand-700 dark:text-brand-100' : 'text-ink-2 hover:bg-surface-3 hover:text-ink')}>
            {({ isActive }) => (
              <>
                {isActive && <motion.span layoutId="nav-active" className="absolute inset-0 rounded-md bg-brand-50 dark:bg-brand-800/50" transition={spring.snappy} />}
                <n.icon className="relative size-[18px]" aria-hidden />
                <span className="relative">{n.label}</span>
              </>
            )}
          </NavLink>
        ))}
        <div className="pt-3">
          <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-ink-3">Kiosk</p>
          <NavLink to="/kiosk" className="flex h-10 items-center gap-3 rounded-md px-3 text-sm font-medium text-ink-2 hover:bg-surface-3 hover:text-ink">
            <ScanFace className="size-[18px]" aria-hidden /> Open attendance kiosk
          </NavLink>
        </div>
      </nav>
      <div className="border-t border-line p-3">
        <div className="mb-1 flex items-center justify-between px-2"><span className="text-xs text-ink-3">Appearance</span><ThemeToggle /></div>
        <div className="flex items-center gap-3 rounded-md px-2 py-2">
          <Avatar name={user?.employee_name ?? user?.email} size="sm" />
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{user?.employee_name ?? user?.email}</p>
            <p className="flex items-center gap-1 text-xs text-ink-3">
              <ShieldCheck className={cn('size-3', user?.mfa_enabled ? 'text-accent-600' : 'text-amber-500')} aria-hidden />
              {user?.mfa_enabled ? 'MFA on' : 'MFA off'} · {user?.role}
            </p>
          </div>
          <button aria-label="Sign out" title="Sign out" onClick={() => logout().then(() => navigate('/login'))} className="rounded-md p-2 text-ink-3 hover:bg-surface-3 hover:text-ink">
            <LogOut className="size-4" />
          </button>
        </div>
      </div>
    </div>
  )

  return (
    <div className="min-h-dvh lg:grid lg:grid-cols-[256px_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[60] focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-pop">Skip to content</a>
      <aside className="hidden lg:block border-r border-line bg-surface sticky top-0 h-dvh">{sidebar}</aside>

      <div className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b border-line bg-surface/90 px-4 backdrop-blur lg:hidden">
        <button aria-label="Open navigation" onClick={() => setOpen(true)} className="rounded-md p-2 hover:bg-surface-3"><Menu className="size-5" /></button>
        <Logo className="size-7" /><span className="font-semibold">FaceGate</span>
      </div>
      <AnimatePresence>
        {open && (
          <motion.div className="fixed inset-0 z-50 lg:hidden" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
            <div className="absolute inset-0 bg-brand-950/50" onClick={() => setOpen(false)} />
            <motion.aside initial={{ x: -280 }} animate={{ x: 0 }} exit={{ x: -280 }} transition={spring.snappy} className="absolute inset-y-0 left-0 w-[272px] bg-surface shadow-pop">
              <button aria-label="Close navigation" onClick={() => setOpen(false)} className="absolute right-3 top-4 rounded-md p-2 hover:bg-surface-3"><X className="size-5" /></button>
              {sidebar}
            </motion.aside>
          </motion.div>
        )}
      </AnimatePresence>

      <main id="main" tabIndex={-1} className="min-w-0 px-4 py-6 sm:px-6 lg:px-8 lg:py-8 outline-none">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div key={loc.pathname} variants={pageVariants} initial="initial" animate="enter" exit="exit" className="mx-auto max-w-7xl">
            <Outlet />
          </motion.div>
        </AnimatePresence>
      </main>
    </div>
  )
}
