import { useEffect, useRef, useState } from 'react'
import type { PaperRecord } from '../../lib/types'

const H = 200
const PAD = { left: 34, right: 14, top: 12, bottom: 18 }
/** Gridlines, in percent. */
const TICKS = [0, 25, 50, 75, 100]
/** Width to draw at before the first measurement lands. */
const MIN_W = 320

/** The chart is drawn at its real pixel size rather than scaled out of a
 * `viewBox`. A viewBox letterboxes when the box it lands in has a different
 * aspect ratio, which moves every point away from where the pointer thinks it
 * is, and it scales the tick labels along with the geometry — 9px type ends up
 * at whatever size the container happens to imply. */
function useMeasuredWidth() {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(0)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])
  return [ref, Math.max(width, MIN_W)] as const
}

function score(a: PaperRecord): string {
  if (a.score_raw === null || a.score_total === null) return '—'
  return `${a.score_raw}/${a.score_total}`
}

/** Roughly what the readout occupies, for keeping it inside the chart. */
const CARD = { halfW: 62, h: 44 }

/** What the pointer is currently over, floated beside the point.
 *
 * It sits above the point, and flips below one that is high enough that the
 * card would otherwise leave the chart — a 96% is exactly the mark a reader
 * wants named, and it is the one nearest the top edge. */
function Readout({
  at,
  of,
  x,
  y,
  W,
}: {
  at: number
  of: PaperRecord
  x: (i: number) => number
  y: (pct: number) => number
  W: number
}) {
  const top = y(of.percentage ?? 0)
  const below = top < CARD.h + PAD.top
  return (
    <div
      className={`pointer-events-none absolute z-10 -translate-x-1/2 rounded-ui border
                  border-hairline bg-panel px-2 py-1 shadow-sm
                  ${below ? '' : '-translate-y-full'}`}
      style={{
        left: Math.min(Math.max(x(at), CARD.halfW), W - CARD.halfW),
        top: below ? top + 10 : top - 10,
      }}
    >
      <div className="text-caption tabular-nums">{of.paper_id}</div>
      <div className="text-micro text-muted tabular-nums">
        {score(of)} · {(of.percentage ?? 0).toFixed(1)}%
      </div>
    </div>
  )
}

/** Percentage over time, oldest first.
 *
 * A plain polyline: the x axis is attempt order rather than real time — the
 * papers are not evenly spaced in time and spacing them that way buries a
 * cluster.
 *
 * The pointer picks the nearest attempt by x alone, so the whole column is a
 * hit target. Per-point hit circles would be 5px wide and would overlap each
 * other once a subject has a dozen attempts.
 */
export function TrendChart({ attempts }: { attempts: PaperRecord[] }) {
  const [box, W] = useMeasuredWidth()
  const [hover, setHover] = useState<number | null>(null)

  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  const x = (i: number) =>
    PAD.left + (attempts.length === 1 ? innerW / 2 : (i / (attempts.length - 1)) * innerW)
  const y = (pct: number) => PAD.top + innerH - (pct / 100) * innerH

  const points = attempts.map((a, i) => `${x(i)},${y(a.percentage ?? 0)}`).join(' ')
  const shown = hover === null ? null : attempts[hover]

  const track = (e: React.MouseEvent<SVGSVGElement>) => {
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left
    let best = 0
    for (let i = 1; i < attempts.length; i++) {
      if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i
    }
    setHover(best)
  }

  return (
    <div ref={box} className="relative w-full">
      <svg
        width={W}
        height={H}
        onMouseMove={track}
        onMouseLeave={() => setHover(null)}
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
              fontSize="10"
              fill="var(--ui-faint)"
            >
              {t}
            </text>
          </g>
        ))}

        {hover !== null && (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={PAD.top + innerH}
            stroke="var(--ui-hairline-strong)"
          />
        )}

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
            r={i === hover ? 4 : 2.5}
            fill="var(--ui-accent)"
          />
        ))}
      </svg>

      {shown && hover !== null && <Readout at={hover} of={shown} x={x} y={y} W={W} />}
    </div>
  )
}
