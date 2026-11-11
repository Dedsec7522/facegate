import { format, formatDistanceToNowStrict, parseISO } from 'date-fns'

/**
 * Every time shown in the UI is rendered in the ORGANISATION's time zone, never the device's. The zone comes from
 * the server (`/api/health` → `timezone`, set by `setDisplayTimeZone` at start-up), so a kiosk or office PC whose
 * clock zone is mis-set still shows the right wall-clock times: the server records instants in UTC and this module
 * converts them with the browser's Intl time-zone database. Until the zone is known, the device zone is used.
 */
let displayTimeZone: string | undefined

export function setDisplayTimeZone(tz: string | null | undefined): void {
  displayTimeZone = tz && isKnownZone(tz) ? tz : undefined
}

export function getDisplayTimeZone(): string | undefined {
  return displayTimeZone
}

function isKnownZone(tz: string): boolean {
  try { new Intl.DateTimeFormat('en-US', { timeZone: tz }); return true } catch { return false }
}

/** The instant `d` as a Date whose *local* fields equal the organisation-zone wall clock (so date-fns `format`
 * and calendar arithmetic can be used unchanged). Identity when no organisation zone is known. */
export function zoned(d: Date): Date {
  if (!displayTimeZone) return d
  const p: Record<string, number> = {}
  for (const part of new Intl.DateTimeFormat('en-US', { timeZone: displayTimeZone, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric', second: 'numeric' }).formatToParts(d)) {
    if (part.type !== 'literal') p[part.type] = Number(part.value)
  }
  return new Date(p.year, p.month - 1, p.day, p.hour, p.minute, p.second, d.getMilliseconds())
}

/** "Now" on the organisation's wall clock. */
export const nowZoned = (): Date => zoned(new Date())

const zonedISO = (iso: string): Date => zoned(parseISO(iso))

/** Organisation-zone wall-clock time in the 12-hour style of the HR portal, e.g. "12:13 PM". */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return format(zonedISO(iso), 'hh:mm a')
}

/** Minutes after midnight → "10:47 AM". Used for averaged times, which have no date. */
export function fmtClock(minutes: number | null | undefined): string {
  if (minutes === null || minutes === undefined) return '—'
  const h24 = Math.floor(minutes / 60) % 24
  const m = minutes % 60
  const h12 = h24 % 12 || 12
  return `${String(h12).padStart(2, '0')}:${String(m).padStart(2, '0')} ${h24 < 12 ? 'AM' : 'PM'}`
}

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return format(zonedISO(iso), 'd MMM yyyy, hh:mm a')
}

/** Calendar dates (YYYY-MM-DD) are zone-less and formatted as-is; full timestamps are converted first. */
export function fmtDate(iso: string | null | undefined, pattern = 'EEE d MMM'): string {
  if (!iso) return '—'
  return format(iso.length === 10 ? parseISO(`${iso}T00:00:00`) : zonedISO(iso), pattern)
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

/** Today / N days ago as YYYY-MM-DD on the organisation's calendar. */
export const todayISO = () => format(nowZoned(), 'yyyy-MM-dd')
export const daysAgoISO = (n: number) => format(zoned(new Date(Date.now() - n * 86_400_000)), 'yyyy-MM-dd')
