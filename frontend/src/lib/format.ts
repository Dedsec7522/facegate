import { format, formatDistanceToNowStrict, parseISO } from 'date-fns'

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return format(parseISO(iso), 'HH:mm')
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return format(parseISO(iso), 'd MMM yyyy, HH:mm')
}

export function fmtDate(iso: string | null | undefined, pattern = 'EEE d MMM'): string {
  if (!iso) return '—'
  return format(parseISO(iso.length === 10 ? `${iso}T00:00:00` : iso), pattern)
}

export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  return formatDistanceToNowStrict(parseISO(iso), { addSuffix: true })
}

export function fmtMinutes(min: number | null | undefined): string {
  if (!min) return '0h'
  const h = Math.floor(min / 60)
  const m = min % 60
  return h ? `${h}h ${m ? `${m}m` : ''}`.trim() : `${m}m`
}

export function pct(n: number): string {
  return `${Math.round(n * 100)}%`
}

export function initials(name: string | null | undefined): string {
  if (!name) return '?'
  return name.split(/\s+/).slice(0, 2).map((p) => p[0]?.toUpperCase() ?? '').join('')
}

export const todayISO = () => format(new Date(), 'yyyy-MM-dd')
export const daysAgoISO = (n: number) => format(new Date(Date.now() - n * 86_400_000), 'yyyy-MM-dd')
