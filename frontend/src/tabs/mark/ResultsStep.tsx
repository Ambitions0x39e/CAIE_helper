import { useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { Button } from '../../ui/Button'
import { Dialog } from '../../ui/Dialog'
import { Metric } from '../../ui/Metric'
import { notify } from '../../ui/Toast'
import { CELL_H, GRID_COLS, compareQuestionIds, scoreBand } from './cells'
import type { Analysis, QuestionResult } from './types'

export function ResultsStep({
  analysis,
  queue,
  results,
  grading,
  progress,
  onConfirmed,
}: {
  analysis: Analysis
  /** The questions this run was asked to grade. */
  queue: string[]
  results: QuestionResult[]
  grading: boolean
  progress: { done: number; total: number } | null
  onConfirmed: () => void
}) {
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [open, setOpen] = useState<string | null>(null)
  const [paperId, setPaperId] = useState(analysis.paper_id ?? '')

  const byId = useMemo(
    () => new Map(results.map((r) => [r.question, r])),
    [results],
  )

  /** The override wins wherever it parses — the same rule summarise_scores
   * applies on the Python side, so the number shown here is the number
   * recorded. A blank or unparseable box falls back to the model's mark. */
  const scoreOf = (r: QuestionResult) => {
    const raw = overrides[r.question]
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
    for (const [q, v] of Object.entries(overrides)) {
      const n = Number(v)
      if (v !== '' && Number.isFinite(n)) numeric[q] = n
    }
    const r = await (await api()).confirm_results(paperId, numeric)
    if (r.success) {
      notify('ok', '分数已记录')
      onConfirmed()
    } else {
      notify('bad', `记录失败: ${r.error ?? ''}`)
    }
  }

  // Laid out from what was *sent* to grade, not from what has come back: the
  // first frame of a run has no results at all, and a grid built from those
  // would be an empty page until the first question lands.
  const order = (queue.length > 0 ? [...queue] : results.map((r) => r.question)).sort(
    compareQuestionIds,
  )
  if (order.length === 0) {
    return <div className="text-caption text-muted">还没有批改结果。</div>
  }

  const maxOf = (q: string) =>
    byId.get(q)?.max ?? analysis.questions?.[q]?.max_marks ?? 0

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
            正在批改… {progress.done}/{progress.total}
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

      <div className="grid gap-2.5" style={{ gridTemplateColumns: GRID_COLS }}>
        {order.map((q) => {
          const r = byId.get(q)
          const got = r ? scoreOf(r) : null
          // A cell with no mark on it means one of two things, and only the run
          // being over tells them apart: still queued, or the question failed.
          const value = r ? `${got}/${maxOf(q)}` : grading ? '—' : '失败'
          return (
            <button
              key={q}
              onClick={() => r && setOpen(q)}
              disabled={!r}
              className={`flex ${CELL_H} flex-col items-center justify-center gap-0.5 rounded-ui
                          border-2 ${scoreBand(got, maxOf(q))} ${
                            open === q ? 'border-accent' : 'border-transparent'
                          }`}
            >
              <span className="text-subhead font-semibold">{q}</span>
              <span
                className={`text-[20px] font-bold tabular-nums ${
                  r ? '' : grading ? 'text-muted' : 'text-bad'
                }`}
              >
                {value}
              </span>
            </button>
          )
        })}
      </div>

      {!grading && (
        <div className="flex flex-wrap items-center gap-2 rounded-ui border border-hairline bg-panel p-3.5">
          <span className="text-caption text-muted">检查结果，确认后记录分数。</span>
          <input
            value={paperId}
            onChange={(e) => setPaperId(e.target.value)}
            placeholder="记到哪份卷子"
            className="ml-auto w-48 rounded-ui border border-hairline bg-raised px-2 py-1 text-body text-ink"
            style={{ cursor: 'text', userSelect: 'text' }}
          />
          <Button tone="accent" onClick={confirm} disabled={!paperId}>
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
              <input
                value={overrides[detail.question] ?? ''}
                placeholder={String(detail.total)}
                onChange={(e) =>
                  setOverrides({ ...overrides, [detail.question]: e.target.value })
                }
                inputMode="decimal"
                className="w-20 rounded-ui border border-hairline bg-raised px-2 py-1 text-body text-ink"
                style={{ cursor: 'text', userSelect: 'text' }}
              />
              <span className="text-faint">留空 = 用模型给的 {detail.total}</span>
            </label>

            {detail.topic && (
              <div className="text-micro text-faint">topic: {detail.topic}</div>
            )}
          </div>
        )}
      </Dialog>
    </div>
  )
}
