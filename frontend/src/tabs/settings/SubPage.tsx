import { ChevronLeft } from 'lucide-react'
import type { ReactNode } from 'react'

/** The frame every settings sub-page shares: a back row, then the content. */
export function SubPage({
  title,
  onBack,
  children,
}: {
  title: string
  onBack: () => void
  children: ReactNode
}) {
  return (
    <div className="space-y-3">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-caption text-muted hover:text-ink"
      >
        <ChevronLeft className="size-3.5" aria-hidden />
        设置
      </button>
      <div className="text-section font-medium">{title}</div>
      {children}
    </div>
  )
}

/** A labelled control in the settings' two-column row form. */
export function Row({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-hairline p-3 last:border-0">
      <div className="min-w-40 flex-1">
        <div className="text-body">{label}</div>
        {hint && <div className="text-caption text-muted">{hint}</div>}
      </div>
      <div className="shrink-0">{children}</div>
    </div>
  )
}

export function TextInput({
  value,
  onChange,
  type = 'text',
  placeholder,
  width = 'w-64',
}: {
  value: string
  onChange: (v: string) => void
  type?: 'text' | 'password'
  placeholder?: string
  width?: string
}) {
  return (
    <input
      type={type}
      value={value}
      placeholder={placeholder}
      onChange={(e) => onChange(e.target.value)}
      className={`${width} rounded-ui border border-hairline bg-raised px-2 py-1.5 text-body text-ink placeholder:text-faint`}
      // Required: the window runs text_select=False, which pywebview applies as
      // an inherited rule on body. See ui/Field.tsx.
      style={{ cursor: 'text', userSelect: 'text' }}
    />
  )
}
