import { motion } from 'motion/react'
import { useId } from 'react'
import { SETTLE_FAST } from './motion'

/** A row of mutually exclusive choices — the nav for a tab's sub-views.
 *
 * `disabled` greys a segment out rather than removing it: the Mark tab's steps
 * have to stay visible to read as a sequence even before they are reachable.
 *
 * The highlight is one element that travels between the segments rather than a
 * background switched on and off, so the eye is carried from the choice it had
 * to the one it now has. `layoutId` is what moves it: motion measures the
 * element in its old position and its new one and animates the difference, so
 * nothing here has to know where the segments are. The id is per-instance —
 * two strips on one screen share a layout id otherwise, and the highlight
 * flies across the row from one to the other.
 */
export function SegmentedStrip<T extends string>({
  items,
  value,
  onChange,
  disabled,
}: {
  items: readonly { id: T; label: string }[]
  value: T
  onChange: (id: T) => void
  disabled?: ReadonlySet<T>
}) {
  const strip = useId()
  return (
    <div className="inline-flex gap-0.5 rounded-ui border border-hairline bg-chrome p-0.5">
      {items.map((item) => {
        const off = disabled?.has(item.id) ?? false
        const on = item.id === value
        return (
          <button
            key={item.id}
            onClick={() => onChange(item.id)}
            disabled={off}
            aria-current={on}
            className={`relative rounded-[4px] px-2.5 py-1 text-caption transition-colors ${
              off ? 'text-faint' : on ? 'text-ink' : 'text-muted hover:text-ink'
            }`}
            style={{ transitionDuration: 'var(--dur-fast)' }}
          >
            {on && (
              <motion.span
                layoutId={strip}
                transition={SETTLE_FAST}
                className="absolute inset-0 rounded-[4px] bg-raised"
              />
            )}
            {/* Above the highlight, which is painted over the button's own
                background box. */}
            <span className="relative">{item.label}</span>
          </button>
        )
      })}
    </div>
  )
}
