import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AnimatePresence, motion } from 'motion/react'
import { AlertTriangle, ArrowLeft, Check, CheckCircle2, RefreshCw, Save, ShieldCheck } from 'lucide-react'
import { CameraStage, type StageMode } from '../../components/camera/CameraStage'
import { useCamera } from '../../components/camera/useCamera'
import { useVerificationStream } from '../../components/camera/useVerificationStream'
import { Button } from '../../components/ui/Button'
import { Card, CardBody, CardHeader } from '../../components/ui/Card'
import { Switch } from '../../components/ui/Field'
import { Avatar, PageHeader, Skeleton } from '../../components/ui/Misc'
import { useToast } from '../../components/ui/Toast'
import { api } from '../../lib/api'
import { cn } from '../../lib/cn'
import { spring } from '../../lib/motion'
import type { Employee, FrameFeedback, OrgSettings } from '../../lib/types'

const POSES: Array<{ key: string; label: string; optional?: boolean }> = [
  { key: 'front', label: 'Sample 1' }, { key: 'front_2', label: 'Sample 2' }, { key: 'front_3', label: 'Sample 3' },
  { key: 'left', label: 'Left', optional: true }, { key: 'right', label: 'Right', optional: true },
]
const REQUIRED = POSES.filter((p) => !p.optional).map((p) => p.key)

type Step = 'consent' | 'capture' | 'review' | 'saved'

export default function Enrolment() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()
  const toast = useToast()
  const [step, setStep] = useState<Step>('consent')
  const [consent, setConsent] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<FrameFeedback | null>(null)
  const [saveError, setSaveError] = useState<FrameFeedback | null>(null)

  const emp = useQuery({ queryKey: ['employee', id], queryFn: () => api.get<Employee>(`/employees/${id}`) })
  const org = useQuery({ queryKey: ['settings'], queryFn: () => api.get<OrgSettings>('/settings') })
  const cam = useCamera(step === 'capture' || step === 'review')

  const onTerminal = useCallback((fb: FrameFeedback) => {
    if (fb.state === 'saved') { setSaved(fb); setStep('saved'); setSaving(false); void qc.invalidateQueries({ queryKey: ['employee', id] }); void qc.invalidateQueries({ queryKey: ['employees'] }) }
    else if (fb.state === 'error') { setSaveError(fb); setSaving(false); setStep('review') }
  }, [id, qc])
  const stream = useVerificationStream({ purpose: 'enrolment', employeeId: id, grabFrame: cam.grabFrame, fps: 10, onTerminal })
  const { start: streamStart, phase } = stream

  useEffect(() => {
    if (step === 'capture' && cam.status === 'ready' && phase === 'idle') void streamStart()
  }, [step, cam.status, phase, streamStart])

  const fb = stream.feedback
  const captured = fb?.poses?.captured ?? []
  const requiredDone = fb?.poses?.required_done ?? REQUIRED.every((k) => captured.includes(k))
  const complete = fb?.state === 'complete' || captured.length === POSES.length
  useEffect(() => { if (complete && step === 'capture') setStep('review') }, [complete, step])
  // Instant enrolment: as soon as the three frontal samples are in, save without waiting for optional angles.
  const [autoSave, setAutoSave] = useState(true)
  useEffect(() => {
    if (autoSave && requiredDone && step === 'capture' && !saving && !saveError) { setSaving(true); stream.command({ cmd: 'save' }) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoSave, requiredDone, step])

  const save = () => { setSaving(true); setSaveError(null); stream.command({ cmd: 'save' }) }
  const restart = () => { setSaveError(null); stream.command({ cmd: 'restart' }); setStep('capture') }
  const stageMode: StageMode = step === 'saved' ? 'success' : saveError ? 'failure' : step === 'capture' ? 'scanning' : 'idle'

  if (emp.isLoading) return <Skeleton className="h-64" />
  if (!emp.data) return <p className="text-ink-3">Employee not found.</p>
  const e = emp.data

  return (
    <div>
      <PageHeader eyebrow="Biometric enrolment" title={<span className="flex items-center gap-3"><Avatar name={`${e.first_name} ${e.last_name}`} /> {e.first_name} {e.last_name}</span>}
        description={`${e.employee_code} · ${e.department_name ?? 'No department'}${e.enrolled ? ' · Re-enrolment (previous templates will be superseded)' : ''}`}
        actions={<Link to={`/admin/employees/${id}`}><Button variant="ghost" leftIcon={<ArrowLeft className="size-4" />}>Back to profile</Button></Link>} />

      <div className="grid gap-6 lg:grid-cols-[1.1fr_0.9fr]">
        <CameraStage videoRef={cam.videoRef} status={step === 'consent' ? 'idle' : cam.status} error={cam.error} feedback={step === 'capture' ? fb : null} mode={stageMode} sentSize={stream.sentSize} className="aspect-[4/3]" />

        <div className="space-y-4">
          <Stepper step={step} />
          <AnimatePresence mode="wait">
            {step === 'consent' && (
              <motion.div key="consent" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <Card>
                  <CardHeader title="Biometric privacy notice" description={`Version ${org.data?.consent_version ?? '…'} — must be acknowledged by the employee before capture.`} />
                  <CardBody className="space-y-4 text-sm text-ink-2">
                    <ul className="list-disc space-y-1.5 pl-5">
                      <li>FaceGate converts a few camera images into a numeric facial template. The template cannot be turned back into a photo.</li>
                      <li>Templates are encrypted and stored only on this organisation's own server. They are used solely to record attendance.</li>
                      <li>One small aligned thumbnail may be kept for administrator review; raw images are discarded immediately.</li>
                      <li>The employee may ask an administrator to delete their template at any time; attendance history is retained per company policy.</li>
                    </ul>
                    <Switch checked={consent} onChange={setConsent} label="The employee has read this notice and consents to biometric enrolment" description="Recorded with the enrolment together with your administrator account." />
                    <Switch checked={autoSave} onChange={setAutoSave} label="Instant capture" description="Save automatically the moment three good frontal samples are captured (about one second). Turn off to add optional angles first." />
                    <Button size="lg" className="w-full" disabled={!consent} onClick={() => setStep('capture')} leftIcon={<ShieldCheck className="size-4" />}>Start capture</Button>
                  </CardBody>
                </Card>
              </motion.div>
            )}

            {(step === 'capture' || step === 'review') && (
              <motion.div key="capture" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
                <Card>
                  <CardHeader title={step === 'review' ? 'Capture complete' : requiredDone ? 'Optional extra angles' : 'Look at the camera'} description={step === 'review' ? 'Review the quality below and save the enrolment.' : requiredDone ? 'Three frontal samples are saved. A slight left/right turn improves off-angle recognition — or save now.' : 'Three frontal samples are captured automatically while the employee looks at the camera.'} />
                  <CardBody>
                    <p className="min-h-7 text-lg font-medium" aria-live="polite">
                      {step === 'review' ? 'Ready to save' : stream.error ?? (fb ? (fb.state === 'ok' || fb.state === 'collecting' ? fb.poses?.text : fb.guidance) : 'Starting camera stream…')}
                    </p>
                    <ul className="mt-4 grid grid-cols-5 gap-2">
                      {POSES.map((p) => {
                        const done = captured.includes(p.key)
                        const active = fb?.poses?.target === p.key && !done
                        return (
                          <li key={p.key} className={cn('relative flex flex-col items-center gap-1.5 rounded-lg border p-2 text-xs transition-colors', done ? 'border-accent-300 bg-accent-50 text-accent-700 dark:border-accent-800 dark:bg-accent-800/20 dark:text-accent-300' : active ? 'border-brand-400 bg-brand-50 text-brand-700 dark:bg-brand-800/30 dark:text-brand-100' : 'border-line text-ink-3')}>
                            <PoseGlyph pose={p.key} />
                            <span>{p.label}{p.optional && <span className="block text-[10px] text-ink-3">optional</span>}</span>
                            <AnimatePresence>{done && <motion.span initial={{ scale: 0 }} animate={{ scale: 1 }} transition={spring.snappy} className="absolute -right-1.5 -top-1.5 grid size-5 place-items-center rounded-full bg-accent-500 text-white"><Check className="size-3" /></motion.span>}</AnimatePresence>
                          </li>
                        )
                      })}
                    </ul>
                    <dl className="mt-4 grid grid-cols-3 gap-3 text-sm">
                      <Metric label="Quality" value={fb?.quality != null ? `${Math.round(fb.quality * 100)}%` : '—'} ok={(fb?.quality ?? 0) >= 0.45} />
                      <Metric label="Liveness" value={fb?.liveness ? `${Math.round(fb.liveness.score * 100)}%` : '—'} ok={!!fb?.liveness?.passed} />
                      <Metric label="Head pose" value={fb?.yaw != null ? `${fb.yaw > 0 ? '→' : '←'} ${Math.abs(fb.yaw).toFixed(0)}°` : '—'} ok={!!fb?.pose_ok} />
                    </dl>
                    {saveError && (
                      <div role="alert" className="mt-4 flex gap-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800 dark:border-red-900 dark:bg-red-950/40 dark:text-red-200">
                        <AlertTriangle className="size-5 shrink-0" />
                        <div>
                          <p className="font-medium">{saveError.message}</p>
                          {saveError.reason === 'duplicate_identity' && saveError.detail && <p className="mt-1">Matches <strong>{String(saveError.detail.employee_name ?? saveError.detail.employee_id)}</strong> (similarity {Number(saveError.detail.score).toFixed(2)}). Check whether this person is already enrolled under another record.</p>}
                        </div>
                      </div>
                    )}
                    <div className="mt-5 flex gap-2">
                      <Button size="lg" className="flex-1" disabled={!(step === 'review' || requiredDone) || saving} loading={saving} onClick={save} leftIcon={<Save className="size-4" />}>Save enrolment</Button>
                      <Button size="lg" variant="outline" onClick={restart} leftIcon={<RefreshCw className="size-4" />}>Restart</Button>
                    </div>
                  </CardBody>
                </Card>
              </motion.div>
            )}

            {step === 'saved' && saved && (
              <motion.div key="saved" initial={{ opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }} transition={spring.card}>
                <Card>
                  <CardBody className="pt-6 text-center">
                    <motion.div initial={{ scale: 0.5 }} animate={{ scale: 1 }} transition={spring.snappy} className="mx-auto grid size-14 place-items-center rounded-full bg-accent-500 text-white"><CheckCircle2 className="size-8" /></motion.div>
                    <h3 className="mt-4 text-xl font-semibold">Enrolment saved</h3>
                    <p className="mt-1 text-sm text-ink-3">{saved.template_count} templates · quality {Math.round((saved.quality_score ?? 0) * 100)}% · liveness {Math.round((saved.liveness_score ?? 0) * 100)}%</p>
                    <p className="mt-3 text-sm text-ink-2">{e.first_name} can now check in at the kiosk. Raw images from this session have been discarded.</p>
                    <div className="mt-6 flex justify-center gap-2">
                      <Button onClick={() => navigate(`/admin/employees/${id}`)}>Back to profile</Button>
                      <Button variant="outline" onClick={() => { toast.info('Open the kiosk to test the new enrolment'); navigate('/kiosk') }}>Test at kiosk</Button>
                    </div>
                  </CardBody>
                </Card>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      </div>
    </div>
  )
}

function Stepper({ step }: { step: Step }) {
  const steps: Array<[Step, string]> = [['consent', 'Consent'], ['capture', 'Capture'], ['review', 'Review'], ['saved', 'Saved']]
  const idx = steps.findIndex(([s]) => s === step)
  return (
    <ol className="flex items-center gap-2 text-xs font-medium">
      {steps.map(([s, label], i) => (
        <li key={s} className="flex items-center gap-2">
          <span className={cn('grid size-6 place-items-center rounded-full border', i < idx ? 'border-accent-500 bg-accent-500 text-white' : i === idx ? 'border-brand-600 text-brand-700 dark:text-brand-100' : 'border-line text-ink-3')}>{i < idx ? <Check className="size-3.5" /> : i + 1}</span>
          <span className={cn(i === idx ? 'text-ink' : 'text-ink-3')}>{label}</span>
          {i < steps.length - 1 && <span className="mx-1 h-px w-6 bg-line" />}
        </li>
      ))}
    </ol>
  )
}

function Metric({ label, value, ok }: { label: string; value: string; ok: boolean }) {
  return (
    <div className="rounded-lg border border-line bg-surface-2 px-3 py-2">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className={cn('text-base font-semibold tabular', ok ? 'text-accent-600' : 'text-ink')}>{value}</dd>
    </div>
  )
}

function PoseGlyph({ pose }: { pose: string }) {
  const rot = ({ front: 0, front_2: 0, front_3: 0, left: -1, right: 1 } as Record<string, number>)[pose] ?? 0
  const dy = 0
  return (
    <svg viewBox="0 0 24 24" className="size-7" aria-hidden>
      <ellipse cx="12" cy="11" rx="6" ry="7.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <circle cx={12 + rot * 2.2} cy={10.5 + dy} r="1" fill="currentColor" />
      <circle cx={9 + rot * 1.6} cy={9 + dy * 0.6} r="0.8" fill="currentColor" />
      <circle cx={15 + rot * 1.6} cy={9 + dy * 0.6} r="0.8" fill="currentColor" />
      <path d={`M${10 + rot * 1.5} ${14.5 + dy * 0.8} q2 1.4 4 0`} stroke="currentColor" strokeWidth="1.2" fill="none" strokeLinecap="round" />
    </svg>
  )
}
