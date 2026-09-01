import { motion } from 'motion/react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

/** The element in App's layout that overlays are portalled into. It is a
 * sibling of the scrolling content and pinned to the viewport region, which is
 * what lets a panel cover the whole content area instead of being appended to
 * the bottom of a list that may be metres long. */
export const OVERLAY_ROOT = 'overlay-root'

/** Scale a panel grows from. Not 0 — coming up from a point reads as a new
 * thing appearing, coming up from nine tenths reads as the row you clicked
 * opening out. */
const REST_SCALE = 0.94

/** A panel covering the whole content area.
 *
 * Rendered through a portal rather than in place: the caller is inside the
 * scroller, and an overlay declared there would scroll away with the rows
 * behind it.
 *
 * It grows in and cuts out. Both halves were tried: AnimatePresence *around*
 * the portal never renders, because `isValidElement` is false for a portal and
 * AnimatePresence drops children it cannot key; AnimatePresence *inside* the
 * portal ran the exit but never unmounted the node, leaving an invisible sheet
 * over the page that swallowed every click. Closing on the spot is what a back
 * navigation does anyway.
 */
export function Overlay({
  open,
  onClose,
  children,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
}) {
  const host = typeof document === 'undefined' ? null : document.getElementById(OVERLAY_ROOT)
  if (!host || !open) return null

  return createPortal(
    <motion.div
      className="pointer-events-auto absolute inset-0 overflow-y-auto bg-page p-5"
      initial={{ opacity: 0, scale: REST_SCALE }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.13, ease: [0.4, 0, 0.2, 1] }}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      tabIndex={-1}
    >
      {children}
    </motion.div>,
    host,
  )
}
