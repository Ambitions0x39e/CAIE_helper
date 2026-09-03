import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import type { MistakeRecord } from '../../lib/types'
import { notify } from '../../ui/Toast'
import { Button } from '../../ui/Button'
import { SegmentedStrip } from '../../ui/SegmentedStrip'

const VIEWS = [
  { id: 'paper', label: '按卷' },
  { id: 'topic', label: '按 topic' },
] as const
type ViewId = (typeof VIEWS)[number]['id']

/** Matches `modules.marking.mistakes._KEY_SEP`. */
const KEY_SEP = ' · '
const UNCLASSIFIED = '未分类'

function subjectIdOf(paperId: string): string {
  return paperId.includes('_') ? paperId.split('_')[0] : paperId
}

/** The filter key one record belongs to: `9701 · Equilibria`. */
function topicKey(r: MistakeRecord): string {
  return `${subjectIdOf(r.paper_id)}${KEY_SEP}${r.topic_name || UNCLASSIFIED}`
}

/** Re-file one mistake under a different topic.
 *
 * The options come from the same paper→topics mapping the grader was given, so
 * a hand-picked tag reads identically to one the model produced. A paper whose
 * syllabus has no topics (a practical, say) gets no picker rather than an empty
 * one — `topics_for` returns null, not `{}`, for exactly that case.
 */
function TopicPicker({
  record,
  onDone,
}: {
  record: MistakeRecord
  onDone: () => void
}) {
  const [topics, setTopics] = useState<Record<string, string> | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    api()
      .then((a) => a.topics_for(record.paper_id))
      .then(setTopics)
      .catch(() => setTopics(null))
  }, [open, record.paper_id])

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-left text-muted hover:text-ink"
        title="改 topic"
      >
        {record.topic_name ?? UNCLASSIFIED}
      </button>
    )
  }

  if (topics === null) {
    return <span className="text-caption text-faint">这份卷子没有可选 topic</span>
  }

  return (
    <select
      autoFocus
      className="rounded-ui border border-hairline bg-panel px-1.5 py-0.5 text-caption text-ink"
      value={record.topic_id ?? ''}
      onChange={async (e) => {
        const value = e.target.value || null
        setOpen(false)
        await (await api()).retag_mistake(record.paper_id, record.question_id, value)
        onDone()
      }}
      onBlur={() => setOpen(false)}
    >
      <option value="">{UNCLASSIFIED}</option>
      {Object.entries(topics).map(([id, name]) => (
        <option key={id} value={id}>
          {name}
        </option>
      ))}
    </select>
  )
}

export function Mistakes() {
  const [records, setRecords] = useState<MistakeRecord[] | null>(null)
  const [view, setView] = useState<ViewId>('paper')
  const [keys, setKeys] = useState<ReadonlySet<string>>(new Set())
  const [openGroups, setOpenGroups] = useState<ReadonlySet<string>>(new Set())
  /** Ticked rows, as positions in `records`. The store is append-only, so a
   * position is stable; paper+question is not, because a re-grade repeats it. */
  const [picked, setPicked] = useState<ReadonlySet<number>>(new Set())

  const load = () =>
    api()
      .then((a) => a.mistakes())
      .then(setRecords)
      .catch(() => setRecords([]))

  useEffect(() => {
    load()
  }, [])

  /** Every key present, sorted, with 未分类 last — it is a leftover bucket
   * rather than a topic, so it sits at the end instead of wherever collation
   * would put it. */
  const allKeys = useMemo(() => {
    const set = new Set((records ?? []).map(topicKey))
    return [...set].sort((a, b) => {
      const au = a.endsWith(UNCLASSIFIED)
      const bu = b.endsWith(UNCLASSIFIED)
      if (au !== bu) return au ? 1 : -1
      return a.localeCompare(b)
    })
  }, [records])

  /** An empty selection means "no filter", not "show nothing". Rows travel as
   * their store position so a checkbox stays bound to one row through every
   * regrouping. */
  const filtered = useMemo(() => {
    const all = (records ?? []).map((r, i) => [i, r] as const)
    return keys.size === 0 ? all : all.filter(([, r]) => keys.has(topicKey(r)))
  }, [records, keys])

  /** Papers in first-seen order — the store is append-only, so that is
   * chronological and the newest paper stays where the user left it. */
  const groups = useMemo(() => {
    const out = new Map<string, (readonly [number, MistakeRecord])[]>()
    for (const entry of filtered) {
      const k = view === 'paper' ? entry[1].paper_id : topicKey(entry[1])
      out.set(k, [...(out.get(k) ?? []), entry])
    }
    return [...out.entries()]
  }, [filtered, view])

  const toggleKey = (k: string) => {
    const next = new Set(keys)
    if (!next.delete(k)) next.add(k)
    setKeys(next)
  }

  const toggleGroup = (k: string) => {
    const next = new Set(openGroups)
    if (!next.delete(k)) next.add(k)
    setOpenGroups(next)
  }

  const toggleRow = (i: number) => {
    const next = new Set(picked)
    if (!next.delete(i)) next.add(i)
    setPicked(next)
  }

  const setGroup = (indices: number[], on: boolean) => {
    const next = new Set(picked)
    for (const i of indices) {
      if (on) next.add(i)
      else next.delete(i)
    }
    setPicked(next)
  }

  /** Every export takes the same selection and reports the same three ways. */
  const runExport = async (
    call: (indices: number[]) => Promise<{
      success: boolean
      cancelled?: boolean
      error?: string | null
      path?: string
      warnings?: string[]
    }>,
  ) => {
    const r = await call([...picked])
    if (r.cancelled) return
    if (!r.success) {
      notify('bad', r.error ?? '导出失败')
      return
    }
    const warned = r.warnings ?? []
    notify(
      warned.length ? 'warn' : 'ok',
      warned.length
        ? `已导出 → ${r.path}；${warned.length} 项未包含: ${warned.join('；')}`
        : `已导出 → ${r.path}`,
    )
  }

  if (records === null) {
    return <div className="text-caption text-muted">读取中…</div>
  }

  if (records.length === 0) {
    return (
      <div className="rounded-ui border border-hairline bg-panel p-6 text-caption text-muted">
        还没有错题。批改完一份卷子就会自动记下丢分的题。
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedStrip items={VIEWS} value={view} onChange={setView} />
        <span className="ml-auto text-caption text-muted tabular-nums">
          已选 {picked.size} / {records.length} 题
        </span>
        <Button onClick={() => runExport((i) => api().then((a) => a.export_mistakes_csv(i)))}>
          导出 CSV
        </Button>
        <Button
          title="把所选题目的 mark scheme 排成一份答案 —— 用批改时已解析的结果，不会重新解析"
          onClick={() => runExport((i) => api().then((a) => a.export_mistakes_answers(i)))}
        >
          导出答案
        </Button>
        <Button
          tone="accent"
          title="把所选题目从原卷裁下来，一道大题一页（不含答题横线）；每题后面跟一页 mark scheme"
          onClick={() => runExport((i) => api().then((a) => a.export_mistakes_pdf(i)))}
        >
          导出 PDF
        </Button>
      </div>

      {allKeys.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {allKeys.map((k) => (
            <button
              key={k}
              onClick={() => toggleKey(k)}
              aria-pressed={keys.has(k)}
              className={`rounded-ui border border-hairline px-2 py-0.5 text-caption
                          ${keys.has(k) ? 'bg-accent text-on-accent' : 'bg-panel text-muted hover:text-ink'}`}
            >
              {k}
            </button>
          ))}
          {keys.size > 0 && (
            <button
              onClick={() => setKeys(new Set())}
              className="px-2 py-0.5 text-caption text-faint hover:text-ink"
            >
              清除筛选
            </button>
          )}
        </div>
      )}

      <div className="space-y-2">
        {groups.map(([key, rows]) => {
          const lost = rows.reduce((s, [, r]) => s + (r.max_score - r.score), 0)
          const open = openGroups.has(key)
          const indices = rows.map(([i]) => i)
          const allPicked = indices.every((i) => picked.has(i))
          return (
            <div key={key} className="rounded-ui border border-hairline bg-panel">
              <div className="flex w-full items-center gap-2 p-2.5">
                <input
                  type="checkbox"
                  checked={allPicked}
                  onChange={(e) => setGroup(indices, e.target.checked)}
                  title="全选这一组"
                />
                <button
                  onClick={() => toggleGroup(key)}
                  aria-expanded={open}
                  className="flex flex-1 items-center gap-2 text-left"
                >
                  <span className="text-caption text-faint">{open ? '▾' : '▸'}</span>
                  <span className="tabular-nums">{key}</span>
                  <span className="ml-auto text-caption text-muted tabular-nums">
                    {rows.length} 题 · 丢 {lost}
                  </span>
                </button>
              </div>
              {open && (
                <div className="border-t border-hairline">
                  <table className="w-full border-collapse text-body">
                    <thead>
                      <tr className="border-b border-hairline text-caption text-muted">
                        <th className="w-8 p-2" />
                        <th className="p-2.5 text-left font-normal">题号</th>
                        {view === 'paper' && (
                          <th className="p-2.5 text-left font-normal">Topic</th>
                        )}
                        {view === 'topic' && (
                          <th className="p-2.5 text-left font-normal">卷号</th>
                        )}
                        <th className="p-2.5 text-right font-normal">得分</th>
                        <th className="p-2.5 text-left font-normal">评语</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map(([i, r]) => (
                        <tr
                          key={i}
                          className={`border-b border-hairline last:border-0 align-top
                                      ${picked.has(i) ? 'bg-raised' : ''}`}
                        >
                          <td className="p-2">
                            <input
                              type="checkbox"
                              checked={picked.has(i)}
                              onChange={() => toggleRow(i)}
                            />
                          </td>
                          <td className="p-2.5 tabular-nums">{r.question_id}</td>
                          <td className="p-2 text-muted">
                            {view === 'paper' ? (
                              <TopicPicker record={r} onDone={load} />
                            ) : (
                              r.paper_id
                            )}
                          </td>
                          <td className="p-2.5 text-right tabular-nums">
                            {r.score} / {r.max_score}
                          </td>
                          <td className="selectable p-2 text-caption text-muted">
                            {r.comment}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
