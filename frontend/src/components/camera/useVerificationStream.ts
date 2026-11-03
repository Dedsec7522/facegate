import { useCallback, useEffect, useRef, useState } from 'react'
import { api, wsUrl } from '../../lib/api'
import type { FrameFeedback, VerifySession } from '../../lib/types'

export type StreamPhase = 'idle' | 'connecting' | 'streaming' | 'done' | 'error'

interface Options {
  purpose: 'attendance' | 'enrolment'
  employeeId?: string
  fps?: number
  grabFrame: (maxSide?: number, quality?: number) => Promise<Blob | null>
  onTerminal?: (fb: FrameFeedback) => void
}

/**
 * Creates a server session, opens the WebSocket, and streams JPEG frames at ~fps while
 * tracking the latest per-frame feedback. Frames are only sent when the previous reply arrived
 * (back-pressure), so a slow server never gets a growing queue.
 */
export function useVerificationStream({ purpose, employeeId, fps = 6, grabFrame, onTerminal }: Options) {
  const [phase, setPhase] = useState<StreamPhase>('idle')
  const [session, setSession] = useState<VerifySession | null>(null)
  const [feedback, setFeedback] = useState<FrameFeedback | null>(null)
  const [sentSize, setSentSize] = useState<{ width: number; height: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const ws = useRef<WebSocket | null>(null)
  const timer = useRef<number>(0)
  const awaiting = useRef(false)
  const onTerminalRef = useRef(onTerminal)
  onTerminalRef.current = onTerminal
  const stats = useRef({ sent: 0, started: 0 })

  const stop = useCallback(() => {
    window.clearInterval(timer.current)
    timer.current = 0
    awaiting.current = false
    ws.current?.close()
    ws.current = null
  }, [])

  const send = useCallback(async () => {
    const sock = ws.current
    if (!sock || sock.readyState !== WebSocket.OPEN || awaiting.current) return
    const blob = await grabFrame(640, 0.8)
    if (!blob || !ws.current || ws.current.readyState !== WebSocket.OPEN) return
    awaiting.current = true
    stats.current.sent++
    sock.send(await blob.arrayBuffer())
  }, [grabFrame])

  const start = useCallback(async () => {
    stop()
    setFeedback(null)
    setError(null)
    setPhase('connecting')
    stats.current = { sent: 0, started: performance.now() }
    try {
      const s = purpose === 'attendance'
        ? await api.post<VerifySession>('/verify/sessions')
        : await api.post<VerifySession>('/verify/enrolment-sessions', undefined, { employee_id: employeeId!, consent: true })
      setSession(s)
      // The server knows the frame size we send (640 max side); the stage needs it to scale boxes.
      const probe = await grabFrame(640, 0.5)
      if (probe) {
        const bmp = await createImageBitmap(probe)
        setSentSize({ width: bmp.width, height: bmp.height })
        bmp.close()
      }
      const sock = new WebSocket(wsUrl(`/verify/${purpose === 'attendance' ? 'stream' : 'enrol-stream'}/${s.session_id}`))
      sock.binaryType = 'arraybuffer'
      ws.current = sock
      sock.onopen = () => {
        sock.send(JSON.stringify({ nonce: s.nonce, token: s.ws_token }))
        setPhase('streaming')
        timer.current = window.setInterval(() => void send(), 1000 / fps)
      }
      sock.onmessage = (ev) => {
        awaiting.current = false
        const fb = JSON.parse(ev.data) as FrameFeedback
        setFeedback(fb)
        if (fb.state === 'identified' || fb.state === 'rejected' || fb.state === 'saved' || (fb.state === 'error' && fb.reason)) {
          window.clearInterval(timer.current)
          setPhase('done')
          onTerminalRef.current?.(fb)
        }
      }
      sock.onerror = () => { setError('Connection to the verification service failed.'); setPhase('error') }
      sock.onclose = (ev) => {
        window.clearInterval(timer.current)
        if (ev.code === 4404) { setError('Verification session expired. Please start again.'); setPhase('error') }
        else if (ev.code === 4403) { setError('Session could not be authenticated.'); setPhase('error') }
        else setPhase((p) => (p === 'done' ? p : p === 'error' ? p : 'idle'))
      }
    } catch (e) {
      setError((e as Error).message)
      setPhase('error')
    }
  }, [purpose, employeeId, grabFrame, send, fps, stop])

  const command = useCallback((cmd: Record<string, unknown>) => {
    ws.current?.send(JSON.stringify(cmd))
  }, [])

  useEffect(() => () => stop(), [stop])

  const elapsedMs = () => (stats.current.started ? performance.now() - stats.current.started : 0)
  return { phase, session, feedback, sentSize, error, start, stop, command, framesSent: () => stats.current.sent, elapsedMs }
}
