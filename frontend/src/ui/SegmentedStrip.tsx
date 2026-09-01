/** A row of mutually exclusive choices — the nav for a tab's sub-views.
 *
 * `disabled` greys a segment out rather than removing it: the Mark tab's steps
 * have to stay visible to read as a sequence even before they are reachable.
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
  return (
    <div className="inline-flex gap-0.5 rounded-ui border border-hairline bg-chrome p-0.5">
      {items.map((item) => {
        const off = disabled?.has(item.id) ?? false
        return (
          <button
            key={item.id}
            onClick={() => onChange(item.id)}
            disabled={off}
            aria-current={item.id === value}
            className={`rounded-[4px] px-2.5 py-1 text-caption transition-colors ${
              off
                ? 'text-faint'
                : item.id === value
                  ? 'bg-raised text-ink shadow-none'
                  : 'text-muted hover:text-ink'
            }`}
            style={{ transitionDuration: 'var(--dur-fast)' }}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
