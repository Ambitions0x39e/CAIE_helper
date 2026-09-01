import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { onJobEvent } from '../../lib/jobs'
import type { PaperRecord } from '../../lib/types'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import type { Analysis } from './types'

const TYPES = [
  { id: 'math', label: '结构化（VL 批改）' },
  { id: 'mcq', label: '选择题（答案键）' },
] as const
type PaperTypeId = (typeof TYPES)[number]['id']

export function SetupStep({
  onAnalysed,
}: {
  onAnalysed: (a: Analysis) => void
}) {
  const [papers, setPapers] = useState<PaperRecord[]>([])
  const [paperId, setPaperId] = useState('')
  const [paperType, setPaperType] = useState<PaperTypeId>('math')
  const [msPath, setMsPath] = useState('')
  const [answerPath, setAnswerPath] = useState('')
  const [busy, setBusy] = useState(false)
  const [msProgress, setMsProgress] = useState<string | null>(null)
  const [scanNote, setScanNote] = useState<string | null>(null)
  const [cached, setCached] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api()
      .then((a) => a.papers())
      .then((list) => setPapers(list.filter((p) => p.ms_path)))
      .catch(() => setPapers([]))
  }, [])

  // Subscribed for the component's life rather than per run: the parse pushes
  // its first progress event before start_analysis has even returned.
  useEffect(
    () =>
      onJobEvent((e) => {
        if (e.type === 'ms_cache') setCached(e.cached)
        else if (e.type === 'ms_progress')
          setMsProgress(`处理第 ${e.batch}/${e.total} 批…`)
        else if (e.type === 'scan')
          setScanNote(e.ok ? '答卷解析完成' : `答卷解析失败：${e.error}`)
        else if (e.type === 'analysis') {
          onAnalysed(e as unknown as Analysis)
          setMsProgress(null)
        } else if (e.type === 'error') setError(e.message)
        else if (e.type === 'finished') setBusy(false)
      }),
    [onAnalysed],
  )

  const chosen = papers.find((p) => p.paper_id === paperId)
  const effectiveMs = msPath || chosen?.ms_path || ''

  const pick = async (set: (p: string) => void, title: string) => {
    const p = await (await api()).pick_pdf(title)
    if (p) set(p)
  }

  const analyse = async () => {
    setBusy(true)
    setError(null)
    setScanNote(null)
    setMsProgress('准备中…')
    const r = await (await api()).start_analysis(
      effectiveMs, paperType, answerPath || null, null, false,
    )
    if (!r.success) {
      setError(r.error ?? '无法开始解析')
      setBusy(false)
      setMsProgress(null)
    }
  }

  return (
    <div className="max-w-2xl space-y-3">
      <div className="rounded-ui border border-hairline bg-panel p-3.5 space-y-3">
        <label className="block">
          <span className="block text-caption text-muted">已下载的卷子</span>
          <select
            value={paperId}
            onChange={(e) => {
              setPaperId(e.target.value)
              setMsPath('')
            }}
            className="mt-1 w-full rounded-ui border border-hairline bg-raised px-2 py-1.5 text-body text-ink"
          >
            <option value="">（自己传 mark scheme）</option>
            {papers.map((p) => (
              <option key={p.paper_id} value={p.paper_id}>
                {p.paper_id}
              </option>
            ))}
          </select>
        </label>

        <div className="flex items-center gap-2">
          <span className="text-caption text-muted">卷子类型</span>
          <SegmentedStrip items={TYPES} value={paperType} onChange={setPaperType} />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => pick(setMsPath, 'Mark scheme')}>选 mark scheme</Button>
          <span className="min-w-0 flex-1 truncate text-caption text-faint">
            {effectiveMs || '未选择'}
          </span>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => pick(setAnswerPath, '答卷')}>选答卷 PDF</Button>
          <span className="min-w-0 flex-1 truncate text-caption text-faint">
            {answerPath || '未选择'}
          </span>
        </div>

        <Button tone="accent" onClick={analyse} disabled={busy || !effectiveMs}>
          {busy ? '解析中…' : '解析'}
        </Button>
      </div>

      {cached && !busy && (
        <Banner tone="ok" title="用的是缓存里的解析结果 —— 重新解析要再花一次视觉模型调用" />
      )}
      {msProgress && <Banner tone="warn" title={msProgress} />}
      {scanNote && <Banner tone="ok" title={scanNote} />}
      {error && <Banner tone="bad" title={error} />}
    </div>
  )
}
