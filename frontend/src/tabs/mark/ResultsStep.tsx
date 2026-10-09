import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { Button } from '../../ui/Button'
import { Dialog } from '../../ui/Dialog'
import { Metric } from '../../ui/Metric'
import { Select } from '../../ui/Select'
import { TextInput } from '../../ui/TextInput'
import { notify } from '../../ui/Toast'
import {
  CELL_H,
  GRID_COLS,
  compareResultKeys,
  paperOf,
  questionOf,
  resultKey,
  scoreBand,
} from './cells'
import type { Run } from './run'
import { ERROR_LABELS, type ErrorType, type QuestionResult } from './types'

const UNCLASSIFIED = '未分类'

/** Stands in for "no topic" in the picker: an empty option value is what a
 * listbox uses to mean nothing is chosen, not that 未分类 was. */
const NONE = '__none__'

export function ResultsStep({
  paperId: analysedId,
  run,
}: {
  /** The analysed paper's id, which a whole paper is recorded under unless
   * the student types another. */
  paperId: string
  run: Run
}) {
  const { queue, results, grading, progress } = run
  const whole = run.kind === 'paper'
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [open, setOpen] = useState<string | null>(null)
  const [paperId, setPaperId] = useState(analysedId)
  /** Every override is keyed by `resultKey`. Topic: the id the student
   * picked; null is 未分类; absent keeps the model's tag. */
  const [topicOverrides, setTopicOverrides] = useState<Record<string, string | null>>({})
  const [errorOverrides, setErrorOverrides] = useState<Record<string, ErrorType | null>>({})
  /** A whole paper's topics, which follow the paper id typed below. Null
   * when the paper has no topics to pick from — no syllabus, or a component
   * it does not map. */
  const [typedTopics, setTypedTopics] = useState<Record<string, string> | null>(null)

  useEffect(() => {
    if (!whole) return
    api()
      .then((a) => a.topics_for(paperId))
      .then(setTypedTopics)
      .catch(() => setTypedTopics(null))
  }, [paperId, whole])

  /** A hand-back's questions each pick from their own paper's list. */
  const topicsOf = (paper: string) => (whole ? typedTopics : (run.topics[paper] ?? null))

  const keyOf = (r: QuestionResult) => resultKey(r.paper_id, r.question)
  const topicOf = (r: QuestionResult) =>
    keyOf(r) in topicOverrides ? topicOverrides[keyOf(r)] : r.topic
  const errorOf = (r: QuestionResult) =>
    keyOf(r) in errorOverrides ? errorOverrides[keyOf(r)] : r.error_type
  const topicName = (r: QuestionResult) => {
    const id = topicOf(r)
    return id ? (topicsOf(r.paper_id)?.[id] ?? id) : UNCLASSIFIED
  }

  const byId = useMemo(
    () => new Map(results.map((r) => [keyOf(r), r])),
    [results],
  )

  /** The override wins wherever it parses — the same rule summarise_scores
   * applies on the Python side, so the number shown here is the number
   * recorded. A blank or unparseable box falls back to the model's mark. */
  const scoreOf = (r: QuestionResult) => {
    const raw = overrides[keyOf(r)]
    const n = raw === undefined || raw === '' ? Number.NaN : Number(raw)
    return Number.isFinite(n) ? n : r.total
  }

  const summary = useMemo(() => {
    const score = results.reduce((s, r) => s + scoreOf(r), 0)
    const max = results.reduce((s, r) => s + r.max, 0)
    return { score, max, pct: max ? Math.round((score / max) * 1000) / 10 : 0 }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [results, overrides])

  const confirm = async () => {
    const numeric: Record<string, number> = {}
    for (const [k, v] of Object.entries(overrides)) {
      const n = Number(v)
      if (v !== '' && Number.isFinite(n)) numeric[k] = n
    }
    const r = await (await api()).confirm_results(
      paperId,
      numeric,
      topicOverrides,
      errorOverrides,
    )
    if (r.success) {
      notify('ok', '分数已记录')
    } else {
      notify('bad', `记录失败: ${r.error ?? ''}`)
    }
  }

  // Laid out from what was *sent* to grade, not from what has come back: the
  // first frame of a run has no results at all, and a grid built from those
  // would be an empty page until the first question lands.
  const order = (queue.length > 0 ? [...queue] : results.map(keyOf)).sort(compareResultKeys)
  if (order.length === 0) {
    return <div className="text-caption text-muted">还没有批改结果。</div>
  }

  const maxOf = (k: string) => byId.get(k)?.max ?? run.max[k] ?? 0
  const papers = [...new Set(order.map(paperOf))]

  const detail = open === null ? null : (byId.get(open) ?? null)

  return (
    <div className="space-y-4">
      <div className="text-section font-bold">批改结果</div>

      <div className="flex flex-wrap gap-3">
        <Metric label="总分" value={`${summary.score}/${summary.max}`} />
        <Metric label="百分比" value={`${summary.pct.toFixed(1)}%`} />
        <Metric label="题数" value={`${results.length}/${order.length}`} />
      </div>

      {grading && progress ? (
        <div className="space-y-1">
          <div className="text-caption tabular-nums text-muted">
            {progress.fetching
              ? `正在获取 ${progress.fetching} 大纲…`
              : `正在批改… ${progress.done}/${progress.total}`}
          </div>
          <div className="h-1 overflow-hidden rounded bg-hairline">
            <div
              className="h-full bg-accent"
              style={{
                width: `${(progress.done / Math.max(progress.total, 1)) * 100}%`,
                transition: 'width var(--dur-base) var(--ease-ui)',
              }}
            />
          </div>
        </div>
      ) : (
        <div className="text-caption text-muted">点开任意一题看判分明细。</div>
      )}

      {papers.map((paper) => (
        <div key={paper} className="space-y-2">
          {!whole && <div className="text-caption tabular-nums text-muted">{paper}</div>}
          <div className="grid gap-2.5" style={{ gridTemplateColumns: GRID_COLS }}>
            {order
              .filter((k) => paperOf(k) === paper)
              .map((k) => {
                const r = byId.get(k)
                const got = r ? scoreOf(r) : null
                // A cell with no mark on it means one of two things, and only the run
                // being over tells them apart: still queued, or the question failed.
                const value = r ? `${got}/${maxOf(k)}` : grading ? '—' : '失败'
                return (
                  <button
                    key={k}
                    onClick={() => r && setOpen(k)}
                    disabled={!r}
                    className={`flex ${CELL_H} flex-col items-center justify-center gap-0.5 rounded-ui
                                border-2 ${scoreBand(got, maxOf(k))} ${
                                  open === k ? 'border-accent' : 'border-transparent'
                                }`}
                  >
                    <span className="text-subhead font-semibold">{questionOf(k)}</span>
                    <span
                      className={`text-[20px] font-bold tabular-nums ${
                        r ? '' : grading ? 'text-muted' : 'text-bad'
                      }`}
                    >
                      {value}
                    </span>
                    {r && topicsOf(r.paper_id) && got !== null && got < r.max && (
                      <span className="max-w-full truncate px-2 text-micro text-muted">
                        {topicName(r)}
                      </span>
                    )}
                  </button>
                )
              })}
          </div>
        </div>
      ))}

      {!grading && (
        <div className="flex flex-wrap items-center gap-2 rounded-ui border border-hairline bg-panel p-3.5">
          <span className="text-caption text-muted">检查结果，确认后记录分数。</span>
          {whole && (
            <TextInput
              value={paperId}
              onChange={setPaperId}
              placeholder="记到哪份卷子"
              className="ml-auto w-48"
            />
          )}
          <Button
            tone="accent"
            onClick={confirm}
            disabled={whole && !paperId}
            className={whole ? '' : 'ml-auto'}
          >
            确认并记录分数
          </Button>
        </div>
      )}

      <Dialog
        open={detail !== null}
        title={detail ? `${detail.question} · ${scoreOf(detail)}/${detail.max}` : ''}
        onClose={() => setOpen(null)}
      >
        {detail && (
          <div className="space-y-3">
            <div className="space-y-1.5">
              {detail.marks.map((m, i) => (
                <div key={`${m.code}-${i}`} className="flex gap-2 text-caption">
                  <span
                    className={`shrink-0 tabular-nums ${m.awarded ? 'text-ok' : 'text-bad'}`}
                  >
                    {m.awarded ? '✓' : '✗'} {m.code}
                  </span>
                  <span className="selectable text-muted">{m.reason}</span>
                </div>
              ))}
            </div>

            {detail.comment && (
              <p className="selectable text-caption text-muted">{detail.comment}</p>
            )}

            <label className="flex items-center gap-2 text-caption text-muted">
              调分
              <TextInput
                value={overrides[keyOf(detail)] ?? ''}
                placeholder={String(detail.total)}
                onChange={(v) => setOverrides({ ...overrides, [keyOf(detail)]: v })}
                inputMode="decimal"
                className="w-20"
              />
              <span className="text-faint">留空 = 用模型给的 {detail.total}</span>
            </label>

            {topicsOf(detail.paper_id) && (
              <Select
                label="topic"
                value={topicOf(detail) ?? NONE}
                onChange={(v) =>
                  setTopicOverrides({
                    ...topicOverrides,
                    [keyOf(detail)]: v === NONE ? null : v,
                  })
                }
                options={[
                  { value: NONE, label: UNCLASSIFIED },
                  ...Object.entries(topicsOf(detail.paper_id) ?? {}).map(([id, name]) => ({
                    value: id,
                    label: name,
                  })),
                ]}
              />
            )}

            {scoreOf(detail) < detail.max && (
              <Select
                label="丢分原因"
                value={errorOf(detail) ?? NONE}
                onChange={(v) =>
                  setErrorOverrides({
                    ...errorOverrides,
                    [keyOf(detail)]: v === NONE ? null : (v as ErrorType),
                  })
                }
                options={[
                  { value: NONE, label: UNCLASSIFIED },
                  ...Object.entries(ERROR_LABELS).map(([id, label]) => ({ value: id, label })),
                ]}
              />
            )}
          </div>
        )}
      </Dialog>
    </div>
  )
}
