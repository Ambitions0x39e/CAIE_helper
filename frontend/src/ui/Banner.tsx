import type { ReactNode } from 'react'

type Tone = 'ok' | 'bad' | 'warn'

const BAR: Record<Tone, string> = {
  ok: 'border-l-ok',
  bad: 'border-l-bad',
  warn: 'border-l-warn',
}

/** Colour is carried by a 2px edge, not a tinted fill.
 *
 * A tinted panel would be a fifth surface competing with the ladder; the edge
 * states the same thing without inventing a step. */
export function Banner({
  tone,
  title,
  details,
}: {
  tone: Tone
  title: ReactNode
  details?: readonly string[]
}) {
  return (
    <div
      className={`rounded-ui border border-hairline border-l-2 bg-panel px-3 py-2 ${BAR[tone]}`}
    >
      <div className="text-body">{title}</div>
      {details && details.length > 0 && (
        <ul className="mt-1 space-y-0.5">
          {details.map((d) => (
            <li key={d} className="selectable break-all text-micro text-muted">
              {d}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
