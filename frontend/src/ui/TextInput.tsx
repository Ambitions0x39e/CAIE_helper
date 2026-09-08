import type { InputHTMLAttributes } from 'react'

/** The app's text box. `onChange` hands over the value, not the event — every
 * caller wants the string.
 *
 * **`selectable` is required, not cosmetic.** The window runs with
 * `text_select=False`, and pywebview implements that by appending
 * `body { user-select: none; cursor: default }` to the head at runtime
 * (webview/js/customize.js). Both properties inherit, so without the override
 * a field shows an arrow cursor and its contents cannot be selected — typing
 * still works, which is exactly what makes it easy to miss. A class beats an
 * inherited declaration whatever order the two sheets land in.
 */
export function TextInput({
  onChange,
  className = 'w-64',
  ...input
}: {
  onChange: (value: string) => void
} & Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange'>) {
  return (
    <input
      {...input}
      onChange={(e) => onChange(e.target.value)}
      className={`selectable rounded-ui border border-hairline bg-raised px-2 py-1.5
                  text-body text-ink placeholder:text-faint ${className}`}
    />
  )
}
