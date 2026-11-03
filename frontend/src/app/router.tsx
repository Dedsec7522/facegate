import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, Navigate } from 'react-router-dom'
import { RequireRole } from '../lib/auth'
import { AdminShell } from '../components/layout/AdminShell'
import { PortalShell } from '../components/layout/PortalShell'

const Landing = lazy(() => import('../pages/Landing'))
const Login = lazy(() => import('../pages/auth/Login'))
const Kiosk = lazy(() => import('../pages/kiosk/Kiosk'))
const Dashboard = lazy(() => import('../pages/admin/Dashboard'))
const Employees = lazy(() => import('../pages/admin/Employees'))
const EmployeeDetail = lazy(() => import('../pages/admin/EmployeeDetail'))
const Enrolment = lazy(() => import('../pages/admin/Enrolment'))
const Attendance = lazy(() => import('../pages/admin/Attendance'))
const Reports = lazy(() => import('../pages/admin/Reports'))
const SettingsPage = lazy(() => import('../pages/admin/Settings'))
const Portal = lazy(() => import('../pages/portal/Portal'))

const Fallback = () => <div className="grid min-h-[40vh] place-items-center text-sm text-ink-3">Loading…</div>
const S = ({ children }: { children: ReactNode }) => <Suspense fallback={<Fallback />}>{children}</Suspense>

export const router = createBrowserRouter([
  { path: '/', element: <S><Landing /></S> },
  { path: '/login', element: <S><Login /></S> },
  { path: '/kiosk', element: <S><Kiosk /></S> },
  {
    path: '/admin',
    element: <RequireRole roles={['admin', 'hr']}><AdminShell /></RequireRole>,
    children: [
      { index: true, element: <S><Dashboard /></S> },
      { path: 'employees', element: <S><Employees /></S> },
      { path: 'employees/:id', element: <S><EmployeeDetail /></S> },
      { path: 'employees/:id/enrol', element: <S><Enrolment /></S> },
      { path: 'attendance', element: <S><Attendance /></S> },
      { path: 'reports', element: <S><Reports /></S> },
      { path: 'settings', element: <S><SettingsPage /></S> },
    ],
  },
  {
    path: '/portal',
    element: <RequireRole roles={['employee', 'admin', 'hr']}><PortalShell /></RequireRole>,
    children: [{ index: true, element: <S><Portal /></S> }],
  },
  { path: '*', element: <Navigate to="/" replace /> },
])
