/** Thin typed fetch wrapper. Cookies carry auth; a 401 triggers one silent refresh then replays the request. */

export class ApiError extends Error {
  status: number
  code?: string
  detail: unknown
  constructor(status: number, detail: unknown) {
    const message =
      typeof detail === 'string' ? detail
      : detail && typeof detail === 'object' && 'message' in (detail as Record<string, unknown>) ? String((detail as Record<string, unknown>).message)
      : Array.isArray(detail) ? detail.map((d: { msg?: string }) => d.msg ?? JSON.stringify(d)).join('; ')
      : `Request failed (${status})`
    super(message)
    this.status = status
    this.detail = detail
    if (detail && typeof detail === 'object' && 'code' in (detail as Record<string, unknown>)) this.code = String((detail as Record<string, unknown>).code)
  }
}

export const API = '/api/v1'
let refreshing: Promise<boolean> | null = null

async function tryRefresh(): Promise<boolean> {
  if (!refreshing) {
    refreshing = fetch(`${API}/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then((r) => r.ok)
      .catch(() => false)
      .finally(() => setTimeout(() => (refreshing = null), 0))
  }
  return refreshing
}

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  body?: unknown
  query?: Record<string, string | number | boolean | null | undefined>
  raw?: boolean
  noRefresh?: boolean
}

export async function request<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const { body, query, raw, noRefresh, headers, ...rest } = opts
  const url = new URL(`${API}${path}`, window.location.origin)
  if (query) for (const [k, v] of Object.entries(query)) if (v !== undefined && v !== null && v !== '') url.searchParams.set(k, String(v))
  const init: RequestInit = {
    credentials: 'include',
    headers: { Accept: 'application/json', ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...(headers ?? {}) },
    ...rest,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  }
  let res = await fetch(url, init)
  if (res.status === 401 && !noRefresh && !path.startsWith('/auth/')) {
    if (await tryRefresh()) res = await fetch(url, init)
  }
  if (!res.ok) {
    let detail: unknown = res.statusText
    try { detail = (await res.json()).detail } catch { /* ignore */ }
    throw new ApiError(res.status, detail)
  }
  if (raw) return res as unknown as T
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string, query?: RequestOptions['query']) => request<T>(path, { method: 'GET', query }),
  post: <T>(path: string, body?: unknown, query?: RequestOptions['query']) => request<T>(path, { method: 'POST', body, query }),
  patch: <T>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T>(path: string, query?: RequestOptions['query']) => request<T>(path, { method: 'DELETE', query }),
}

export function wsUrl(path: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${window.location.host}${API}${path}`
}
