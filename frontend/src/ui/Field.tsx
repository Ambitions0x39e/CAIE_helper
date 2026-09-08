import type { InputHTMLAttributes } from 'react'

/** A labelled text input, with the label above and an optional `hint` under it.
 *
 * Roomier padding than the bare `TextInput`: this one stands alone in a form
 * column rather than sitting at the end of a settings row. */
export function Field({
  label,
  hint,
  ...input
}: { label: string; hint?: string } & InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block">
      <span className="block text-caption text-muted">{label}</span>
      <input
        {...input}
        className="selectable mt-1 w-full rounded-ui border border-hairline bg-raised
                   px-2.5 py-1.5 text-body text-ink placeholder:text-faint"
      />
      {hint && <span className="mt-1 block text-micro text-faint">{hint}</span>}
    </label>
  )
}
