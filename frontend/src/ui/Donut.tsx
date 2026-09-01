import type { Tally } from '../lib/papers'

/** Ring thickness as a share of the diameter. */
const RING = 0.17

const SLICES = [
  { key: 'earned', varName: '--ui-ok' },
  { key: 'lost', varName: '--ui-bad' },
  { key: 'pending', varName: '--ui-hairline-strong' },
] as const

/** The tally as a ring, drawn with one stroked circle per slice.
 *
 * `stroke-dasharray` + `stroke-dashoffset` rather than arc paths: the slices
 * are shares of one circumference, so they cannot drift apart the way three
 * separately-computed arcs can. An empty tally draws the track only.
 */
export function Donut({
  tally,
  size,
  value,
  label,
}: {
  tally: Tally
  size: number
  value?: string
  label?: string
}) {
  const stroke = size * RING
  const r = (size - stroke) / 2
  const circumference = 2 * Math.PI * r
  const parts = [tally.earned, tally.lost, tally.pending]
  const total = tally.total || 1

  // Dash lengths and their running starts, computed before the map rather than
  // accumulated inside it: the offsets are derived from the tally, not from
  // render order.
  const dashes = parts.map((p) => (p / total) * circumference)
  const starts = dashes.map((_, i) =>
    dashes.slice(0, i).reduce((a, b) => a + b, 0),
  )

  return (
    <div className="relative shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--ui-hairline)"
          strokeWidth={stroke}
        />
        {SLICES.map((slice, i) => (
          <circle
            key={slice.key}
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={`var(${slice.varName})`}
            strokeWidth={stroke}
            strokeDasharray={`${dashes[i]} ${circumference - dashes[i]}`}
            strokeDashoffset={-starts[i]}
            // Start at 12 o'clock rather than 3.
            transform={`rotate(-90 ${size / 2} ${size / 2})`}
          />
        ))}
      </svg>
      {value && (
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span
            className="font-medium tabular-nums leading-none"
            style={{ fontSize: size * 0.22 }}
          >
            {value}
          </span>
          {label && (
            <span className="mt-0.5 text-muted" style={{ fontSize: size * 0.1 }}>
              {label}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
