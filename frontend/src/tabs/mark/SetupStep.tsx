import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { onJobEvent } from '../../lib/jobs'
import { comparePaperIds, syllabusIdOf } from '../../lib/papers'
import type { PaperRecord } from '../../lib/types'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import type { Analysis } from './types'

const SELECT = 'rounded-ui border border-hairline bg-raised px-2 py-1.5 text-body text-ink'

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
  const [msProgress, setMsProgress] = useState<string | null>(null)
  const [scanNote, setScanNote] = useState<string | null>(null)
  const [cached, setCached] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
        if (e.type === 'ms_cache') setCached(e.cached)
        else if (e.type === 'ms_progress')
          setMsProgress(`处理第 ${e.batch}/${e.total} 批…`)
        else if (e.type === 'scan')
          setScanNote(e.ok ? '答卷解析完成' : `答卷分析失败: ${e.error}`)
        else if (e.type === 'analysis') {
          onAnalysed(e as unknown as Analysis)
          setMsProgress(null)
        } else if (e.type === 'error') setError(`解析失败: ${e.message}`)
        else if (e.type === 'finished') setBusy(false)
      }),
    [onAnalysed],
  )

  /** Subject first, then the papers under it — the same two-step narrowing the
   * Flet tab does, so a subject with forty papers does not bury one with two. */
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

  const chosenId = filtered.includes(paperId) ? paperId : (filtered[0] ?? '')
  const chosen = papers.find((p) => p.paper_id === chosenId)
  const msPath = source === 'upload' ? uploadPath : (chosen?.ms_path ?? '')
  const isMcq = paperType === 'mcq'
  const canParse = !busy && msPath !== '' && (isMcq || graderReady)

  const pick = async (set: (p: string) => void, title: string) => {
    const p = await (await api()).pick_pdf(title)
    if (p) set(p)
  }

  const parse = async (force: boolean) => {
    setBusy(true)
    setError(null)
    setScanNote(null)
    setMsProgress('正在解析 Mark Scheme…')
    const page = Number(startPage)
    const r = await (await api()).start_analysis(
      msPath,
      paperType,
      answerPath || null,
      startPage !== '' && Number.isFinite(page) ? page : null,
      force,
    )
    if (!r.success) {
      setError(`解析失败: ${r.error ?? ''}`)
      setBusy(false)
      setMsProgress(null)
    }
  }

  return (
    <div className="space-y-3">
      <div className="text-section font-bold">选择试卷与答卷</div>

      <div className="space-y-3 rounded-ui border border-hairline bg-panel p-3.5">
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
              <label className="w-40 shrink-0">
                <span className="block text-caption text-muted">科目代码</span>
                <select
                  className={`mt-1 w-full ${SELECT}`}
                  value={syllabus || codes[0]}
                  onChange={(e) => {
                    setSyllabus(e.target.value)
                    setPaperId('')
                  }}
                >
                  {codes.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="min-w-0 flex-1">
                <span className="block text-caption text-muted">选择试卷</span>
                <select
                  className={`mt-1 w-full ${SELECT}`}
                  value={chosenId}
                  onChange={(e) => setPaperId(e.target.value)}
                >
                  {filtered.map((id) => (
                    <option key={id} value={id}>
                      {id}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => pick(setUploadPath, '选择 Mark Scheme PDF')}>
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
            <input
              value={startPage}
              onChange={(e) => setStartPage(e.target.value)}
              placeholder="自动"
              inputMode="numeric"
              className={`mt-1 w-full ${SELECT}`}
              style={{ cursor: 'text', userSelect: 'text' }}
            />
            <span className="mt-1 block text-micro text-muted">默认留空，自动检测</span>
          </label>
        )}

        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() =>
              pick(
                setAnswerPath,
                isMcq ? '选择已批注 QP PDF' : '选择答卷 PDF (GoodNotes 导出)',
              )
            }
          >
            {isMcq ? '选择已批注 QP PDF' : '选择答卷 PDF'}
          </Button>
          <span className="min-w-0 flex-1 truncate text-caption text-muted">
            {answerPath ? fileName(answerPath) : '未选择文件（可稍后再选）'}
          </span>
        </div>
        {isMcq && (
          <div className="text-caption text-muted">
            上传在 GoodNotes 中批注过的试卷（圈出/写出每题答案）。
          </div>
        )}

        {!isMcq && !graderReady && (
          <Banner tone="warn" title="请先在设置中配置 Grader API 凭证" />
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button tone="accent" onClick={() => parse(false)} disabled={!canParse}>
            {answerPath && !isMcq ? '解析 Mark Scheme 与答卷' : '解析 Mark Scheme'}
          </Button>
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

      {msProgress && <Banner tone="warn" title={msProgress} />}
      {scanNote && <Banner tone="ok" title={scanNote} />}
      {error && <Banner tone="bad" title={error} />}

      {analysis?.ready && !busy && (
        <Banner
          tone="ok"
          title={
            `已解析 ${analysis.paper_id} — 共 ${Object.keys(analysis.questions ?? {}).length} 题, ` +
            `总分为 ${analysis.total_marks}` +
            (analysis.total_pages
              ? `；答卷 ${analysis.total_pages} 页，识别 ${analysis.matched?.length ?? 0}/${
                  Object.keys(analysis.questions ?? {}).length
                } 题`
              : '')
          }
        />
      )}
    </div>
  )
}
