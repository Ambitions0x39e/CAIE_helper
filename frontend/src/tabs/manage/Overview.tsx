import { useMemo, useState } from 'react'
import { subjectGlyph, syllabusIdOf, tally } from '../../lib/papers'
import type { PaperRecord, SyllabusConfig } from '../../lib/types'
import { Donut } from '../../ui/Donut'
import { Glyph } from '../../ui/Glyph'
import { TrendChart } from './TrendChart'

/** A paper's marks over time need at least two points to be a line. */
const MIN_FOR_TREND = 2

function Legend({ t }: { t: ReturnType<typeof tally> }) {
  const rows = [
    { label: '拿到', value: t.earned, color: 'var(--ui-ok)' },
    { label: '丢掉', value: t.lost, color: 'var(--ui-bad)' },
    { label: '未完成', value: t.pending, color: 'var(--ui-hairline-strong)' },
  ]
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-caption">
          <span
            className="size-2 shrink-0 rounded-[2px]"
            style={{ background: r.color }}
          />
          <span className="text-muted">{r.label}</span>
          <span className="ml-auto tabular-nums">
            {r.value.toFixed(r.label === '未完成' ? 0 : 1)}
          </span>
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

  const names = useMemo(
    () => new Map(syllabuses.map((s) => [s.syllabus_id, s.name])),
    [syllabuses],
  )

  /** Papers bucketed by syllabus, biggest bucket first. */
  const bySyllabus = useMemo(() => {
    const groups = new Map<string, PaperRecord[]>()
    for (const p of papers) {
      const id = syllabusIdOf(p.paper_id)
      groups.set(id, [...(groups.get(id) ?? []), p])
    }
    return [...groups.entries()].sort((a, b) => b[1].length - a[1].length)
  }, [papers])

  const overall = tally(papers)

  if (papers.length === 0) {
    return (
      <div className="rounded-ui border border-hairline bg-panel p-6 text-caption text-muted">
        还没有任何卷子。去【下载】拿几份回来。
      </div>
    )
  }

  const detail = open ? bySyllabus.find(([id]) => id === open) : null

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-5 rounded-ui border border-hairline bg-panel p-4">
        <Donut
          tally={overall}
          size={140}
          value={String(overall.total)}
          label="份卷子"
        />
        <div className="min-w-40">
          <Legend t={overall} />
        </div>
      </div>

      <div
        className="grid gap-3"
        style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(16rem, 1fr))' }}
      >
        {bySyllabus.map(([id, records]) => {
          const t = tally(records)
          return (
            <button
              key={id}
              onClick={() => setOpen(open === id ? null : id)}
              aria-expanded={open === id}
              className={`flex items-center gap-3 rounded-ui border border-hairline p-3 text-left
                          transition-colors ${open === id ? 'bg-raised' : 'bg-panel hover:bg-raised'}`}
              style={{ transitionDuration: 'var(--dur-fast)' }}
            >
              <Glyph name={subjectGlyph(names.get(id))} className="size-5 text-muted" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-body font-medium">{names.get(id) ?? id}</div>
                <div className="text-caption text-muted tabular-nums">
                  {id} · {records.length} 份 · 完成 {t.total - t.pending}
                </div>
              </div>
              <Donut tally={t} size={44} />
            </button>
          )
        })}
      </div>

      {detail && (
        <SyllabusDetail
          syllabusId={detail[0]}
          name={names.get(detail[0]) ?? detail[0]}
          records={detail[1]}
          onClose={() => setOpen(null)}
        />
      )}
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
    <div className="rounded-ui border border-hairline bg-raised p-4 space-y-3"
         style={{ boxShadow: 'var(--shadow-popover)' }}>
      <div className="flex items-center gap-3">
        <Donut tally={tally(records)} size={72} />
        <div className="min-w-0 flex-1">
          <div className="text-section font-medium">{name}</div>
          <div className="text-caption text-muted tabular-nums">{syllabusId}</div>
        </div>
        <button onClick={onClose} className="text-caption text-muted hover:text-ink">
          收起
        </button>
      </div>

      {attempts.length >= MIN_FOR_TREND ? (
        <TrendChart attempts={attempts} />
      ) : (
        <div className="text-caption text-faint">
          至少要两份有分数的卷子才画得出趋势。
        </div>
      )}

      <div className="overflow-x-auto rounded-ui border border-hairline">
        <table className="w-full border-collapse text-body">
          <thead>
            <tr className="border-b border-hairline text-caption text-muted">
              <th className="p-2 text-left font-normal">卷号</th>
              <th className="p-2 text-right font-normal">得分</th>
              <th className="p-2 text-right font-normal">满分</th>
              <th className="p-2 text-right font-normal">百分比</th>
              <th className="p-2 text-left font-normal">状态</th>
            </tr>
          </thead>
          <tbody>
            {records.map((r) => (
              <tr key={r.paper_id} className="border-b border-hairline last:border-0">
                <td className="p-2 tabular-nums">{r.paper_id}</td>
                <td className="p-2 text-right tabular-nums">{r.score_raw ?? '–'}</td>
                <td className="p-2 text-right tabular-nums">{r.score_total ?? '–'}</td>
                <td className="p-2 text-right tabular-nums">
                  {r.percentage === null ? '–' : `${r.percentage}%`}
                </td>
                <td className="p-2 text-caption">
                  <span className={r.status === 'Completed' ? 'text-ok' : 'text-muted'}>
                    {r.status === 'Completed' ? '已完成' : '未完成'}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
