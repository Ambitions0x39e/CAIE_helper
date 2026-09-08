import * as RS from '@radix-ui/react-select'
import { ChevronDown } from 'lucide-react'

/** The gap between the text and the box around it, in the text's own size, so
 * a field set in caption sits as tightly as one set in body.
 *
 * Sideways it runs wider than 30%: the arrow and its gap already hold the
 * right-hand end open, and a left inset that matches the top and bottom reads
 * as text jammed against the border rather than as a matching margin. Same
 * value on the rows in the popup, so the two columns of text line up. */
const PAD = '0.3em 0.6em'
const PAD_LEFT = '0.6em'

export type Option = { value: string; label: string }

/** One dropdown, drawn by us on both platforms.
 *
 * A native `<select>` is painted by the OS: Windows and macOS disagree on the
 * height, the corner, the arrow and — the part no stylesheet can reach — the
 * popup itself. Radix builds the same widget out of divs and keeps what the
 * native control was worth: keyboard navigation, typeahead, the popup
 * positioned to stay on screen, and the listbox semantics.
 *
 * The label sits above the box, aligned to the same `PAD` inset as the value
 * under it, so the column reads as one edge rather than two.
 */
export function Select({
  label,
  value,
  options,
  onChange,
  placeholder,
  className,
  defaultOpen,
  onOpenChange,
}: {
  label?: string
  value: string
  options: readonly Option[]
  onChange: (value: string) => void
  placeholder?: string
  className?: string
  /** Opens as soon as it mounts — for a picker that replaces the value it is
   * editing, where the click that revealed it was already the request to
   * choose. */
  defaultOpen?: boolean
  onOpenChange?: (open: boolean) => void
}) {
  return (
    <div className={className}>
      {/* The label takes the same inset as the value below it, plus the 1px
          the box's own border takes, so the two texts start on one line. */}
      {label && (
        <span
          className="block text-caption text-muted"
          style={{ paddingLeft: `calc(${PAD_LEFT} + 1px)` }}
        >
          {label}
        </span>
      )}
      <RS.Root
        value={value}
        onValueChange={onChange}
        defaultOpen={defaultOpen}
        onOpenChange={onOpenChange}
      >
        <RS.Trigger
          className={`flex w-full items-center gap-2 rounded-ui border border-hairline
                      bg-raised text-body text-ink transition-colors
                      hover:border-hairline-strong ${label ? 'mt-1' : ''}`}
          style={{ padding: PAD, transitionDuration: 'var(--dur-fast)' }}
        >
          <span className="min-w-0 flex-1 truncate text-left">
            <RS.Value placeholder={placeholder} />
          </span>
          <RS.Icon asChild>
            <ChevronDown className="size-4 shrink-0 text-faint" aria-hidden />
          </RS.Icon>
        </RS.Trigger>

        {/* Portalled to the body, so a picker inside a scroller or a table cell
            is not clipped by it. `popper` is what gives the content the
            trigger's width to match. */}
        <RS.Portal>
          <RS.Content
            position="popper"
            sideOffset={4}
            // No padding of its own, and rows that run the full width: the
            // list sits edge to edge with the closed box, and an option's
            // text starts on the same vertical as the value above it.
            // `overflow-hidden` is what rounds the first and last rows.
            className="pop-in z-50 max-h-[min(18rem,60vh)] w-[var(--radix-select-trigger-width)]
                       overflow-hidden rounded-ui border border-hairline bg-panel text-ink"
            style={{
              boxShadow: 'var(--shadow-popover)',
              // Grows out of the corner nearest the trigger, whichever side
              // Radix ended up putting it on.
              transformOrigin: 'var(--radix-select-content-transform-origin)',
            }}
          >
            <RS.Viewport className="max-h-[inherit] overflow-y-auto">
              {options.map((o) => (
                <RS.Item
                  key={o.value}
                  value={o.value}
                  className="cursor-default text-body outline-none select-none
                             data-[highlighted]:bg-accent/10 data-[state=checked]:text-accent"
                  style={{ padding: PAD }}
                >
                  <RS.ItemText>{o.label}</RS.ItemText>
                </RS.Item>
              ))}
            </RS.Viewport>
          </RS.Content>
        </RS.Portal>
      </RS.Root>
    </div>
  )
}
