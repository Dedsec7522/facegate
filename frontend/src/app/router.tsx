import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, useParams } from 'react-router-dom'
import { RequireRole } from '../lib/auth'
import { AdminShell } from '../components/layout/AdminShell'
import { PortalShell } from '../components/layout/PortalShell'
// Error pages are imported eagerly: a page chunk that fails to download must not need another download to say so.
import { ErrorPage } from '../pages/errors/ErrorPage'
import { RouteError } from '../pages/errors/RouteError'

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
const LoadTest = lazy(() => import('../pages/admin/LoadTest'))
const Portal = lazy(() => import('../pages/portal/Portal'))

const Fallback = () => <div className="grid min-h-[40vh] place-items-center text-sm text-ink-3">Loading…</div>
const S = ({ children }: { children: ReactNode }) => <Suspense fallback={<Fallback />}>{children}</Suspense>

/** Development only: `/_error/404 | 403 | 500 | offline` shows that page; `/_error/crash` throws for real, to exercise the boundary. */
function ErrorPreview() {
  const { kind } = useParams()
  if (kind === 'crash') throw new Error('Preview crash: thrown on purpose by /_error/crash')
  return <ErrorPage kind={kind === '403' || kind === '500' || kind === 'offline' ? kind : '404'} />
}

export const router = createBrowserRouter([
  {
    // Pathless parent: anything a route throws while rendering or loading bubbles up to this one error page.
    errorElement: <RouteError />,
    children: [
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
          { path: 'load-test', element: <S><LoadTest /></S> },
        ],
      },
      {
        path: '/portal',
        element: <RequireRole roles={['employee', 'admin', 'hr']}><PortalShell /></RequireRole>,
        children: [{ index: true, element: <S><Portal /></S> }],
      },
      ...(import.meta.env.DEV ? [{ path: '/_error/:kind', element: <ErrorPreview /> }] : []),
      { path: '*', element: <ErrorPage kind="404" /> },
    ],
  },
])
