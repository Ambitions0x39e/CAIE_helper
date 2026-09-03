import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import type { DownloadSource, GradeThreshold } from '../../lib/types'
import { Button } from '../../ui/Button'
import { notify } from '../../ui/Toast'
import { sortGrades } from './columns'
import { SessionPicker } from './SessionPicker'
import { type Session, gtPaperId, sessionCode } from './session'

/** Two-digit components become full paper ids: 9701 + w25 + 14 → 9701_w25_qp_14. */
function papersFor(syllabus: string, session: string, opt: GradeThreshold): string[] {
  return opt.components.map((c) => `${syllabus}_${session}_qp_${c}`)
}

type Doc = { syllabus_id: string; session: string; options: GradeThreshold[] }

export function Gt({ source }: { source: DownloadSource }) {
  const [session, setSession] = useState<Session | null>(null)
  const [busy, setBusy] = useState(false)
  const [doc, setDoc] = useState<Doc | null>(null)
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set())
  const [onDisk, setOnDisk] = useState<ReadonlySet<string>>(new Set())
  const [progress, setProgress] = useState<string | null>(null)

  const refreshOnDisk = () =>
    api()
      .then((a) => a.downloaded_ids())
      .then((ids) => setOnDisk(new Set(ids)))
      .catch(() => setOnDisk(new Set()))

  useEffect(() => {
    refreshOnDisk()
  }, [])

  const grades = useMemo(
    () => (doc ? sortGrades(doc.options.flatMap((o) => Object.keys(o.thresholds))) : []),
    [doc],
  )

  /** Papers for every ticked option, de-duplicated — options share components. */
  const selectedPapers = useMemo(() => {
    if (!doc) return []
    const out = new Set<string>()
    for (const opt of doc.options) {
      if (picked.has(opt.option)) {
        for (const p of papersFor(doc.syllabus_id, doc.session, opt)) out.add(p)
      }
    }
    return [...out]
  }, [doc, picked])

  const lookUp = async () => {
    if (!session || busy) return
    setBusy(true)
    setDoc(null)
    setPicked(new Set())
    try {
      const a = await api()
      // The threshold PDF itself only exists on CIEFrank; the papers an option
      // pulls in are ordinary QPs and follow the tab's source.
      const dl = await a.download_paper(gtPaperId(session), 'CIEFrank')
      if (!dl.success || !dl.qp_path) {
        notify('bad', `下载失败: ${dl.error ?? '没有拿到文件路径'}`)
        return
      }
      const parsed = await a.parse_gt(dl.qp_path, sessionCode(session))
      if (!parsed.success) {
        notify('bad', parsed.error)
        return
      }
      setDoc(parsed)
      notify('ok', `已下载: ${gtPaperId(session)}`)
    } catch (err) {
      notify('bad', String(err instanceof Error ? err.message : err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = (option: string) => {
    const next = new Set(picked)
    if (!next.delete(option)) next.add(option)
    setPicked(next)
  }

  const batchDownload = async () => {
    if (busy || selectedPapers.length === 0) return
    setBusy(true)
    const failures: string[] = []
    try {
      const a = await api()
      for (const [i, paperId] of selectedPapers.entries()) {
        setProgress(`下载中 ${i + 1}/${selectedPapers.length} — ${paperId}`)
        const dl = await a.download_paper(paperId, source)
        if (!dl.success) failures.push(`${paperId}: ${dl.error}`)
      }
    } catch (err) {
      failures.push(String(err instanceof Error ? err.message : err))
    } finally {
      setProgress(null)
      setBusy(false)
      setPicked(new Set())
      notify(
        failures.length ? 'bad' : 'ok',
        failures.length
          ? `${failures.length}/${selectedPapers.length} 份失败 — ${failures[0]}`
          : `已下载 ${selectedPapers.length} 份`,
      )
      refreshOnDisk()
    }
  }

  const prefix = doc ? `${doc.syllabus_id}_${doc.session}_qp_` : ''

  return (
    <div className="space-y-4">
      <div className="rounded-ui border border-hairline bg-panel p-4.5 space-y-3">
        <SessionPicker onChange={setSession} />
        <Button tone="accent" onClick={lookUp} disabled={busy || !session}>
          查询分数线
        </Button>
      </div>

      {doc && (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-caption text-muted">
              共 {doc.options.length} 个 option · 已勾选 {picked.size}
              {selectedPapers.length > 0 && `，合计 ${selectedPapers.length} 份卷子（已去重）`}
            </span>
            <Button
              tone="accent"
              onClick={batchDownload}
              disabled={busy || selectedPapers.length === 0}
            >
              批量下载
            </Button>
            <Button onClick={() => setPicked(new Set(doc.options.map((o) => o.option)))}>
              全选
            </Button>
            <Button onClick={() => setPicked(new Set())}>清空</Button>
          </div>

          <div className="text-section font-bold">
            {doc.syllabus_id} · {doc.session} — 共 {doc.options.length} 个 option
          </div>

          <p className="text-caption text-muted">
            卷号 = {prefix}&lt;卷子列的号&gt;，例如 {prefix}
            {doc.options[0].components[0]}。勾选 option 即选中它的整套卷子；
            <span className="font-bold text-ok">绿色</span>＝本地已有。
          </p>

          {progress && <div className="text-caption text-muted">{progress}</div>}

          <div className="overflow-x-auto rounded-ui border border-hairline bg-panel">
            <table className="w-full border-collapse text-body">
              <thead>
                <tr className="border-b border-hairline text-caption text-muted">
                  <th className="w-8 p-2" />
                  <th className="p-2.5 text-left font-normal">Option</th>
                  <th className="p-2.5 text-right font-normal">满分</th>
                  {grades.map((g) => (
                    <th key={g} className="p-2.5 text-right font-normal">
                      {g}
                    </th>
                  ))}
                  <th className="p-2.5 text-left font-normal">卷子</th>
                </tr>
              </thead>
              <tbody>
                {doc.options.map((opt) => {
                  const papers = papersFor(doc.syllabus_id, doc.session, opt)
                  return (
                    <tr
                      key={opt.option}
                      onClick={() => toggle(opt.option)}
                      className={`cursor-default border-b border-hairline last:border-0 ${
                        picked.has(opt.option) ? 'bg-raised' : ''
                      }`}
                    >
                      <td className="p-2">
                        <input
                          type="checkbox"
                          checked={picked.has(opt.option)}
                          onChange={() => toggle(opt.option)}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </td>
                      <td className="p-2.5 tabular-nums">{opt.option}</td>
                      <td className="p-2.5 text-right tabular-nums">{opt.max_weighted}</td>
                      {grades.map((g) => (
                        <td key={g} className="p-2.5 text-right tabular-nums">
                          {opt.thresholds[g] ?? '–'}
                        </td>
                      ))}
                      <td className="p-2">
                        <span className="flex flex-wrap gap-1.5 tabular-nums">
                          {opt.components.map((c, i) => (
                            <span
                              key={c}
                              title={papers[i] + (onDisk.has(papers[i]) ? '（本地已有）' : '')}
                              className={onDisk.has(papers[i]) ? 'font-medium text-ok' : ''}
                            >
                              {c}
                            </span>
                          ))}
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
