import { useEffect, useState } from 'react'
import { Globe, MonitorSmartphone } from 'lucide-react'
import { Button } from './ui/Button'
import { Input, Select } from './ui/Field'
import { clockIn, isValidZone, offsetOf, regionForZone, REGIONS } from '../lib/regions'

/**
 * Organisation time-zone picker. Choose a country/region: a single-zone region sets the zone at once; a region with
 * several zones shows a second list. "Other" accepts any IANA name. "Use this device's zone" reads the browser's
 * setting but is clearly marked as a guess, because the whole point of an organisation zone is to be right even
 * when a kiosk PC's clock zone is not.
 */
export function RegionPicker({ value, onChange, disabled }: { value: string; onChange: (zone: string) => void; disabled?: boolean }) {
  const owner = regionForZone(value)
  const [region, setRegion] = useState<string>(owner?.code ?? (value ? 'OTHER' : ''))
  useEffect(() => { const o = regionForZone(value); if (o) setRegion(o.code); else if (value) setRegion('OTHER') }, [value])
  const selected = REGIONS.find((r) => r.code === region)
  const [tick, setTick] = useState(0)
  useEffect(() => { const t = window.setInterval(() => setTick((n) => n + 1), 30_000); return () => window.clearInterval(t) }, [])
  const deviceZone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const valid = isValidZone(value)

  const pickRegion = (code: string) => {
    setRegion(code)
    const r = REGIONS.find((x) => x.code === code)
    if (r && r.zones.length === 1) onChange(r.zones[0].id)  // automatic: one zone for this region
    else if (r && !r.zones.some((z) => z.id === value)) onChange(r.zones[0].id)
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Select label="Country / region" value={region} onChange={(e) => pickRegion(e.target.value)} disabled={disabled} hint="Picking a region sets its time zone automatically.">
        <option value="">Select a region…</option>
        {REGIONS.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
        <option value="OTHER">Other (enter an IANA zone name)</option>
      </Select>
      {selected && selected.zones.length > 1 ? (
        <Select label={`Time zone in ${selected.name}`} value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled}>
          {selected.zones.map((z) => <option key={z.id} value={z.id}>{z.label} · {z.id}</option>)}
        </Select>
      ) : region === 'OTHER' ? (
        <Input label="IANA time zone" value={value} onChange={(e) => onChange(e.target.value)} disabled={disabled} placeholder="e.g. Asia/Kolkata" error={value && !valid ? 'Not a known time zone' : undefined} />
      ) : (
        <Input label="Time zone" value={value} readOnly disabled hint={selected ? selected.zones[0].label : undefined} />
      )}
      <div className="flex flex-wrap items-center gap-3 text-sm text-ink-2 sm:col-span-2" key={tick}>
        <Globe className="size-4 shrink-0 text-brand-600" aria-hidden />
        {valid ? <span>Organisation time now: <strong className="tabular text-ink">{clockIn(value)}</strong> ({value}, {offsetOf(value)}). Every time in FaceGate is shown in this zone, whatever a PC's own clock zone says.</span> : <span>Choose a region to set the organisation time zone.</span>}
      </div>
      {!disabled && (
        <div className="flex flex-wrap items-center gap-2 text-xs text-ink-3 sm:col-span-2">
          <Button size="sm" variant="outline" leftIcon={<MonitorSmartphone className="size-4" />} onClick={() => onChange(deviceZone)} disabled={deviceZone === value}>Use this device's zone ({deviceZone})</Button>
          <span>Only a suggestion: it reflects this computer's clock setting, which may be wrong. The region above is the reliable choice.</span>
        </div>
      )}
    </div>
  )
}
