import type { ReactNode } from 'react'
import { BackButton } from '../../ui/BackButton'

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
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <BackButton onClick={onBack} />
        <div className="text-section font-medium">{title}</div>
      </div>
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
