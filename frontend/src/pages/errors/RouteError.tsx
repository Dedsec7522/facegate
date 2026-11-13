import { isRouteErrorResponse, useRouteError } from 'react-router-dom'
import { ErrorPage } from './ErrorPage'
import type { ErrorKind } from './ScannerFace'

/**
 * The router's error boundary: anything thrown while a route renders or loads (a crash in a page, a lazy chunk that
 * fails to download, a thrown Response) lands here instead of React Router's bare default screen.
 */
export function RouteError() {
  const err = useRouteError()
  let kind: ErrorKind = '500'
  if (isRouteErrorResponse(err)) kind = err.status === 404 ? '404' : err.status === 401 || err.status === 403 ? '403' : '500'
  else if (!navigator.onLine) kind = 'offline' // typically a page chunk that could not be fetched
  const detail = !import.meta.env.DEV ? undefined
    : isRouteErrorResponse(err) ? `${err.status} ${err.statusText}`
    : err instanceof Error ? (err.stack ?? err.message) : String(err)
  return <ErrorPage kind={kind} detail={detail} />
}
