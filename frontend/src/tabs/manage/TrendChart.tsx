import type { PaperRecord } from '../../lib/types'

const H = 180
const PAD = { left: 34, right: 12, top: 10, bottom: 22 }
/** Gridlines, in percent. */
const TICKS = [0, 25, 50, 75, 100]

/** Percentage over time, oldest first.
 *
 * A plain polyline in an SVG that scales to its box: the x axis is attempt
 * order rather than real time, matching the Flet chart — the papers are not
 * evenly spaced in time and spacing them that way buries a cluster.
 */
export function TrendChart({ attempts }: { attempts: PaperRecord[] }) {
  const W = 640
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  const x = (i: number) =>
    PAD.left + (attempts.length === 1 ? innerW / 2 : (i / (attempts.length - 1)) * innerW)
  const y = (pct: number) => PAD.top + innerH - (pct / 100) * innerH

  const points = attempts.map((a, i) => `${x(i)},${y(a.percentage ?? 0)}`).join(' ')

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label="得分率趋势"
    >
      {TICKS.map((t) => (
        <g key={t}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(t)}
            y2={y(t)}
            stroke="var(--ui-hairline)"
          />
          <text
            x={PAD.left - 6}
            y={y(t) + 3}
            textAnchor="end"
            fontSize="9"
            fill="var(--ui-faint)"
          >
            {t}
          </text>
        </g>
      ))}

      <polyline
        points={points}
        fill="none"
        stroke="var(--ui-accent)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {attempts.map((a, i) => (
        <circle
          key={a.paper_id}
          cx={x(i)}
          cy={y(a.percentage ?? 0)}
          r="2.5"
          fill="var(--ui-accent)"
        >
          <title>
            {a.paper_id} — {a.percentage}%
          </title>
        </circle>
      ))}
    </svg>
  )
}
