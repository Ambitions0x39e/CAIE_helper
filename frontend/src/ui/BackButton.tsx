import { ArrowLeft } from 'lucide-react'

/** The way back out of a sub-page or a detail panel.
 *
 * An arrow and nothing else. The word beside it was naming the place it
 * returns to, which is the one thing the user already knows — they were just
 * there. */
export function BackButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      aria-label="返回"
      title="返回"
      className="flex size-7 shrink-0 items-center justify-center rounded-ui text-muted
                 transition-colors hover:bg-raised hover:text-ink"
      style={{ transitionDuration: 'var(--dur-fast)' }}
    >
      <ArrowLeft className="size-4" aria-hidden />
    </button>
  )
}
