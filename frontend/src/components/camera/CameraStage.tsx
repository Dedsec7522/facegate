import { useEffect, useRef, type ReactNode, type RefObject } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Camera, CameraOff, Loader2 } from 'lucide-react'
import { cn } from '../../lib/cn'
import type { FrameFeedback } from '../../lib/types'
import type { CameraStatus } from './useCamera'

export type StageMode = 'idle' | 'scanning' | 'success' | 'failure' | 'paused'

interface Props {
  videoRef: RefObject<HTMLVideoElement | null>
  status: CameraStatus
  error: string | null
  feedback: FrameFeedback | null
  mode: StageMode
  /** Size of the frame that was sent to the server (so boxes can be scaled back). */
  sentSize: { width: number; height: number } | null
  mirrored?: boolean
  className?: string
  overlay?: ReactNode
}

/**
 * Video + overlay canvas. Draws the detected face frame, a scanning sweep and the colour state.
 * Drawing is done on a canvas sized to the video's rendered box so it stays crisp and cheap.
 */
export function CameraStage({ videoRef, status, error, feedback, mode, sentSize, mirrored = true, className, overlay }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const raf = useRef<number>(0)
  const state = useRef({ feedback, mode, sentSize, t0: performance.now() })
  state.current = { ...state.current, feedback, mode, sentSize }

  useEffect(() => {
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const draw = () => {
      const c = canvasRef.current
      const v = videoRef.current
      if (!c || !v) { raf.current = requestAnimationFrame(draw); return }
      const rect = c.getBoundingClientRect()
      const dpr = Math.min(2, window.devicePixelRatio || 1)
      if (c.width !== Math.round(rect.width * dpr) || c.height !== Math.round(rect.height * dpr)) { c.width = Math.round(rect.width * dpr); c.height = Math.round(rect.height * dpr) }
      const ctx = c.getContext('2d')!
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, rect.width, rect.height)
      const { feedback: fb, mode: m, sentSize: ss } = state.current
      const t = (performance.now() - state.current.t0) / 1000

      // object-fit: cover mapping from sent-frame coordinates to the rendered box.
      const vw = v.videoWidth || ss?.width || 640
      const vh = v.videoHeight || ss?.height || 480
      const scale = Math.max(rect.width / vw, rect.height / vh)
      const ox = (rect.width - vw * scale) / 2
      const oy = (rect.height - vh * scale) / 2
      const sx = ss ? vw / ss.width : 1
      const sy = ss ? vh / ss.height : 1
      const toX = (x: number) => (mirrored ? rect.width - (ox + x * sx * scale) : ox + x * sx * scale)
      const toY = (y: number) => oy + y * sy * scale

      // guide ellipse when nothing is detected
      const colour = m === 'success' ? '#34d399' : m === 'failure' ? '#f87171' : fb?.state === 'ok' || fb?.state === 'collecting' ? '#34d399' : '#e2e8f0'
      if (!fb?.face) {
        ctx.save()
        ctx.strokeStyle = 'rgba(255,255,255,0.35)'
        ctx.setLineDash([6, 8])
        ctx.lineWidth = 1.5
        ctx.beginPath()
        ctx.ellipse(rect.width / 2, rect.height / 2, Math.min(rect.width, rect.height) * 0.22, Math.min(rect.width, rect.height) * 0.3, 0, 0, Math.PI * 2)
        ctx.stroke()
        ctx.restore()
      } else {
        const [bx, by, bw, bh] = fb.face.box
        const x1 = Math.min(toX(bx), toX(bx + bw)), x2 = Math.max(toX(bx), toX(bx + bw))
        const y1 = toY(by), y2 = toY(by + bh)
        const w = x2 - x1, h = y2 - y1
        const r = Math.min(w, h) * 0.18
        ctx.save()
        ctx.strokeStyle = colour
        ctx.lineWidth = 3
        ctx.lineCap = 'round'
        ctx.shadowColor = colour
        ctx.shadowBlur = 12
        const corner = (cx: number, cy: number, dx: number, dy: number) => {
          ctx.beginPath(); ctx.moveTo(cx, cy + dy * r); ctx.lineTo(cx, cy); ctx.lineTo(cx + dx * r, cy); ctx.stroke()
        }
        corner(x1, y1, 1, 1); corner(x2, y1, -1, 1); corner(x1, y2, 1, -1); corner(x2, y2, -1, -1)
        ctx.restore()
        if ((m === 'scanning') && !reduce) {
          const p = (Math.sin(t * 2.2) + 1) / 2
          const yy = y1 + p * h
          const g = ctx.createLinearGradient(x1, yy - 10, x1, yy + 10)
          g.addColorStop(0, 'rgba(52,211,153,0)'); g.addColorStop(0.5, 'rgba(52,211,153,0.75)'); g.addColorStop(1, 'rgba(52,211,153,0)')
          ctx.fillStyle = g
          ctx.fillRect(x1 + 6, yy - 10, w - 12, 20)
        }
        if (fb.face.landmarks && (m === 'scanning')) {
          ctx.fillStyle = 'rgba(255,255,255,0.8)'
          for (const [lx, ly] of fb.face.landmarks) { ctx.beginPath(); ctx.arc(toX(lx), toY(ly), 2.2, 0, Math.PI * 2); ctx.fill() }
        }
      }
      raf.current = requestAnimationFrame(draw)
    }
    raf.current = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf.current)
  }, [videoRef, mirrored])

  return (
    <div className={cn('relative overflow-hidden rounded-2xl bg-black', className)}>
      <video ref={videoRef} playsInline muted autoPlay className={cn('absolute inset-0 size-full object-cover', mirrored && '-scale-x-100', status !== 'ready' && 'opacity-0')} />
      <canvas ref={canvasRef} className="absolute inset-0 size-full" aria-hidden />
      <AnimatePresence>
        {mode === 'success' && <motion.div key="ok" className="pointer-events-none absolute inset-0 ring-4 ring-inset ring-accent-400" initial={{ opacity: 0 }} animate={{ opacity: [0, 1, 0.6] }} exit={{ opacity: 0 }} transition={{ duration: 0.6 }} />}
        {mode === 'failure' && <motion.div key="bad" className="pointer-events-none absolute inset-0 ring-4 ring-inset ring-red-400" initial={{ opacity: 0 }} animate={{ opacity: [0, 1, 0.6] }} exit={{ opacity: 0 }} transition={{ duration: 0.6 }} />}
      </AnimatePresence>
      {status !== 'ready' && (
        <div className="absolute inset-0 grid place-items-center bg-brand-950 text-center text-ink-2">
          <div className="max-w-xs px-6">
            {status === 'requesting' ? <Loader2 className="mx-auto mb-3 size-8 animate-spin text-brand-300" /> : status === 'idle' ? <Camera className="mx-auto mb-3 size-8 text-brand-300" /> : <CameraOff className="mx-auto mb-3 size-8 text-red-400" />}
            <p className="text-sm">{status === 'requesting' ? 'Waiting for camera permission…' : status === 'idle' ? 'Camera is off' : error}</p>
          </div>
        </div>
      )}
      {overlay}
    </div>
  )
}
