import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { onJobEvent } from '../../lib/jobs'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import type { Analysis, QuestionResult } from './types'

export function GradeStep({
  analysis,
  results,
  setResults,
  onDone,
}: {
  analysis: Analysis
  results: QuestionResult[]
  setResults: (fn: (prev: QuestionResult[]) => QuestionResult[]) => void
  onDone: () => void
}) {
  const questionIds = Object.keys(analysis.questions ?? {})
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set(questionIds))
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [failures, setFailures] = useState<{ question: string; error: string }[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(
    () =>
      onJobEvent((e) => {
        if (e.type === 'progress') setProgress({ done: e.done, total: e.total })
        // Results arrive as each question lands, not in question order — the
        // whole point of streaming them is that the list fills in live.
        else if (e.type === 'result')
          setResults((prev) => [...prev, e.result as unknown as QuestionResult])
        else if (e.type === 'graded') {
          setFailures(e.failures)
          setProgress(null)
          if (e.failures.length === 0) onDone()
        } else if (e.type === 'error') setError(e.message)
        else if (e.type === 'finished') setBusy(false)
      }),
    [setResults, onDone],
  )

  const toggle = (q: string) => {
    const next = new Set(picked)
    if (!next.delete(q)) next.add(q)
    setPicked(next)
  }

  const run = async () => {
    setBusy(true)
    setError(null)
    setFailures([])
    setResults(() => [])
    const r = await (await api()).start_grading([...picked])
    if (!r.success) {
      setError(r.error ?? '无法开始批改')
      setBusy(false)
    }
  }

  const matched = new Set(analysis.matched ?? [])
  const matchedCount = questionIds.filter((q) => matched.has(q)).length
  const unmatched = questionIds.filter((q) => !matched.has(q))

  return (
    <div className="space-y-4">
      <div className="text-section font-bold">核对题目</div>
      <div className="text-body">勾选要批改的题，并确认每题的页码。</div>

      <Banner
        tone={matchedCount === questionIds.length ? 'ok' : 'warn'}
        title={
          analysis.total_pages
            ? `PDF 共 ${analysis.total_pages} 页 | ${matchedCount}/${questionIds.length} 题已自动定位`
            : `${matchedCount}/${questionIds.length} 题已自动定位`
        }
        details={
          unmatched.length > 0
            ? [`未识别：${unmatched.slice(0, 8).join('、')}${
                unmatched.length > 8 ? ` 等 ${unmatched.length} 题` : ''
              }。这些题会按整页送去批改。`]
            : undefined
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-caption text-muted tabular-nums">
          {analysis.paper_id} · 共 {questionIds.length} 题 · 满分 {analysis.total_marks}
        </span>
        <Button onClick={() => setPicked(new Set(questionIds))}>全选</Button>
        <Button onClick={() => setPicked(new Set())}>全不选</Button>
        <Button tone="accent" onClick={run} disabled={busy || picked.size === 0}>
          开始批改
        </Button>
      </div>

      {picked.size === 0 && (
        <div className="text-caption text-warn">请至少勾选一个题目进行批改。</div>
      )}

      {progress && (
        <div className="space-y-1">
          <div className="text-caption text-muted tabular-nums">
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
      )}

      {error && <Banner tone="bad" title={error} />}
      {failures.map((f) => (
        <Banner key={f.question} tone="bad" title={`${f.question}：${f.error}`} />
      ))}

      <div className="rounded-ui border border-hairline bg-panel">
        {questionIds.map((q, i) => {
          const done = results.find((r) => r.question === q)
          return (
            <label
              key={q}
              className={`flex items-center gap-2 p-2 ${i > 0 ? 'border-t border-hairline' : ''}`}
            >
              <input
                type="checkbox"
                checked={picked.has(q)}
                onChange={() => toggle(q)}
                disabled={busy}
              />
              <span className="tabular-nums">{q}</span>
              {!matched.has(q) && (
                <span
                  className="text-micro text-warn"
                  title="分段没定位到它，会按整页送去批改"
                >
                  整页
                </span>
              )}
              <span className="ml-auto text-caption tabular-nums">
                {done ? (
                  <span className={done.total === done.max ? 'text-ok' : 'text-bad'}>
                    {done.total} / {done.max}
                  </span>
                ) : (
                  <span className="text-faint">
                    {analysis.questions?.[q]?.max_marks} 分
                  </span>
                )}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}
