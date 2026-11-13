import { useCallback, useEffect, useRef, useState } from 'react'

export type CameraStatus = 'idle' | 'requesting' | 'ready' | 'denied' | 'unavailable' | 'error'

/** Owns a getUserMedia stream and can grab downscaled JPEG frames for the verification stream. */
export function useCamera(active: boolean, opts: { width?: number; height?: number; facingMode?: 'user' | 'environment' } = {}) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [status, setStatus] = useState<CameraStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [size, setSize] = useState({ width: 0, height: 0 })

  const restoreRef = useRef<(() => void) | null>(null)

  /** Undo `boostLowLight`. Webcam drivers remember exposure and brightness, so they are put back after every scan. */
  const resetLowLight = useCallback(() => {
    restoreRef.current?.()
    restoreRef.current = null
  }, [])

  /**
   * Ask the webcam for a brighter picture: continuous auto-exposure, then exposure compensation and brightness raised
   * most of the way to what the camera reports as its maximum. Only Chromium exposes these controls and only some
   * cameras support them; returns false when nothing could be changed.
   */
  const boostLowLight = useCallback(async (): Promise<boolean> => {
    const track = streamRef.current?.getVideoTracks()[0]
    if (!track || typeof track.getCapabilities !== 'function' || restoreRef.current) return false
    type Range = { min: number; max: number }
    const caps = track.getCapabilities() as MediaTrackCapabilities & { exposureCompensation?: Range; brightness?: Range; exposureMode?: string[] }
    const now = track.getSettings() as MediaTrackSettings & { exposureCompensation?: number; brightness?: number }
    const want: Record<string, unknown> = {}
    const back: Record<string, unknown> = {}
    if (caps.exposureMode?.includes('continuous')) want.exposureMode = 'continuous'
    for (const k of ['exposureCompensation', 'brightness'] as const) {
      const range = caps[k]
      const cur = now[k]
      if (range && typeof cur === 'number' && range.max > cur) { want[k] = cur + (range.max - cur) * 0.7; back[k] = cur }
    }
    if (!Object.keys(want).length) return false
    try { await track.applyConstraints({ advanced: [want] } as MediaTrackConstraints) } catch { return false }
    restoreRef.current = () => {
      if (Object.keys(back).length && track.readyState === 'live') void track.applyConstraints({ advanced: [back] } as MediaTrackConstraints).catch(() => undefined)
    }
    return true
  }, [])

  const stop = useCallback(() => {
    resetLowLight()
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setStatus('idle')
  }, [resetLowLight])

  useEffect(() => {
    if (!active) { stop(); return }
    let cancelled = false
    const start = async () => {
      if (!navigator.mediaDevices?.getUserMedia) { setStatus('unavailable'); setError('This browser does not support camera access.'); return }
      setStatus('requesting')
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: opts.width ?? 1280 }, height: { ideal: opts.height ?? 720 }, facingMode: opts.facingMode ?? 'user' },
          audio: false,
        })
        if (cancelled) { stream.getTracks().forEach((t) => t.stop()); return }
        streamRef.current = stream
        const v = videoRef.current
        if (v) {
          v.srcObject = stream
          await v.play().catch(() => undefined)
          const settle = () => setSize({ width: v.videoWidth, height: v.videoHeight })
          if (v.videoWidth) settle(); else v.onloadedmetadata = settle
        }
        setStatus('ready')
        setError(null)
      } catch (e) {
        const err = e as DOMException
        if (err.name === 'NotAllowedError' || err.name === 'SecurityError') { setStatus('denied'); setError('Camera permission was denied. Allow camera access in your browser and try again.') }
        else if (err.name === 'NotFoundError' || err.name === 'OverconstrainedError') { setStatus('unavailable'); setError('No camera was found on this device.') }
        else { setStatus('error'); setError(err.message || 'Could not start the camera.') }
      }
    }
    void start()
    return () => { cancelled = true; stop() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, opts.facingMode, stop])

  /** Returns a JPEG blob of the current frame, downscaled so the longest side is `maxSide`. */
  const grabFrame = useCallback(async (maxSide = 640, quality = 0.8): Promise<Blob | null> => {
    const v = videoRef.current
    if (!v || !v.videoWidth) return null
    const c = (canvasRef.current ??= document.createElement('canvas'))
    const s = Math.min(1, maxSide / Math.max(v.videoWidth, v.videoHeight))
    c.width = Math.round(v.videoWidth * s)
    c.height = Math.round(v.videoHeight * s)
    const ctx = c.getContext('2d')
    if (!ctx) return null
    ctx.drawImage(v, 0, 0, c.width, c.height)
    return new Promise((res) => c.toBlob(res, 'image/jpeg', quality))
  }, [])

  return { videoRef, status, error, size, grabFrame, stop, boostLowLight, resetLowLight }
}
