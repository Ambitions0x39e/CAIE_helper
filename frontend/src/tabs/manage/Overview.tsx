import { useMemo, useState } from 'react'
import { subjectGlyph, syllabusIdOf, tally } from '../../lib/papers'
import type { PaperRecord, SyllabusConfig } from '../../lib/types'
import { BackButton } from '../../ui/BackButton'
import { Donut } from '../../ui/Donut'
import { Glyph } from '../../ui/Glyph'
import { Overlay } from '../../ui/Overlay'
import { TrendChart } from './TrendChart'

/** A paper's marks over time need at least two points to be a line. */
const MIN_FOR_TREND = 2

/** The three ring sizes: the overall one, a card's, and the panel header's. */
const DONUT_BIG = 168
const DONUT_SMALL = 68
const DONUT_PANEL = 96

function pct(value: number): string {
  return `${value.toFixed(1)}%`
}

/** A label and its number on one line — the card's and the summary's stats. */
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-caption text-muted">{label}</span>
      <span className="text-subhead font-semibold tabular-nums">{value}</span>
    </div>
  )
}

function Legend({ t }: { t: ReturnType<typeof tally> }) {
  const done = Math.round(t.earned + t.lost)
  const earnedRate = done ? (t.earned / done) * 100 : 0
  const rows = [
    { label: '得分', value: `${done} 张 · ${pct(earnedRate)}`, color: 'var(--ui-ok)' },
    { label: '失分', value: pct(100 - earnedRate), color: 'var(--ui-bad)' },
    { label: '未完成', value: `${t.pending} 张`, color: 'var(--ui-hairline-strong)' },
  ]
  return (
    <div className="space-y-2">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-caption">
          <span
            className="size-2.5 shrink-0 rounded-full"
            style={{ background: r.color }}
          />
          <span>{r.label}</span>
          <span className="text-muted tabular-nums">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

export function Overview({
  papers,
  syllabuses,
}: {
  papers: PaperRecord[]
  syllabuses: SyllabusConfig[]
}) {
  const [open, setOpen] = useState<string | null>(null)
  /** The card the panel grows out of. */
  const [origin, setOrigin] = useState<DOMRect | null>(null)

  const names = useMemo(
    () => new Map(syllabuses.map((s) => [s.syllabus_id, s.name])),
    [syllabuses],
  )

  /** Papers bucketed by syllabus, by code — the order the cards are read in
   * should not shuffle when one subject overtakes another. */
  const bySyllabus = useMemo(() => {
    const groups = new Map<string, PaperRecord[]>()
    for (const p of papers) {
      const id = syllabusIdOf(p.paper_id)
      groups.set(id, [...(groups.get(id) ?? []), p])
    }
    return [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [papers])

  const overall = tally(papers)
  const completed = papers
    .filter((p) => p.status === 'Completed' && p.percentage !== null)
    .map((p) => p.percentage as number)

  if (papers.length === 0) {
    return <div className="text-section text-muted">暂无记录，请先下载试卷。</div>
  }

  const detail = open ? bySyllabus.find(([id]) => id === open) : null

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-5 rounded-ui border border-hairline bg-panel p-5">
        <Donut
          tally={overall}
          size={DONUT_BIG}
          value={String(overall.total)}
          label="总体"
        />
        <Legend t={overall} />
        <div className="ml-auto space-y-2 text-right">
          <Stat
            label="平均"
            value={
              completed.length
                ? pct(completed.reduce((a, b) => a + b, 0) / completed.length)
                : '—'
            }
          />
          <Stat label="最高" value={completed.length ? pct(Math.max(...completed)) : '—'} />
          <Stat label="学科" value={`${bySyllabus.length} 门`} />
        </div>
      </div>

      {/* Two across on a normal window — a card carries three stats beside its
          ring, and squeezing a third column shortens every one of them. */}
      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(24rem, 1fr))' }}
      >
        {bySyllabus.map(([id, records]) => {
          const t = tally(records)
          const marks = records
            .filter((r) => r.status === 'Completed' && r.percentage !== null)
            .map((r) => r.percentage as number)
          return (
            <button
              key={id}
              onClick={(e) => {
                setOrigin(e.currentTarget.getBoundingClientRect())
                setOpen(open === id ? null : id)
              }}
              aria-expanded={open === id}
              className={`flex items-center gap-4 rounded-ui border border-hairline p-5 text-left
                          transition-colors ${open === id ? 'bg-raised' : 'bg-panel hover:bg-raised'}`}
              style={{ transitionDuration: 'var(--dur-fast)' }}
            >
              <div className="min-w-0 flex-1 space-y-1">
                <div className="flex items-center gap-2">
                  <Glyph name={subjectGlyph(names.get(id))} className="size-5 text-accent" />
                  <span className="text-section font-bold tabular-nums">{id}</span>
                </div>
                <div className="truncate text-caption text-muted">{names.get(id) ?? ''}</div>
                <div className="h-1" />
                <Stat label="最近" value={marks.length ? pct(marks[marks.length - 1]) : '—'} />
                <Stat label="最佳" value={marks.length ? pct(Math.max(...marks)) : '—'} />
                <Stat label="共" value={`${records.length} 张`} />
              </div>
              <Donut tally={t} size={DONUT_SMALL} />
            </button>
          )
        })}
      </div>

      <Overlay open={detail !== null} origin={origin} onClose={() => setOpen(null)}>
        {detail && (
          <SyllabusDetail
            syllabusId={detail[0]}
            name={names.get(detail[0]) ?? detail[0]}
            records={detail[1]}
            onClose={() => setOpen(null)}
          />
        )}
      </Overlay>
    </div>
  )
}

function SyllabusDetail({
  syllabusId,
  name,
  records,
  onClose,
}: {
  syllabusId: string
  name: string
  records: PaperRecord[]
  onClose: () => void
}) {
  /** Completed papers oldest first; undated last, since a row written before
   * the timestamp column existed has none. */
  const attempts = useMemo(
    () =>
      records
        .filter((r) => r.percentage !== null)
        .sort((a, b) => {
          if (!a.timestamp) return 1
          if (!b.timestamp) return -1
          return a.timestamp.localeCompare(b.timestamp)
        }),
    [records],
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <BackButton onClick={onClose} />
        <div className="min-w-0 flex-1">
          <div className="text-section font-bold">
            {syllabusId} — {name}
          </div>
        </div>
        <Donut
          tally={tally(records)}
          size={DONUT_PANEL}
          value={String(records.length)}
          label="张"
        />
      </div>

      {attempts.length >= MIN_FOR_TREND ? (
        <TrendChart attempts={attempts} />
      ) : (
        <div className="text-caption italic text-muted">
          至少需要 2 次成绩才能绘制趋势图
        </div>
      )}

      <div className="overflow-x-auto rounded-ui border border-hairline">
        <table className="w-full border-collapse text-body">
          <thead>
            <tr className="border-b border-hairline text-caption text-muted">
              <th className="p-2.5 text-left font-normal">Paper ID</th>
              <th className="p-2.5 text-right font-normal">Raw</th>
              <th className="p-2.5 text-right font-normal">Total</th>
              <th className="p-2.5 text-right font-normal">%</th>
              <th className="p-2.5 text-left font-normal">Date</th>
            </tr>
          </thead>
          <tbody>
            {attempts.map((r) => (
              <tr key={r.paper_id} className="border-b border-hairline last:border-0">
                <td className="p-2.5 tabular-nums">{r.paper_id}</td>
                <td className="p-2.5 text-right tabular-nums">{r.score_raw}</td>
                <td className="p-2.5 text-right tabular-nums">{r.score_total}</td>
                <td className="p-2.5 text-right tabular-nums">{pct(r.percentage ?? 0)}</td>
                <td className="p-2 text-caption text-muted tabular-nums">
                  {r.timestamp ? r.timestamp.slice(0, 16).replace('T', ' ') : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
