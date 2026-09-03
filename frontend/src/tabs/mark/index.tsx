import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { GRADE_JOB, onJobEvent } from '../../lib/jobs'
import { PushTrack } from '../../ui/PushTrack'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { notify } from '../../ui/Toast'
import { GradeStep } from './GradeStep'
import { McqStep } from './McqStep'
import { ResultsStep } from './ResultsStep'
import { SetupStep } from './SetupStep'
import type { Analysis, QuestionResult } from './types'

const STEPS = [
  { id: '0', label: '选卷' },
  { id: '1', label: '核对' },
  { id: '2', label: '结果' },
] as const

export function MarkTab() {
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [results, setResults] = useState<QuestionResult[]>([])
  /** The questions the running batch was asked for — what 结果 lays out. */
  const [queue, setQueue] = useState<string[]>([])
  const [grading, setGrading] = useState(false)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const [step, setStep] = useState(0)
  /** How far the flow has actually got. Looking back does not undo progress,
   * so anything past this stays unreachable. */
  const [reached, setReached] = useState(0)
  const [dir, setDir] = useState(1)

  // The analysis lives on the Python side, so a reload picks it back up
  // instead of paying for another vision-model call.
  useEffect(() => {
    api()
      .then((a) => a.analysis())
      .then((a) => {
        if (a.ready) {
          setAnalysis(a as Analysis)
          setReached((r) => Math.max(r, 1))
        }
      })
      .catch(() => undefined)
  }, [])

  // Subscribed by the tab rather than by 结果: the marks have to keep landing
  // while the user is looking at another step, and a listener that unmounts
  // with the view would drop the ones that arrive meanwhile.
  useEffect(
    () =>
      onJobEvent((e) => {
        if (e.type === 'progress') setProgress({ done: e.done, total: e.total })
        // Results arrive as each question lands, not in question order — the
        // whole point of streaming them is that the grid fills in live.
        else if (e.type === 'result')
          setResults((prev) => [...prev, e.result as unknown as QuestionResult])
        else if (e.type === 'graded') {
          setProgress(null)
          if (e.failures.length > 0) {
            const [first] = e.failures
            notify(
              'bad',
              e.failures.length === 1
                ? `${first.question} 批改失败: ${first.error}`
                : `${e.failures.length} 题批改失败，第一题 ${first.question}: ${first.error}`,
            )
          }
        }
        // Both terminal events are shared by every job, so they are read only
        // when they belong to this one — the parse on the first step pushes
        // the same two.
        else if (e.type === 'error' && e.job === GRADE_JOB)
          notify('bad', `批改失败: ${e.message}`)
        else if (e.type === 'finished' && e.job === GRADE_JOB) setGrading(false)
      }),
    [],
  )

  const go = (next: number) => {
    if (next > reached) return
    setDir(next > step ? 1 : -1)
    setStep(next)
  }

  const onAnalysed = useCallback((a: Analysis) => {
    setAnalysis(a)
    setResults([])
    setQueue([])
    setReached((r) => Math.max(r, 1))
    setDir(1)
    setStep(1)
  }, [])

  /** Start a run and go straight to 结果 — that step draws the batch as
   * pending cells and fills them in one by one, which is where the progress
   * of a run is actually legible. */
  const startGrading = useCallback(async (questionIds: string[]) => {
    setGrading(true)
    setResults([])
    setQueue(questionIds)
    setProgress({ done: 0, total: questionIds.length })
    setReached(2)
    setDir(1)
    setStep(2)
    const r = await (await api()).start_grading(questionIds)
    if (!r.success) {
      notify('bad', r.error ?? '无法开始批改')
      setGrading(false)
      setProgress(null)
    }
  }, [])

  return (
    <div className="space-y-4">
      <SegmentedStrip
        items={STEPS.filter(
          (s) => !(analysis?.paper_type === 'mcq' && s.id === '2'),
        )}
        value={String(step)}
        // Greyed by how far the flow has got, not by where you are looking:
        // paging back does not put the later steps out of reach again.
        disabled={new Set(STEPS.slice(reached + 1).map((s) => s.id))}
        onChange={(v) => go(Number(v))}
      />
      <PushTrack step={step} dir={dir}>
        {step === 0 ? (
          <SetupStep analysis={analysis} onAnalysed={onAnalysed} />
        ) : step === 1 && analysis?.paper_type === 'mcq' ? (
          // MCQ detects and scores in one place — there is no per-question
          // mark scheme to review afterwards, so it has no third step.
          <McqStep analysis={analysis} />
        ) : step === 1 && analysis ? (
          <GradeStep analysis={analysis} busy={grading} onStart={startGrading} />
        ) : step === 2 && analysis ? (
          <ResultsStep
            analysis={analysis}
            queue={queue}
            results={results}
            grading={grading}
            progress={progress}
            onConfirmed={() => undefined}
          />
        ) : (
          <div className="text-caption text-muted">先在第一步解析一份卷子。</div>
        )}
      </PushTrack>
    </div>
  )
}
