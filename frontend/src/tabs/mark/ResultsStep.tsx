import { useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { Metric } from '../../ui/Metric'
import type { Analysis, QuestionResult } from './types'

export function ResultsStep({
  analysis,
  results,
  onConfirmed,
}: {
  analysis: Analysis
  results: QuestionResult[]
  onConfirmed: () => void
}) {
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [open, setOpen] = useState<string | null>(null)
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [paperId, setPaperId] = useState(analysis.paper_id ?? '')

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
      setNote({ tone: 'ok', text: '分数已记录' })
      onConfirmed()
    } else {
      setNote({ tone: 'bad', text: `记录失败: ${r.error ?? ''}` })
    }
  }

  if (results.length === 0) {
    return <div className="text-caption text-muted">还没有批改结果。</div>
  }

  const total = Object.keys(analysis.questions ?? {}).length

  return (
    <div className="space-y-4">
      <div className="text-section font-bold">批改结果</div>

      <div className="flex flex-wrap gap-3">
        <Metric label="总分" value={`${summary.score}/${summary.max}`} />
        <Metric label="百分比" value={`${summary.pct.toFixed(1)}%`} />
        <Metric label="题数" value={`${results.length}/${total}`} />
      </div>

      <div className="text-caption text-muted">点开任意一题看判分明细。</div>

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

      {note && <Banner tone={note.tone} title={note.text} />}

      <div className="rounded-ui border border-hairline bg-panel">
        {results.map((r, i) => {
          const full = scoreOf(r) === r.max
          return (
            <div key={r.question} className={i > 0 ? 'border-t border-hairline' : ''}>
              <button
                onClick={() => setOpen(open === r.question ? null : r.question)}
                aria-expanded={open === r.question}
                className="flex w-full items-center gap-2 p-2 text-left"
              >
                <span className="text-caption text-faint">
                  {open === r.question ? '▾' : '▸'}
                </span>
                <span className="tabular-nums">{r.question}</span>
                <span className={`ml-auto tabular-nums ${full ? 'text-ok' : 'text-bad'}`}>
                  {scoreOf(r)} / {r.max}
                </span>
              </button>

              {open === r.question && (
                <div className="space-y-2 border-t border-hairline p-3">
                  <label className="flex items-center gap-2 text-caption text-muted">
                    调分
                    <input
                      value={overrides[r.question] ?? ''}
                      placeholder={String(r.total)}
                      onChange={(e) =>
                        setOverrides({ ...overrides, [r.question]: e.target.value })
                      }
                      inputMode="decimal"
                      className="w-20 rounded-ui border border-hairline bg-raised px-2 py-1 text-body text-ink"
                      style={{ cursor: 'text', userSelect: 'text' }}
                    />
                    <span className="text-faint">留空 = 用模型给的 {r.total}</span>
                  </label>

                  {r.comment && (
                    <p className="selectable text-caption text-muted">{r.comment}</p>
                  )}

                  <div className="space-y-1">
                    {r.marks.map((m, j) => (
                      <div key={`${m.code}-${j}`} className="flex gap-2 text-caption">
                        <span
                          className={`shrink-0 tabular-nums ${m.awarded ? 'text-ok' : 'text-bad'}`}
                        >
                          {m.awarded ? '✓' : '✗'} {m.code}
                        </span>
                        <span className="selectable text-muted">{m.reason}</span>
                      </div>
                    ))}
                  </div>

                  {r.topic && <div className="text-micro text-faint">topic: {r.topic}</div>}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
