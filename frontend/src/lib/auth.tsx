import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { api, ApiError } from './api'
import type { Role, User } from './types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string, totp?: string) => Promise<User>
  logout: () => Promise<void>
  refresh: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setUser(await api.get<User>('/auth/me'))
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const login = useCallback(async (email: string, password: string, totp?: string) => {
    const u = await api.post<User>('/auth/login', { identifier: email, password, totp_code: totp || undefined })
    setUser(u)
    return u
  }, [])

  const logout = useCallback(async () => {
    try { await api.post('/auth/logout') } catch { /* already gone */ }
    setUser(null)
  }, [])

  const value = useMemo(() => ({ user, loading, login, logout, refresh }), [user, loading, login, logout, refresh])
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAuth outside AuthProvider')
  return v
}

export function RequireRole({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth()
  const loc = useLocation()
  if (loading) return <div className="min-h-dvh grid place-items-center text-ink-3 text-sm">Checking your session…</div>
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />
  if (!roles.includes(user.role)) return <Navigate to={user.role === 'employee' ? '/portal' : '/admin'} replace />
  return <>{children}</>
}

export function isMfaRequired(e: unknown): boolean {
  return e instanceof ApiError && e.status === 401 && /MFA/i.test(e.message)
}
