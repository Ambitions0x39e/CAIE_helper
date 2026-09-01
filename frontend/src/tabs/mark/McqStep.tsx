import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { onJobEvent } from '../../lib/jobs'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { isValidManual } from './mcq'
import type { Analysis } from './types'

export function McqStep({ analysis }: { analysis: Analysis }) {
  const questionIds = useMemo(
    () => Object.keys(analysis.questions ?? {}),
    [analysis],
  )

  const [qpPath, setQpPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<string | null>(null)
  const [detected, setDetected] = useState<Record<string, string>>({})
  const [undetected, setUndetected] = useState<string[]>([])
  const [answerKey, setAnswerKey] = useState<Record<string, string>>({})
  const [manual, setManual] = useState<Record<string, string>>({})
  const [scored, setScored] = useState<{
    score: number
    total: number
    per_question: Record<string, boolean>
  } | null>(null)
  const [paperId, setPaperId] = useState(analysis.paper_id ?? '')
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(
    () =>
      onJobEvent((e) => {
        if (e.type === 'mcq_progress')
          setProgress(`识别第 ${e.batch}/${e.total} 批…`)
        else if (e.type === 'mcq_detected') {
          setDetected(e.detected as Record<string, string>)
          setUndetected(e.undetected as string[])
          setAnswerKey(e.answer_key as Record<string, string>)
          setProgress(null)
        } else if (e.type === 'error') setError(e.message)
        else if (e.type === 'finished') setBusy(false)
      }),
    [],
  )

  const pick = async () => {
    const p = await (await api()).pick_pdf('已作答的 QP')
    if (p) setQpPath(p)
  }

  const detect = async () => {
    setBusy(true)
    setError(null)
    setScored(null)
    setProgress('准备中…')
    const name = qpPath.split(/[\\/]/).pop() ?? ''
    const r = await (await api()).start_mcq_detection(qpPath, name)
    if (!r.success) {
      setError(r.error ?? '无法开始识别')
      setBusy(false)
      setProgress(null)
    }
  }

  const score = async () => {
    const r = await (await api()).score_mcq(manual)
    if (r.success) setScored(r as typeof scored)
    else setError(r.error ?? '打分失败')
  }

  const confirm = async () => {
    const r = await (await api()).confirm_mcq(paperId, manual)
    setNote(
      r.success
        ? { tone: 'ok', text: `已记录 ${r.score} / ${r.total}` }
        : { tone: 'bad', text: r.error ?? '记录失败' },
    )
  }

  /** What each question will actually be scored on. */
  const effective = (q: string) =>
    isValidManual(manual[q] ?? '') ? manual[q] : (detected[q] ?? '')

  const hasDetection = Object.keys(detected).length > 0 || undetected.length > 0

  return (
    <div className="max-w-2xl space-y-3">
      <div className="rounded-ui border border-hairline bg-panel p-3.5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={pick}>选已作答的 QP</Button>
          <span className="min-w-0 flex-1 truncate text-caption text-faint">
            {qpPath || '未选择'}
          </span>
        </div>
        <Button tone="accent" onClick={detect} disabled={busy || !qpPath}>
          {busy ? '识别中…' : '识别答案'}
        </Button>
      </div>

      {progress && <Banner tone="warn" title={progress} />}
      {error && <Banner tone="bad" title={error} />}
      {undetected.length > 0 && (
        <Banner
          tone="warn"
          title={`有 ${undetected.length} 题没识别出来，下面手动填：${undetected.join(', ')}`}
        />
      )}

      {hasDetection && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={score}>打分</Button>
            {scored && (
              <span className="text-body tabular-nums">
                {scored.score} <span className="text-muted">/ {scored.total}</span>
              </span>
            )}
            <input
              value={paperId}
              onChange={(e) => setPaperId(e.target.value)}
              placeholder="记到哪份卷子"
              className="ml-auto w-44 rounded-ui border border-hairline bg-raised px-2 py-1 text-body text-ink"
              style={{ cursor: 'text', userSelect: 'text' }}
            />
            <Button tone="accent" onClick={confirm} disabled={!paperId || !scored}>
              确认并记录
            </Button>
          </div>

          {note && <Banner tone={note.tone} title={note.text} />}

          <div
            className="grid gap-1.5"
            style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(7.5rem, 1fr))' }}
          >
            {questionIds.map((q) => {
              const mine = effective(q)
              const right = scored?.per_question[q]
              return (
                <div
                  key={q}
                  className={`flex items-center gap-1.5 rounded-ui border border-hairline p-1.5
                    ${right === true ? 'bg-ok/10' : right === false ? 'bg-bad/10' : 'bg-panel'}`}
                >
                  <span className="w-8 shrink-0 text-caption tabular-nums text-muted">{q}</span>
                  <input
                    value={manual[q] ?? ''}
                    placeholder={detected[q] ?? '—'}
                    maxLength={1}
                    onChange={(e) =>
                      setManual({ ...manual, [q]: e.target.value.toUpperCase() })
                    }
                    className={`w-8 rounded border border-hairline bg-raised px-1 py-0.5 text-center
                                text-body uppercase ${mine ? 'text-ink' : 'text-faint'}`}
                    style={{ cursor: 'text', userSelect: 'text' }}
                  />
                  {scored && (
                    <span
                      className={`ml-auto text-caption tabular-nums ${
                        right ? 'text-ok' : 'text-bad'
                      }`}
                      title={right ? '' : `正确答案 ${answerKey[q]}`}
                    >
                      {right ? '✓' : answerKey[q]}
                    </span>
                  )}
                </div>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
