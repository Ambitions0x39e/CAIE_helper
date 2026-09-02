import { AnimatePresence, motion } from 'motion/react'
import type { ReactNode } from 'react'
import { SETTLE } from './motion'

const variants = {
  enter: (dir: number) => ({ x: dir > 0 ? '100%' : '-100%' }),
  center: { x: 0 },
  exit: (dir: number) => ({ x: dir > 0 ? '-100%' : '100%' }),
}

/** N-step track: the outgoing step leaves the same way the incoming one arrives.
 *
 * The pair is symmetric on purpose — a pane that enters from the right leaves
 * to the right when you go back, so the direction you travelled is the
 * direction you can return along.
 *
 * Nothing here touches opacity: the two panes are solid, and one slides off
 * while the other slides on. A cross-fade would put them on top of each other
 * and say nothing about which way you moved.
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
          transition={SETTLE}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
