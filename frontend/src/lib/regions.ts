/**
 * Country / region → IANA time zone(s). Picking a region with a single zone sets the organisation zone
 * automatically; regions spanning several zones offer a second choice. This is a deliberate offline table:
 * no IP-geolocation service is called (the product runs on private networks and uses no cloud APIs), and the
 * device's own zone setting is never trusted implicitly because a mis-set PC clock is exactly the failure to avoid.
 */
export interface Region {
  code: string
  name: string
  zones: Array<{ id: string; label: string }>
}

export const REGIONS: Region[] = [
  { code: 'IN', name: 'India', zones: [{ id: 'Asia/Kolkata', label: 'India Standard Time (IST)' }] },
  { code: 'GB', name: 'United Kingdom', zones: [{ id: 'Europe/London', label: 'London (GMT / BST)' }] },
  { code: 'IE', name: 'Ireland', zones: [{ id: 'Europe/Dublin', label: 'Dublin (GMT / IST)' }] },
  { code: 'AE', name: 'United Arab Emirates', zones: [{ id: 'Asia/Dubai', label: 'Gulf Standard Time' }] },
  { code: 'SA', name: 'Saudi Arabia', zones: [{ id: 'Asia/Riyadh', label: 'Arabia Standard Time' }] },
  { code: 'QA', name: 'Qatar', zones: [{ id: 'Asia/Qatar', label: 'Arabia Standard Time' }] },
  { code: 'PK', name: 'Pakistan', zones: [{ id: 'Asia/Karachi', label: 'Pakistan Standard Time' }] },
  { code: 'BD', name: 'Bangladesh', zones: [{ id: 'Asia/Dhaka', label: 'Bangladesh Standard Time' }] },
  { code: 'LK', name: 'Sri Lanka', zones: [{ id: 'Asia/Colombo', label: 'Sri Lanka Standard Time' }] },
  { code: 'NP', name: 'Nepal', zones: [{ id: 'Asia/Kathmandu', label: 'Nepal Time' }] },
  { code: 'SG', name: 'Singapore', zones: [{ id: 'Asia/Singapore', label: 'Singapore Standard Time' }] },
  { code: 'MY', name: 'Malaysia', zones: [{ id: 'Asia/Kuala_Lumpur', label: 'Malaysia Time' }] },
  { code: 'PH', name: 'Philippines', zones: [{ id: 'Asia/Manila', label: 'Philippine Time' }] },
  { code: 'ID', name: 'Indonesia', zones: [{ id: 'Asia/Jakarta', label: 'Western (Jakarta)' }, { id: 'Asia/Makassar', label: 'Central (Makassar)' }, { id: 'Asia/Jayapura', label: 'Eastern (Jayapura)' }] },
  { code: 'TH', name: 'Thailand', zones: [{ id: 'Asia/Bangkok', label: 'Indochina Time' }] },
  { code: 'VN', name: 'Vietnam', zones: [{ id: 'Asia/Ho_Chi_Minh', label: 'Indochina Time' }] },
  { code: 'HK', name: 'Hong Kong', zones: [{ id: 'Asia/Hong_Kong', label: 'Hong Kong Time' }] },
  { code: 'CN', name: 'China', zones: [{ id: 'Asia/Shanghai', label: 'China Standard Time' }] },
  { code: 'TW', name: 'Taiwan', zones: [{ id: 'Asia/Taipei', label: 'Taipei Standard Time' }] },
  { code: 'JP', name: 'Japan', zones: [{ id: 'Asia/Tokyo', label: 'Japan Standard Time' }] },
  { code: 'KR', name: 'South Korea', zones: [{ id: 'Asia/Seoul', label: 'Korea Standard Time' }] },
  { code: 'AU', name: 'Australia', zones: [{ id: 'Australia/Sydney', label: 'Sydney / Canberra (AEST)' }, { id: 'Australia/Melbourne', label: 'Melbourne (AEST)' }, { id: 'Australia/Brisbane', label: 'Brisbane (AEST, no DST)' }, { id: 'Australia/Adelaide', label: 'Adelaide (ACST)' }, { id: 'Australia/Perth', label: 'Perth (AWST)' }, { id: 'Australia/Darwin', label: 'Darwin (ACST, no DST)' }] },
  { code: 'NZ', name: 'New Zealand', zones: [{ id: 'Pacific/Auckland', label: 'New Zealand Time' }] },
  { code: 'ZA', name: 'South Africa', zones: [{ id: 'Africa/Johannesburg', label: 'South Africa Standard Time' }] },
  { code: 'NG', name: 'Nigeria', zones: [{ id: 'Africa/Lagos', label: 'West Africa Time' }] },
  { code: 'KE', name: 'Kenya', zones: [{ id: 'Africa/Nairobi', label: 'East Africa Time' }] },
  { code: 'EG', name: 'Egypt', zones: [{ id: 'Africa/Cairo', label: 'Eastern European Time' }] },
  { code: 'TR', name: 'Türkiye', zones: [{ id: 'Europe/Istanbul', label: 'Turkey Time' }] },
  { code: 'DE', name: 'Germany', zones: [{ id: 'Europe/Berlin', label: 'Central European Time' }] },
  { code: 'FR', name: 'France', zones: [{ id: 'Europe/Paris', label: 'Central European Time' }] },
  { code: 'NL', name: 'Netherlands', zones: [{ id: 'Europe/Amsterdam', label: 'Central European Time' }] },
  { code: 'BE', name: 'Belgium', zones: [{ id: 'Europe/Brussels', label: 'Central European Time' }] },
  { code: 'ES', name: 'Spain', zones: [{ id: 'Europe/Madrid', label: 'Central European Time' }, { id: 'Atlantic/Canary', label: 'Canary Islands' }] },
  { code: 'PT', name: 'Portugal', zones: [{ id: 'Europe/Lisbon', label: 'Western European Time' }, { id: 'Atlantic/Azores', label: 'Azores' }] },
  { code: 'IT', name: 'Italy', zones: [{ id: 'Europe/Rome', label: 'Central European Time' }] },
  { code: 'CH', name: 'Switzerland', zones: [{ id: 'Europe/Zurich', label: 'Central European Time' }] },
  { code: 'AT', name: 'Austria', zones: [{ id: 'Europe/Vienna', label: 'Central European Time' }] },
  { code: 'PL', name: 'Poland', zones: [{ id: 'Europe/Warsaw', label: 'Central European Time' }] },
  { code: 'SE', name: 'Sweden', zones: [{ id: 'Europe/Stockholm', label: 'Central European Time' }] },
  { code: 'NO', name: 'Norway', zones: [{ id: 'Europe/Oslo', label: 'Central European Time' }] },
  { code: 'DK', name: 'Denmark', zones: [{ id: 'Europe/Copenhagen', label: 'Central European Time' }] },
  { code: 'FI', name: 'Finland', zones: [{ id: 'Europe/Helsinki', label: 'Eastern European Time' }] },
  { code: 'GR', name: 'Greece', zones: [{ id: 'Europe/Athens', label: 'Eastern European Time' }] },
  { code: 'RO', name: 'Romania', zones: [{ id: 'Europe/Bucharest', label: 'Eastern European Time' }] },
  { code: 'UA', name: 'Ukraine', zones: [{ id: 'Europe/Kyiv', label: 'Eastern European Time' }] },
  { code: 'RU', name: 'Russia', zones: [{ id: 'Europe/Moscow', label: 'Moscow' }, { id: 'Asia/Yekaterinburg', label: 'Yekaterinburg' }, { id: 'Asia/Novosibirsk', label: 'Novosibirsk' }, { id: 'Asia/Vladivostok', label: 'Vladivostok' }] },
  { code: 'IL', name: 'Israel', zones: [{ id: 'Asia/Jerusalem', label: 'Israel Time' }] },
  { code: 'US', name: 'United States', zones: [{ id: 'America/New_York', label: 'Eastern' }, { id: 'America/Chicago', label: 'Central' }, { id: 'America/Denver', label: 'Mountain' }, { id: 'America/Phoenix', label: 'Arizona (no DST)' }, { id: 'America/Los_Angeles', label: 'Pacific' }, { id: 'America/Anchorage', label: 'Alaska' }, { id: 'Pacific/Honolulu', label: 'Hawaii' }] },
  { code: 'CA', name: 'Canada', zones: [{ id: 'America/Toronto', label: 'Eastern (Toronto)' }, { id: 'America/Winnipeg', label: 'Central (Winnipeg)' }, { id: 'America/Edmonton', label: 'Mountain (Edmonton)' }, { id: 'America/Vancouver', label: 'Pacific (Vancouver)' }, { id: 'America/Halifax', label: 'Atlantic (Halifax)' }, { id: 'America/St_Johns', label: 'Newfoundland' }] },
  { code: 'MX', name: 'Mexico', zones: [{ id: 'America/Mexico_City', label: 'Central (Mexico City)' }, { id: 'America/Cancun', label: 'Cancún' }, { id: 'America/Tijuana', label: 'Pacific (Tijuana)' }] },
  { code: 'BR', name: 'Brazil', zones: [{ id: 'America/Sao_Paulo', label: 'Brasília (São Paulo)' }, { id: 'America/Manaus', label: 'Amazon (Manaus)' }] },
  { code: 'AR', name: 'Argentina', zones: [{ id: 'America/Argentina/Buenos_Aires', label: 'Argentina Time' }] },
  { code: 'CL', name: 'Chile', zones: [{ id: 'America/Santiago', label: 'Chile Time' }] },
  { code: 'CO', name: 'Colombia', zones: [{ id: 'America/Bogota', label: 'Colombia Time' }] },
  { code: 'PE', name: 'Peru', zones: [{ id: 'America/Lima', label: 'Peru Time' }] },
]

/** The region that owns a zone id, if any. */
export function regionForZone(zone: string): Region | undefined {
  return REGIONS.find((r) => r.zones.some((z) => z.id === zone))
}

/** True when the browser's Intl implementation knows this IANA zone. */
export function isValidZone(zone: string): boolean {
  try { new Intl.DateTimeFormat('en-US', { timeZone: zone }); return true } catch { return false }
}

/** Current wall-clock time in a zone, e.g. "07:21 PM" (for showing the admin what the choice means). */
export function clockIn(zone: string): string {
  try { return new Intl.DateTimeFormat('en-US', { timeZone: zone, hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date()) } catch { return '—' }
}

/** UTC offset of a zone right now, e.g. "UTC+05:30". */
export function offsetOf(zone: string): string {
  try {
    const part = new Intl.DateTimeFormat('en-US', { timeZone: zone, timeZoneName: 'longOffset' }).formatToParts(new Date()).find((p) => p.type === 'timeZoneName')?.value ?? ''
    return part.replace('GMT', 'UTC') || 'UTC'
  } catch { return '' }
}
