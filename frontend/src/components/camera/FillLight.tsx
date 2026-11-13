import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'
import { Sun } from 'lucide-react'
import type { FrameFeedback } from '../../lib/types'

const DARK_FRAMES_TO_SWITCH_ON = 3

/**
 * Low-light assist for a face scan. The server refuses a face that is too dark (it cannot be matched or checked for
 * liveness reliably), which in a dim room left the person stuck on "find better lighting". After a few such frames this
 * turns on, and stays on until the scan ends:
 *   - `cam.boostLowLight()` asks the webcam for more exposure, where the browser and camera allow it;
 *   - the returned flag lets the page show <FillLight>, which turns the screen itself into a lamp.
 * Nothing about the server's checks changes: the frame simply has to become bright enough to pass them.
 */
export function useLowLightAssist(fb: FrameFeedback | null, scanning: boolean, cam?: { boostLowLight: () => Promise<boolean>; resetLowLight: () => void }): boolean {
  const [on, setOn] = useState(false)
  const dark = useRef(0)
  const boostRef = useRef(cam?.boostLowLight)
  const resetRef = useRef(cam?.resetLowLight)
  useEffect(() => { boostRef.current = cam?.boostLowLight; resetRef.current = cam?.resetLowLight })

  useEffect(() => {
    if (!scanning) { dark.current = 0; setOn(false); resetRef.current?.() }
  }, [scanning])

  useEffect(() => {
    if (!scanning || !fb) return
    if (fb.issues?.includes('too_dark')) dark.current += 1
    else if (fb.state !== 'busy' && fb.state !== 'throttled') dark.current = 0
    if (dark.current === DARK_FRAMES_TO_SWITCH_ON) {
      setOn(true)
      void boostRef.current?.()
    }
  }, [fb, scanning])

  return on
}

/**
 * A bright white frame around the whole screen. A laptop or kiosk display at full white is a usable lamp for a face
 * half a metre away. It sits above the page but lets every click through, and announces itself so the sudden light is
 * not a surprise.
 */
export function FillLight({ on }: { on: boolean }) {
  return (
    <AnimatePresence>
      {on && (
        <motion.div
          key="fill-light"
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.35 }}
          className="pointer-events-none fixed inset-0 z-[90]"
          style={{ boxShadow: 'inset 0 0 0 9vmin #fff, inset 0 0 14vmin 9vmin rgba(255,255,255,0.55)' }}
        />
      )}
    </AnimatePresence>
  )
}

/** One line telling the person what the light is for and what to do. Uses ink tokens, so it works in `.theme-dark` too. */
export function FillLightNote({ on, className }: { on: boolean; className?: string }) {
  if (!on) return null
  return (
    <p role="status" className={`flex gap-2 rounded-lg border border-amber-400/50 bg-amber-500/10 px-3 py-2 text-sm text-ink-2 ${className ?? ''}`}>
      <Sun className="mt-0.5 size-4 shrink-0 text-amber-500" />
      <span><strong className="text-amber-500">Screen light is on.</strong> It is dark here, so the screen is lighting your face. Move a little closer to it and face it directly.</span>
    </p>
  )
}
