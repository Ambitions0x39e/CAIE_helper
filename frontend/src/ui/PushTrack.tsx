import { AnimatePresence, motion } from 'motion/react'
import type { ReactNode } from 'react'

const variants = {
  enter: (dir: number) => ({ x: dir > 0 ? '100%' : '-100%' }),
  center: { x: 0 },
  exit: (dir: number) => ({ x: dir > 0 ? '-100%' : '100%' }),
}

/** N-step track: the outgoing step leaves the same way the incoming one arrives.
 *
 * Long enough to be read as travel. A push of a hundred-odd milliseconds is
 * over before the eye has followed it, and what lands is a swap — which is the
 * thing the movement exists to avoid. Nothing here touches opacity: the two
 * panes are solid, and one slides off while the other slides on.
 */
export function PushTrack({ step, dir, children }: { step: number; dir: number; children: ReactNode }) {
  return (
    <div className="relative overflow-hidden">
      <AnimatePresence initial={false} custom={dir} mode="popLayout">
        <motion.div
          key={step}
          custom={dir}
          variants={variants}
          initial="enter"
          animate="center"
          exit="exit"
          transition={{ duration: 0.26, ease: [0.32, 0.72, 0, 1] }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
