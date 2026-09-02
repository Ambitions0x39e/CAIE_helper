import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { PushTrack } from '../../ui/PushTrack'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
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
  const [step, setStep] = useState(0)
  /** How far the flow has actually got. Looking back does not undo progress,
   * so anything past this stays unreachable — same split the Flet tab drew
   * between view_step and reached_step. */
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

  const go = (next: number) => {
    if (next > reached) return
    setDir(next > step ? 1 : -1)
    setStep(next)
  }

  const onAnalysed = useCallback((a: Analysis) => {
    setAnalysis(a)
    setResults([])
    setReached((r) => Math.max(r, 1))
    setDir(1)
    setStep(1)
  }, [])

  const onGraded = useCallback(() => {
    setReached((r) => Math.max(r, 2))
    setDir(1)
    setStep(2)
  }, [])

  return (
    <div className="space-y-3">
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
          <GradeStep
            analysis={analysis}
            results={results}
            setResults={setResults}
            onDone={onGraded}
          />
        ) : step === 2 && analysis ? (
          <ResultsStep analysis={analysis} results={results} onConfirmed={() => undefined} />
        ) : (
          <div className="text-caption text-muted">先在第一步解析一份卷子。</div>
        )}
      </PushTrack>
    </div>
  )
}
