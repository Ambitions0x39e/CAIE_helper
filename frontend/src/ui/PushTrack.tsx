import { AnimatePresence, motion } from 'motion/react'
import type { ReactNode } from 'react'

const variants = {
  enter: (dir: number) => ({ x: dir > 0 ? '100%' : '-100%' }),
  center: { x: 0 },
  exit: (dir: number) => ({ x: dir > 0 ? '-100%' : '100%' }),
}

/** N-step track: the outgoing step leaves the same way the incoming one arrives. */
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
          transition={{ duration: 0.12, ease: [0.4, 0, 0.2, 1] }}
        >
          {children}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
