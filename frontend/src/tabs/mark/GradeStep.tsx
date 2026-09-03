import { useMemo, useState } from 'react'
import { Button } from '../../ui/Button'
import { CELL_H, GRID_COLS, compareQuestionIds } from './cells'
import type { Analysis } from './types'

export function GradeStep({
  analysis,
  busy,
  onStart,
}: {
  analysis: Analysis
  busy: boolean
  onStart: (questionIds: string[]) => void
}) {
  const questionIds = useMemo(
    () => Object.keys(analysis.questions ?? {}).sort(compareQuestionIds),
    [analysis],
  )
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set(questionIds))

  const toggle = (q: string) => {
    const next = new Set(picked)
    if (!next.delete(q)) next.add(q)
    setPicked(next)
  }

  const matched = new Set(analysis.matched ?? [])
  const matchedCount = questionIds.filter((q) => matched.has(q)).length

  return (
    <div className="space-y-4">
      <div className="text-section font-bold">核对题目</div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-caption tabular-nums text-muted">
          {analysis.paper_id} · 共 {questionIds.length} 题 · 满分{' '}
          {analysis.total_marks} · 已定位 {matchedCount}/{questionIds.length}
          {analysis.total_pages ? ` · 答卷 ${analysis.total_pages} 页` : ''}
        </span>
        <Button onClick={() => setPicked(new Set(questionIds))}>全选</Button>
        <Button onClick={() => setPicked(new Set())}>全不选</Button>
        <Button
          tone="accent"
          onClick={() => onStart(questionIds.filter((q) => picked.has(q)))}
          disabled={busy || picked.size === 0}
        >
          开始批改
        </Button>
      </div>

      <div className="text-caption text-muted">
        点一格开关一题。标了「整页」的没被分段定位到，会按整页送去批改。
      </div>

      <div className="grid gap-2.5" style={{ gridTemplateColumns: GRID_COLS }}>
        {questionIds.map((q) => {
          const on = picked.has(q)
          return (
            <button
              key={q}
              onClick={() => toggle(q)}
              aria-pressed={on}
              disabled={busy}
              // The border is 2px whether or not the cell is picked, and only
              // its colour changes: growing one on selection would widen the
              // cell and shove the whole row sideways.
              className={`flex ${CELL_H} flex-col items-center justify-center gap-0.5 rounded-ui
                          border-2 transition-colors ${
                            on
                              ? 'border-accent bg-raised'
                              : 'border-hairline bg-panel text-faint'
                          }`}
              style={{ transitionDuration: 'var(--dur-fast)' }}
            >
              <span className="text-subhead font-semibold">{q}</span>
              <span className="text-caption tabular-nums">
                {analysis.questions?.[q]?.max_marks} 分
              </span>
              {!matched.has(q) && (
                <span className={`text-micro ${on ? 'text-warn' : ''}`}>整页</span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
