import { AlertTriangle, Users } from 'lucide-react'
import { cn } from '../../lib/cn'
import { fmtTime } from '../../lib/format'
import type { FrameFeedback } from '../../lib/types'

const COVER_ISSUES = ['covered', 'eyes_covered']
const fmt = (iso: string) => fmtTime(iso)

/**
 * Warnings derived from the per-frame feedback: a partially covered face (error) and more than one person in
 * view (warning, listing who the bystanders are and whether they are signed in). Works inside `.theme-dark`
 * subtrees too, so it only uses ink tokens plus red/amber accents.
 */
export function FrameAlerts({ fb, subject = 'the person closest to the camera', className }: { fb: FrameFeedback | null; subject?: string; className?: string }) {
  if (!fb) return null
  const covered = fb.issues?.find((i) => COVER_ISSUES.includes(i))
  const people = fb.faces ?? 0
  const others = fb.others ?? []
  if (!covered && people < 2) return null
  return (
    <div className={cn('space-y-2', className)}>
      {covered && (
        <p role="alert" className="flex gap-2 rounded-lg border border-red-400/50 bg-red-500/10 px-3 py-2 text-sm text-ink-2">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-red-500" />
          <span><strong className="text-red-500">{covered === 'eyes_covered' ? 'Eyes covered.' : 'Face partially covered.'}</strong> {fb.guidance}</span>
        </p>
      )}
      {people >= 2 && (
        <div role="status" className="rounded-lg border border-amber-400/50 bg-amber-500/10 px-3 py-2 text-sm text-ink-2">
          <p className="flex gap-2">
            <Users className="mt-0.5 size-4 shrink-0 text-amber-500" />
            <span><strong className="text-amber-500">{people} people in view.</strong> {fb.state === 'multiple_faces' ? fb.guidance : `Only ${subject} is verified.`}</span>
          </p>
          {others.length > 0 && (
            <ul className="mt-1.5 space-y-0.5 pl-6 text-xs">
              {others.map((o, i) => (
                <li key={i}>
                  {o.name
                    ? <><span className="font-medium text-ink">{o.name}</span>{o.code ? ` (${o.code})` : ''} · {o.signed_in ? `signed in${o.since ? ` since ${fmt(o.since)}` : ''}` : 'not signed in'}</>
                    : 'Unknown person (not enrolled or not recognised)'}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
