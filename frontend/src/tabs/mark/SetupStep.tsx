import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../lib/bridge'
import { PARSE_JOB, onJobEvent } from '../../lib/jobs'
import { comparePaperIds, syllabusIdOf } from '../../lib/papers'
import type { PaperRecord } from '../../lib/types'
import { Button } from '../../ui/Button'
import { Select } from '../../ui/Select'
import { TextInput } from '../../ui/TextInput'
import { notify } from '../../ui/Toast'
import { nextStage } from './stage'
import type { Analysis } from './types'

type Source = 'downloaded' | 'upload'
type PaperTypeId = 'mcq' | 'math'

/** A labelled radio in one of the two rows at the top of the step. */
function Radio<T extends string>({
  name,
  value,
  current,
  onChange,
  label,
}: {
  name: string
  value: T
  current: T
  onChange: (v: T) => void
  label: string
}) {
  return (
    <label className="flex items-center gap-1.5 text-body">
      <input
        type="radio"
        name={name}
        checked={current === value}
        onChange={() => onChange(value)}
      />
      {label}
    </label>
  )
}

function fileName(path: string): string {
  return path.replace(/\\/g, '/').split('/').pop() ?? ''
}

/** What a finished parse got out of the two PDFs, in one line. */
function parsedSummary(a: Analysis): string {
  const total = Object.keys(a.questions ?? {}).length
  const answer = a.total_pages
    ? `；答卷 ${a.total_pages} 页，识别 ${a.matched?.length ?? 0}/${total} 题`
    : ''
  return `已解析 ${a.paper_id} — 共 ${total} 题，总分 ${a.total_marks}${answer}`
}

export function SetupStep({
  analysis,
  onAnalysed,
}: {
  analysis: Analysis | null
  onAnalysed: (a: Analysis) => void
}) {
  const [papers, setPapers] = useState<PaperRecord[]>([])
  const [source, setSource] = useState<Source>('downloaded')
  const [syllabus, setSyllabus] = useState('')
  const [paperId, setPaperId] = useState('')
  const [paperType, setPaperType] = useState<PaperTypeId>('math')
  const [uploadPath, setUploadPath] = useState('')
  const [startPage, setStartPage] = useState('')
  const [answerPath, setAnswerPath] = useState('')
  const [graderReady, setGraderReady] = useState(true)
  const [busy, setBusy] = useState(false)
  const [cached, setCached] = useState(false)
  const [stage, setStage] = useState('')

  // The listener below is bound for the component's life, so it closes over
  // the first render's answerPath forever. A ref is what lets it read the
  // current pick without re-subscribing and dropping events mid-parse.
  const hasAnswerRef = useRef(false)
  useEffect(() => {
    hasAnswerRef.current = answerPath !== ''
  }, [answerPath])

  useEffect(() => {
    api()
      .then((a) => a.papers())
      .then((list) => setPapers(list.filter((p) => p.ms_path)))
      .catch(() => setPapers([]))
    api()
      .then((a) => a.grader_settings())
      .then((s) => setGraderReady(s.configured))
      .catch(() => setGraderReady(false))
  }, [])

  // Subscribed for the component's life rather than per run: the parse pushes
  // its first progress event before start_analysis has even returned.
  useEffect(
    () =>
      onJobEvent((e) => {
        setStage((s) => nextStage(s, e, { hasAnswer: hasAnswerRef.current }))
        if (e.type === 'ms_cache') setCached(e.cached)
        else if (e.type === 'scan') {
          if (!e.ok) notify('bad', `答卷分析失败: ${e.error}`)
        } else if (e.type === 'analysis') {
          const parsed = e as unknown as Analysis
          notify('ok', parsedSummary(parsed))
          onAnalysed(parsed)
        } else if (e.type === 'error' && e.job === PARSE_JOB)
          notify('bad', `解析失败: ${e.message}`)
        else if (e.type === 'finished' && e.job === PARSE_JOB) setBusy(false)
      }),
    [onAnalysed],
  )

  /** Subject first, then the papers under it: a subject with forty papers
   * should not bury one with two. */
  const codes = useMemo(
    () => [...new Set(papers.map((p) => syllabusIdOf(p.paper_id)))].sort(),
    [papers],
  )
  const filtered = useMemo(
    () =>
      papers
        .filter((p) => syllabusIdOf(p.paper_id) === (syllabus || codes[0]))
        .map((p) => p.paper_id)
        .sort(comparePaperIds),
    [papers, syllabus, codes],
  )

  /** The answer paper this step will parse: the one just picked, or — after a
   * reload — the one the stored analysis was made against. The analysis lives
   * on the Python side and outlives the page, so the file the user chose has
   * to be read back off it rather than left in local state that does not. */
  const answerPdf = answerPath || analysis?.answer_path || ''

  const chosenId = filtered.includes(paperId) ? paperId : (filtered[0] ?? '')
  const chosen = papers.find((p) => p.paper_id === chosenId)
  const msPath = source === 'upload' ? uploadPath : (chosen?.ms_path ?? '')
  const isMcq = paperType === 'mcq'
  const canParse = !busy && msPath !== '' && (isMcq || graderReady)

  const pick = async (set: (p: string) => void) => {
    const p = await (await api()).pick_pdf()
    if (p) set(p)
  }

  const parse = async (force: boolean) => {
    setBusy(true)
    setStage('准备中…')
    const page = Number(startPage)
    const r = await (await api()).start_analysis(
      msPath,
      paperType,
      answerPdf || null,
      startPage !== '' && Number.isFinite(page) ? page : null,
      force,
    )
    if (!r.success) {
      notify('bad', `解析失败: ${r.error ?? ''}`)
      setBusy(false)
      setStage('')
    }
  }

  return (
    <div className="space-y-4">
      <div className="text-section font-bold">选择试卷与答卷</div>

      <div className="space-y-4 rounded-ui border border-hairline bg-panel p-4.5">
        <div className="flex flex-wrap items-center gap-5">
          <Radio
            name="ms-source"
            value="downloaded"
            current={source}
            onChange={setSource}
            label="从已下载试卷"
          />
          <Radio
            name="ms-source"
            value="upload"
            current={source}
            onChange={setSource}
            label="上传 PDF"
          />
        </div>

        <div className="flex flex-wrap items-center gap-5">
          <Radio
            name="paper-type"
            value="mcq"
            current={paperType}
            onChange={setPaperType}
            label="MCQ"
          />
          <Radio
            name="paper-type"
            value="math"
            current={paperType}
            onChange={setPaperType}
            label="Structured / Math"
          />
        </div>

        {source === 'downloaded' ? (
          papers.length === 0 ? (
            <div className="text-body text-muted">
              没有包含 Mark Scheme 的已下载试卷。请先下载或直接上传。
            </div>
          ) : (
            <div className="flex items-end gap-3">
              <Select
                className="w-40 shrink-0"
                label="科目代码"
                value={syllabus || codes[0]}
                onChange={(v) => {
                  setSyllabus(v)
                  setPaperId('')
                }}
                options={codes.map((c) => ({ value: c, label: c }))}
              />
              <Select
                className="min-w-0 flex-1"
                label="选择试卷"
                value={chosenId}
                onChange={setPaperId}
                options={filtered.map((id) => ({ value: id, label: id }))}
              />
            </div>
          )
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => pick(setUploadPath)}>
              选择 MS PDF 文件
            </Button>
            <span className="min-w-0 flex-1 truncate text-caption text-muted">
              {uploadPath ? fileName(uploadPath) : '未选择文件'}
            </span>
          </div>
        )}

        {!isMcq && (
          <label className="block w-50">
            <span className="block text-caption text-muted">MS 内容起始页</span>
            <TextInput
              value={startPage}
              onChange={setStartPage}
              placeholder="自动"
              inputMode="numeric"
              className="mt-1 w-full"
            />
            <span className="mt-1 block text-micro text-muted">默认留空，自动检测</span>
          </label>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => pick(setAnswerPath)}>
            {isMcq ? '选择已批注 QP PDF' : '选择答卷 PDF'}
          </Button>
          <span className="min-w-0 flex-1 truncate text-caption text-muted">
            {answerPdf ? fileName(answerPdf) : '未选择文件（可稍后再选）'}
          </span>
        </div>
        {isMcq && (
          <div className="text-caption text-muted">
            上传在 GoodNotes 中批注过的试卷（圈出/写出每题答案）。
          </div>
        )}

        {/* Stays on the page rather than going out as a toast: it is the
            standing reason the button below is dead, not news. */}
        {!isMcq && !graderReady && (
          <div className="text-caption text-warn">请先在设置中配置 Grader API 凭证。</div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button tone="accent" onClick={() => parse(false)} disabled={!canParse}>
            {answerPdf && !isMcq ? '解析 Mark Scheme 与答卷' : '解析 Mark Scheme'}
          </Button>
          {/* Stands there for the whole run rather than going out as a toast:
              a cold parse is minutes of VL calls, and a message that takes
              itself away after four seconds leaves a greyed-out button as the
              only sign of life — which looks exactly like a hang. */}
          {busy && stage && (
            <span className="flex items-center gap-2 text-caption text-muted"
                  role="status" aria-live="polite">
              <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-warn" />
              {stage}
            </span>
          )}
          {analysis?.ready && cached && !busy && (
            <span className="ml-auto flex items-center gap-1.5 rounded-full border border-hairline
                             bg-raised py-1 pl-3 pr-1.5 text-caption">
              此结果来自缓存
              <Button onClick={() => parse(true)} disabled={!canParse}>
                重新解析
              </Button>
            </span>
          )}
        </div>
      </div>

    </div>
  )
}
