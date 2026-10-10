import { AnimatePresence, motion } from 'motion/react'
import { type ButtonHTMLAttributes, useEffect, useRef, useState } from 'react'
import { Button } from './Button'
import { SETTLE_FAST } from './motion'

export type StepState = 'pending' | 'active' | 'done' | 'failed'
export interface Step {
  label: string
  state: StepState
  /** A step made of several things (papers) is drawn as one dot each while it
   * is running and merges into a single dot once it is done. `done` is how
   * many of them have finished; the next one is the one in flight. */
  units?: { done: number; total: number }
}

const DOT: Record<StepState, string> = {
  pending: 'bg-hairline-strong',
  active: 'bg-accent animate-pulse',
  done: 'bg-accent',
  failed: 'bg-bad',
}

/** How a run that has just stopped looks. A run that succeeded finished every
 * step, including the ones that had nothing to do and never reported; one that
 * failed stops at the step it was in, or at the first one it never reached. */
function settle(steps: Step[], failed: boolean): Step[] {
  if (!failed) return steps.map((s) => ({ ...s, state: 'done' }))
  const at = steps.some((s) => s.state === 'active')
    ? steps.map((s) => s.state === 'active')
    : steps.map((s, i) => s.state === 'pending' && steps.findIndex((t) => t.state === 'pending') === i)
  return steps.map((s, i) => (at[i] ? { ...s, state: 'failed' } : s))
}

function Line({ on, hidden }: { on: boolean; hidden: boolean }) {
  return (
    <span
      className={`h-0.5 flex-1 transition-colors ${
        hidden ? 'bg-transparent' : on ? 'bg-accent' : 'bg-hairline-strong'
      }`}
      style={{ transitionDuration: 'var(--dur-base)' }}
    />
  )
}

const MERGE = { opacity: 0, scale: 0.4 }

/** The dot of one step, or — while a step with `units` is running — a dot per
 * unit. */
function Dots({ step }: { step: Step }) {
  const { units } = step
  const split = units !== undefined && step.state === 'active'
  return (
    <div className="relative flex items-center">
      <AnimatePresence initial={false} mode="popLayout">
        <motion.div
          key={split ? 'units' : 'dot'}
          className="flex items-center gap-1.5"
          initial={MERGE}
          animate={{ opacity: 1, scale: 1 }}
          exit={MERGE}
          transition={SETTLE_FAST}
        >
          {split ? (
            Array.from({ length: units.total }, (_, i) => (
              <span
                key={i}
                className={`size-2 shrink-0 rounded-full transition-colors ${
                  DOT[i < units.done ? 'done' : i === units.done ? 'active' : 'pending']
                }`}
                style={{ transitionDuration: 'var(--dur-base)' }}
              />
            ))
          ) : (
            <span
              className={`size-2.5 shrink-0 rounded-full transition-colors ${DOT[step.state]}`}
              style={{ transitionDuration: 'var(--dur-base)' }}
            />
          )}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}

function Track({ steps }: { steps: Step[] }) {
  return (
    <div role="status" aria-live="polite" className="flex w-full items-start">
      {steps.map((s, i) => (
        <div key={i} className="flex min-w-0 flex-1 flex-col items-center gap-1">
          <div className="flex w-full items-center">
            <Line on={steps[i - 1]?.state === 'done'} hidden={i === 0} />
            <Dots step={s} />
            <Line on={s.state === 'done'} hidden={i === steps.length - 1} />
          </div>
          <span
            className={`whitespace-nowrap text-caption tabular-nums ${
              s.state === 'pending' ? 'text-faint' : 'text-muted'
            }`}
          >
            {s.label}
          </span>
        </div>
      ))}
    </div>
  )
}

/** An accent button that, while its job runs, becomes the job's steps: a dot
 * per step joined by a line, grey until the step is done. When the job stops
 * the finished track stays a moment, then the button comes back. */
export function StepButton({
  running,
  steps,
  failed = false,
  ...button
}: {
  running: boolean
  steps: Step[]
  failed?: boolean
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const [lingering, setLingering] = useState<Step[] | null>(null)
  const last = useRef({ steps, failed })
  const was = useRef(false)

  // What the run looked like while it was running: by the render that sees it
  // stopped, the caller has already reset its steps.
  useEffect(() => {
    last.current = { steps: running ? steps : last.current.steps, failed }
  })

  useEffect(() => {
    if (running) {
      was.current = true
      return
    }
    if (!was.current) return
    was.current = false
    setLingering(settle(last.current.steps, last.current.failed))
    const t = setTimeout(() => setLingering(null), 800)
    return () => {
      clearTimeout(t)
      setLingering(null)
    }
  }, [running])

  const shown = running ? steps : lingering
  return (
    <div className={`relative ${shown ? 'w-full' : ''}`}>
      <AnimatePresence initial={false} mode="popLayout">
        <motion.div
          key={shown ? 'track' : 'button'}
          initial={{ opacity: 0, scale: 0.97 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.97 }}
          transition={SETTLE_FAST}
        >
          {shown ? <Track steps={shown} /> : <Button tone="accent" {...button} />}
        </motion.div>
      </AnimatePresence>
    </div>
  )
}
