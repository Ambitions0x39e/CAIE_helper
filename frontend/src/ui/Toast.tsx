import { X } from 'lucide-react'
import { motion } from 'motion/react'
import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { SETTLE_FAST } from './motion'

export interface Note {
  tone: 'ok' | 'bad' | 'warn'
  text: string
}

/** Set by the one mounted host. Module level so any component — any depth, any
 * tab — can say something without threading state down to it. */
let deliver: ((note: Note) => void) | null = null

/** Say one thing, bottom right, and let it take itself away. */
export function notify(tone: Note['tone'], text: string): void {
  deliver?.({ tone, text })
}

/** Mounted once, at the app root. */
export function ToastHost() {
  const [note, setNote] = useState<Note | null>(null)
  useEffect(() => {
    deliver = setNote
    return () => {
      deliver = null
    }
  }, [])
  return <Toast note={note} onDismiss={() => setNote(null)} />
}

const DOT: Record<Note['tone'], string> = {
  ok: 'bg-ok',
  bad: 'bg-bad',
  warn: 'bg-warn',
}

/** How long it sits there before taking itself away. Long enough to read a
 * sentence twice, short enough that it is gone before the next action. */
const LINGER = 4000

/** Outlasts the spring, so the card is not cut off mid-slide. */
const TEARDOWN_MS = 340

/** What just happened, said once and then gone.
 *
 * Floats over the page instead of being appended to it: the result of pressing
 * a button is not a new part of the view, and giving it a slot pushes
 * everything below it down every time an action finishes.
 */
function Toast({ note, onDismiss }: { note: Note | null; onDismiss: () => void }) {
  /** Held past `note` going null so the outgoing text is still there to read
   * while it slides away. */
  const [shown, setShown] = useState(note)
  if (note && note !== shown) setShown(note)

  // Kept in a ref so the timer restarts on a new note and nothing else; an
  // inline arrow from the caller changes identity every render.
  const dismiss = useRef(onDismiss)
  useEffect(() => {
    dismiss.current = onDismiss
  })

  useEffect(() => {
    // Cleared on a clock, not on the slide-out's completion callback — see
    // Overlay for why a frame loop is not something to hang teardown on.
    const timer = setTimeout(() => (note ? dismiss.current() : setShown(null)), note ? LINGER : TEARDOWN_MS)
    return () => clearTimeout(timer)
  }, [note])

  if (!shown || typeof document === 'undefined') return null

  return createPortal(
    <motion.div
      className="pointer-events-none fixed bottom-5 right-5 z-50 flex justify-end"
      initial={{ opacity: 0, y: 8 }}
      animate={note ? { opacity: 1, y: 0 } : { opacity: 0, y: 8 }}
      transition={SETTLE_FAST}
    >
      <div
        className="pointer-events-auto flex max-w-lg items-center gap-2 rounded-ui border
                   border-hairline bg-panel py-1.5 pl-3 pr-1.5 text-body"
        style={{ boxShadow: 'var(--shadow-popover)' }}
      >
        <span className={`size-1.5 shrink-0 rounded-full ${DOT[shown.tone]}`} />
        <span className="min-w-0 truncate">{shown.text}</span>
        <button
          onClick={() => dismiss.current()}
          aria-label="关闭"
          className="flex size-5 shrink-0 items-center justify-center rounded-full text-faint
                     transition-colors hover:bg-raised hover:text-ink"
          style={{ transitionDuration: 'var(--dur-fast)' }}
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>
    </motion.div>,
    document.body,
  )
}
