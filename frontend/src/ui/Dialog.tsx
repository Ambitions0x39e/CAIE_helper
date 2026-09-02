import { X } from 'lucide-react'
import { type ReactNode, useEffect, useRef } from 'react'

/** A modal, on the native `<dialog>`.
 *
 * `showModal()` already brings the top layer, the backdrop, the focus trap,
 * inertness for everything behind it and Esc-to-close. None of that is worth
 * rebuilding out of a portal and a keydown handler.
 *
 * Not the same thing as `Overlay`: that one grows out of a card to *replace*
 * the view, and the work continues inside it. This interrupts — it says one
 * thing and is dismissed.
 */
export function Dialog({
  open,
  title,
  onClose,
  children,
}: {
  open: boolean
  title: string
  onClose: () => void
  children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    // `open` as a prop, not the `open` attribute: the attribute shows the
    // dialog inline, without the top layer or the backdrop. Only showModal()
    // gives a modal one.
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      // Esc and the backdrop are the two ways out that a reader will try
      // without being told. The target check is what separates a press on the
      // backdrop from one that landed on the card.
      onClick={(e) => e.target === ref.current && onClose()}
      // `m-auto` is what centres it. The UA sheet centres a modal dialog with
      // `inset: 0; margin: auto`, and Tailwind's preflight zeroes the margin on
      // every element — without this it sits in the top-left corner.
      className="m-auto max-w-lg rounded-ui border border-hairline bg-panel p-0 text-ink
                 backdrop:bg-black/25"
      style={{ boxShadow: 'var(--shadow-popover)' }}
    >
      <div className="flex items-center gap-3 border-b border-hairline px-4 py-2.5">
        <span className="flex-1 text-subhead font-semibold">{title}</span>
        <button
          onClick={onClose}
          aria-label="关闭"
          className="flex size-6 shrink-0 items-center justify-center rounded-ui text-faint
                     transition-colors hover:bg-raised hover:text-ink"
          style={{ transitionDuration: 'var(--dur-fast)' }}
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="max-h-[60vh] overflow-y-auto px-4 py-3.5">{children}</div>
    </dialog>
  )
}
