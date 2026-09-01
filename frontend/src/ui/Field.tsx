import type { InputHTMLAttributes } from 'react'

/** A labelled text input. `hint` sits under the field as the format reminder.
 *
 * **The inline cursor/user-select is required, not cosmetic.** The window runs
 * with `text_select=False`, and pywebview implements that by appending
 * `body { user-select: none; cursor: default }` to the head at runtime
 * (webview/js/customize.js). Both properties inherit, so without an override
 * here the field shows an arrow cursor and its contents cannot be selected —
 * typing still works, which is exactly what makes it easy to miss. Inline
 * rather than a class so it cannot lose to the injected sheet.
 */
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
        className="mt-1 w-full rounded-ui border border-hairline bg-raised px-2.5 py-1.5
                   text-body text-ink placeholder:text-faint"
        style={{ cursor: 'text', userSelect: 'text' }}
      />
      {hint && <span className="mt-1 block text-micro text-faint">{hint}</span>}
    </label>
  )
}
