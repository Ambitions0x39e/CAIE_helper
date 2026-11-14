import { useEffect, useRef, useState } from 'react'
import {
  GRADE_LEVELS,
  GRADE_LINES,
  GRADE_TOP,
  type GradePoint,
  type PaperRecord,
  type Trend,
} from '../../lib/types'

const H = 200
const PAD = { left: 24, right: 14, top: 12, bottom: 18 }
/** Width to draw at before the first measurement lands. */
const MIN_W = 320

/** The chart is drawn at its real pixel size rather than scaled out of a
 * `viewBox`. A viewBox letterboxes when the box it lands in has a different
 * aspect ratio, which moves every point away from where the pointer thinks it
 * is, and it scales the labels along with the geometry — 9px type ends up at
 * whatever size the container happens to imply. */
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

/** The fewest papers the verdict is given for; `modules.progress.MIN_PAPERS`. */
const MIN_FOR_PROGRESS = 6

/** The verdict on one component, in a sentence. */
export function ProgressLine({ trend }: { trend: Trend }) {
  const v = trend.progress
  const text =
    v === null
      ? `至少需要 ${MIN_FOR_PROGRESS} 次成绩才能检验进步`
      : `${v.improved ? '有进步' : '看不出进步'}：后 ${v.late} 份` +
        `${v.improved ? '显著高于' : '没有显著高于'}前 ${v.early} 份` +
        `（Wilcoxon 秩和检验，单尾 p = ${v.p.toFixed(3)}）`
  return <div className="text-caption text-muted">{text}</div>
}

function score(a: PaperRecord): string {
  if (a.score_raw === null || a.score_total === null) return '—'
  return `${a.score_raw}/${a.score_total}`
}

/** Roughly what the readout occupies, for keeping it inside the chart. */
const CARD = { halfW: 62, h: 44 + GRADE_LINES.length * 14 }

/** A plotted paper: its record, where it sits on the grade scale, and the
 * boundaries that put it there. */
type Plotted = { record: PaperRecord; position: number; lines: GradePoint['lines'] }

/** What the pointer is currently over, floated beside the point: the score
 * and each of that paper's boundaries, in percent.
 *
 * It sits above the point, and flips below one that is high enough that the
 * card would otherwise leave the chart — a 96% is exactly the mark a reader
 * wants named, and it is the one nearest the top edge. */
function Readout({ left, top, of }: { left: number; top: number; of: Plotted }) {
  const below = top < CARD.h + PAD.top
  return (
    <div
      className={`pointer-events-none absolute z-10 -translate-x-1/2 rounded-ui border
                  border-hairline bg-panel px-2 py-1 shadow-sm
                  ${below ? '' : '-translate-y-full'}`}
      style={{ left, top: below ? top + 10 : top - 10 }}
    >
      <div className="text-caption tabular-nums">{of.record.paper_id}</div>
      <div className="text-micro text-muted tabular-nums">
        {score(of.record)} · {(of.record.percentage ?? 0).toFixed(1)}%
      </div>
      {GRADE_LINES.map((g) => (
        <div key={g} className="flex justify-between gap-3 text-micro text-faint tabular-nums">
          <span>{g}</span>
          <span>{of.lines[g]?.toFixed(1)}%</span>
        </div>
      ))}
    </div>
  )
}

/** Each paper's score against its own A* / A / B / C, oldest first.
 *
 * The y axis is the grade scale, not the percentage: a paper's boundaries
 * move with its difficulty, and here they are the four fixed lines, with the
 * score interpolated inside the band it falls in (`modules.grade_lines`).
 * A paper whose boundaries are not known has no place on it and is left out.
 *
 * The x axis is attempt order rather than real time — the papers are not
 * evenly spaced in time and spacing them that way buries a cluster.
 *
 * The pointer picks the nearest attempt by x alone, so the whole column is a
 * hit target. Per-point hit circles would be 5px wide and would overlap each
 * other once a subject has a dozen attempts.
 */
export function TrendChart({
  attempts,
  points,
}: {
  attempts: PaperRecord[]
  points: Record<string, GradePoint>
}) {
  const [box, W] = useMeasuredWidth()
  const [hover, setHover] = useState<number | null>(null)

  const plotted: Plotted[] = attempts.flatMap((record) => {
    const p = points[record.paper_id]
    return p && p.position !== null
      ? [{ record, position: p.position, lines: p.lines }]
      : []
  })

  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom
  /** C sits on the floor unless a score falls below it. */
  const floor = Math.min(GRADE_LEVELS.C, ...plotted.map((p) => Math.floor(p.position)))

  const x = (i: number) =>
    PAD.left + (plotted.length === 1 ? innerW / 2 : (i / (plotted.length - 1)) * innerW)
  const y = (level: number) =>
    PAD.top + innerH - ((level - floor) / (GRADE_TOP - floor)) * innerH

  const shown = hover === null ? null : plotted[hover]

  const track = (e: React.MouseEvent<SVGSVGElement>) => {
    if (plotted.length === 0) return
    const px = e.clientX - e.currentTarget.getBoundingClientRect().left
    let best = 0
    for (let i = 1; i < plotted.length; i++) {
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
        aria-label="得分趋势"
      >
        {GRADE_LINES.map((g) => (
          <g key={g}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(GRADE_LEVELS[g])}
              y2={y(GRADE_LEVELS[g])}
              stroke="var(--ui-hairline)"
            />
            <text
              x={PAD.left - 6}
              y={y(GRADE_LEVELS[g]) + 3}
              textAnchor="end"
              fontSize="10"
              fill="var(--ui-faint)"
            >
              {g}
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
          points={plotted.map((p, i) => `${x(i)},${y(p.position)}`).join(' ')}
          fill="none"
          stroke="var(--ui-accent)"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        {plotted.map((p, i) => (
          <circle
            key={p.record.paper_id}
            cx={x(i)}
            cy={y(p.position)}
            r={i === hover ? 4 : 2.5}
            fill="var(--ui-accent)"
          />
        ))}
      </svg>

      {shown && hover !== null && (
        <Readout
          left={Math.min(Math.max(x(hover), CARD.halfW), W - CARD.halfW)}
          top={y(shown.position)}
          of={shown}
        />
      )}
    </div>
  )
}
