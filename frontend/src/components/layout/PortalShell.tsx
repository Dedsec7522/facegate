import { Outlet, useNavigate } from 'react-router-dom'
import { LogOut } from 'lucide-react'
import { useAuth } from '../../lib/auth'
import { Avatar } from '../ui/Misc'
import { Logo } from './Logo'

export function PortalShell() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-30 border-b border-line bg-surface/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-4xl items-center gap-3 px-4">
          <Logo className="size-7" />
          <span className="font-semibold">FaceGate</span>
          <span className="rounded-full border border-line px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-ink-3">My attendance</span>
          <div className="ml-auto flex items-center gap-2">
            <Avatar name={user?.employee_name ?? user?.email} size="sm" />
            <span className="hidden text-sm sm:inline">{user?.employee_name ?? user?.email}</span>
            <button aria-label="Sign out" onClick={() => logout().then(() => navigate('/login'))} className="rounded-md p-2 text-ink-3 hover:bg-surface-3 hover:text-ink"><LogOut className="size-4" /></button>
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto max-w-4xl px-4 py-6 outline-none">
        <Outlet />
      </main>
    </div>
  )
}
