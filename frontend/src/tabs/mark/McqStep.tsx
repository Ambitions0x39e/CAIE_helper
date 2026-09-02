import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { onJobEvent } from '../../lib/jobs'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { Metric } from '../../ui/Metric'
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
          setProgress(`第 ${e.batch}/${e.total} 页…`)
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
    const p = await (await api()).pick_pdf('选择已批注 QP PDF')
    if (p) setQpPath(p)
  }

  const detect = async () => {
    setBusy(true)
    setError(null)
    setScored(null)
    setProgress('正在检测答案…')
    const name = qpPath.split(/[\\/]/).pop() ?? ''
    const r = await (await api()).start_mcq_detection(qpPath, name)
    if (!r.success) {
      setError(`检测失败: ${r.error ?? ''}`)
      setBusy(false)
      setProgress(null)
    }
  }

  const score = async () => {
    const r = await (await api()).score_mcq(manual)
    if (r.success) setScored(r as typeof scored)
    else setError(`检测失败: ${r.error ?? ''}`)
  }

  const confirm = async () => {
    const r = await (await api()).confirm_mcq(paperId, manual)
    setNote(
      r.success
        ? { tone: 'ok', text: '分数已记录' }
        : { tone: 'bad', text: `记录失败: ${r.error ?? ''}` },
    )
  }

  /** What each question will actually be scored on. */
  const effective = (q: string) =>
    isValidManual(manual[q] ?? '') ? manual[q] : (detected[q] ?? '')

  const hasDetection = Object.keys(detected).length > 0 || undetected.length > 0

  return (
    <div className="space-y-4">
      <div className="text-section font-bold">检测与批改</div>

      <div className="rounded-ui border border-hairline bg-panel p-4.5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={pick}>选择已批注 QP PDF</Button>
          <span className="min-w-0 flex-1 truncate text-caption text-muted">
            {qpPath ? (qpPath.split(/[\\/]/).pop() ?? '') : '未选择文件'}
          </span>
        </div>
        <Button tone="accent" onClick={detect} disabled={busy || !qpPath}>
          检测答案
        </Button>
      </div>

      {progress && <Banner tone="warn" title={progress} />}
      {error && <Banner tone="bad" title={error} />}
      {undetected.length > 0 && (
        <Banner
          tone="warn"
          title={`未能检测到 ${undetected.length} 题: ${undetected.join(', ')}。请在下方手动填写。`}
        />
      )}

      {hasDetection && (
        <>
          {scored && (
            <div className="flex flex-wrap gap-3">
              <Metric label="得分" value={`${scored.score}/${scored.total}`} />
              <Metric
                label="百分比"
                value={`${((scored.score / Math.max(scored.total, 1)) * 100).toFixed(1)}%`}
              />
              <Metric label="已检测" value={String(Object.keys(detected).length)} />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 rounded-ui border border-hairline bg-panel p-3.5">
            <Button onClick={score}>打分</Button>
            <span className="text-caption text-muted">检查上方结果，确认后记录分数。</span>
            <input
              value={paperId}
              onChange={(e) => setPaperId(e.target.value)}
              placeholder="记到哪份卷子"
              className="ml-auto w-44 rounded-ui border border-hairline bg-raised px-2 py-1 text-body text-ink"
              style={{ cursor: 'text', userSelect: 'text' }}
            />
            <Button tone="accent" onClick={confirm} disabled={!paperId || !scored}>
              确认并记录分数
            </Button>
          </div>

          {note && <Banner tone={note.tone} title={note.text} />}

          <div className="text-body font-bold">逐题结果:</div>

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
