import { motion } from 'motion/react'
import { type ReactNode, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { SETTLE } from './motion'

/** The element in App's layout that overlays are portalled into. It is a
 * sibling of the scrolling content and pinned to the viewport region, which is
 * what lets a panel cover the whole content area instead of being appended to
 * the bottom of a list that may be metres long. */
export const OVERLAY_ROOT = 'overlay-root'

/** The panel is already laid out at full size; only the window onto it moves.
 * Matching the card's own corner is what makes the first frame read as the
 * card rather than as a new surface appearing on top of it. */
const CORNER = 7

/** Fraction of the content area the fallback origin covers, for a caller with
 * no element to grow from. */
const CENTRED = 0.7

/** Must outlast the spring, or the panel is yanked off the screen partway
 * through shrinking. */
const TEARDOWN_MS = 460

/** `clip-path` insets that show only `rect` of the host.
 *
 * Both ends must have identical structure — same function, same count of
 * lengths, same units — or there is nothing to interpolate between and the
 * clip snaps instead of growing. */
function clipTo(rect: DOMRect, host: DOMRect): string {
  const top = Math.max(0, rect.top - host.top)
  const left = Math.max(0, rect.left - host.left)
  const bottom = Math.max(0, host.bottom - rect.bottom)
  const right = Math.max(0, host.right - rect.right)
  return `inset(${top}px ${right}px ${bottom}px ${left}px round ${CORNER}px)`
}

const OPEN_CLIP = `inset(0px 0px 0px 0px round 0px)`

/** A panel covering the whole content area, growing out of the thing that
 * opened it.
 *
 * Rendered through a portal rather than in place: the caller is inside the
 * scroller, and an overlay declared there would scroll away with the rows
 * behind it. `AnimatePresence` cannot drive that portal — `isValidElement` is
 * false for one, so it drops the child and nothing renders — so the exit is
 * held here instead: the panel stays mounted until it has finished shrinking
 * back into the rectangle it came out of.
 */
export function Overlay({
  open,
  origin,
  onClose,
  children,
}: {
  open: boolean
  /** Where it grows from — the bounding rect of the element that was clicked.
   * Omitted, it grows from the middle of the content area. */
  origin?: DOMRect | null
  onClose: () => void
  children: ReactNode
}) {
  /** Stays true through the close so the panel is still there to shrink. */
  const [mounted, setMounted] = useState(open)
  if (open && !mounted) setMounted(true)

  // Torn down on a clock rather than on the animation's completion callback.
  // The panel is opaque and covers the whole content area, so a frame loop
  // that never reports back — a throttled tab, a window that is not
  // compositing — would leave an invisible sheet swallowing every click.
  // A timer ends it whether or not the animation ever ran.
  useEffect(() => {
    if (open) return
    const timer = setTimeout(() => setMounted(false), TEARDOWN_MS)
    return () => clearTimeout(timer)
  }, [open])

  const host = typeof document === 'undefined' ? null : document.getElementById(OVERLAY_ROOT)
  if (!host || !mounted) return null

  // `origin` outlives the close — the caller sets it when the panel opens and
  // leaves it there — so the same rectangle drives both directions and the
  // panel shrinks back into the thing it came out of.
  const bounds = host.getBoundingClientRect()
  const closed = clipTo(
    origin ??
      new DOMRect(
        bounds.left + (bounds.width * (1 - CENTRED)) / 2,
        bounds.top + (bounds.height * (1 - CENTRED)) / 2,
        bounds.width * CENTRED,
        bounds.height * CENTRED,
      ),
    bounds,
  )

  return createPortal(
    <motion.div
      className="pointer-events-auto absolute inset-0 overflow-y-auto bg-page px-7 py-6"
      initial={{ clipPath: closed, opacity: 0 }}
      animate={
        open ? { clipPath: OPEN_CLIP, opacity: 1 } : { clipPath: closed, opacity: 0 }
      }
      transition={SETTLE}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      tabIndex={-1}
    >
      {children}
    </motion.div>,
    host,
  )
}
