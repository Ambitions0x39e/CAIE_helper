import { useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { subjectGlyph, syllabusIdOf } from '../../lib/papers'
import type { PaperRecord, SyllabusConfig } from '../../lib/types'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { Glyph } from '../../ui/Glyph'
import { SegmentedStrip } from '../../ui/SegmentedStrip'

const LAYOUTS = [
  { id: 'detail', label: '详细' },
  { id: 'icons', label: '图标' },
] as const
type LayoutId = (typeof LAYOUTS)[number]['id']

export function Organize({
  papers,
  syllabuses,
  reload,
}: {
  papers: PaperRecord[]
  syllabuses: SyllabusConfig[]
  reload: () => void
}) {
  const [layout, setLayout] = useState<LayoutId>('detail')
  const [hideCompleted, setHideCompleted] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)

  const names = useMemo(
    () => new Map(syllabuses.map((s) => [s.syllabus_id, s.name])),
    [syllabuses],
  )

  const shown = useMemo(
    () => (hideCompleted ? papers.filter((p) => p.status !== 'Completed') : papers),
    [papers, hideCompleted],
  )

  const current = shown.find((p) => p.paper_id === selected) ?? null

  const call = async (fn: (a: Awaited<ReturnType<typeof api>>) => Promise<{ success: boolean; error?: string | null }>, ok: string) => {
    try {
      const result = await fn(await api())
      setNote(
        result.success
          ? { tone: 'ok', text: ok }
          : { tone: 'bad', text: result.error ?? '操作失败' },
      )
      if (result.success) reload()
    } catch (err) {
      setNote({ tone: 'bad', text: String(err instanceof Error ? err.message : err) })
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedStrip items={LAYOUTS} value={layout} onChange={setLayout} />
        <label className="flex items-center gap-1.5 text-caption text-muted">
          <input
            type="checkbox"
            checked={hideCompleted}
            onChange={(e) => setHideCompleted(e.target.checked)}
          />
          隐藏已完成
        </label>
        <span className="text-caption text-faint tabular-nums">{shown.length} 份</span>
      </div>

      {note && <Banner tone={note.tone} title={note.text} />}

      {shown.length === 0 ? (
        <div className="rounded-ui border border-hairline bg-panel p-6 text-caption text-muted">
          没有符合条件的卷子。
        </div>
      ) : layout === 'icons' ? (
        <div
          className="grid gap-2"
          style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(8.5rem, 1fr))' }}
        >
          {shown.map((p) => (
            <button
              key={p.paper_id}
              onClick={() => setSelected(p.paper_id)}
              className={`flex flex-col items-center gap-1.5 rounded-ui border border-hairline p-3
                          ${selected === p.paper_id ? 'bg-raised' : 'bg-panel hover:bg-raised'}`}
            >
              <Glyph
                name={subjectGlyph(names.get(syllabusIdOf(p.paper_id)))}
                className="size-6 text-muted"
              />
              <span className="w-full truncate text-center text-caption tabular-nums">
                {p.paper_id}
              </span>
              <span
                className={`text-micro ${p.status === 'Completed' ? 'text-ok' : 'text-faint'}`}
              >
                {p.percentage === null ? '未完成' : `${p.percentage}%`}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-ui border border-hairline bg-panel">
          <table className="w-full border-collapse text-body">
            <thead>
              <tr className="border-b border-hairline text-caption text-muted">
                <th className="p-2 text-left font-normal">卷号</th>
                <th className="p-2 text-left font-normal">科目</th>
                <th className="p-2 text-right font-normal">分数</th>
                <th className="p-2 text-left font-normal">状态</th>
                <th className="p-2 text-left font-normal">GN</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr
                  key={p.paper_id}
                  onClick={() => setSelected(p.paper_id)}
                  className={`cursor-default border-b border-hairline last:border-0
                              ${selected === p.paper_id ? 'bg-raised' : ''}`}
                >
                  <td className="p-2 tabular-nums">{p.paper_id}</td>
                  <td className="p-2 text-muted">
                    {names.get(syllabusIdOf(p.paper_id)) ?? '—'}
                  </td>
                  <td className="p-2 text-right tabular-nums">
                    {p.score_raw === null ? '–' : `${p.score_raw} / ${p.score_total}`}
                  </td>
                  <td className="p-2 text-caption">
                    <span className={p.status === 'Completed' ? 'text-ok' : 'text-muted'}>
                      {p.status === 'Completed' ? `已完成 ${p.percentage}%` : '未完成'}
                    </span>
                  </td>
                  <td className="p-2 text-caption text-muted">{p.sent_to_gn ? '已发送' : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {current && <PaperActions paper={current} onAct={call} onClose={() => setSelected(null)} />}
    </div>
  )
}

function PaperActions({
  paper,
  onAct,
  onClose,
}: {
  paper: PaperRecord
  onAct: (
    fn: (a: Awaited<ReturnType<typeof api>>) => Promise<{ success: boolean; error?: string | null }>,
    ok: string,
  ) => Promise<void>
  onClose: () => void
}) {
  const [raw, setRaw] = useState(paper.score_raw?.toString() ?? '')
  const [total, setTotal] = useState(paper.score_total?.toString() ?? '')
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [alsoFiles, setAlsoFiles] = useState(false)

  return (
    <div
      className="rounded-ui border border-hairline bg-raised p-4 space-y-3"
      style={{ boxShadow: 'var(--shadow-popover)' }}
    >
      <div className="flex items-center gap-2">
        <span className="text-subhead font-medium tabular-nums">{paper.paper_id}</span>
        <button onClick={onClose} className="ml-auto text-caption text-muted hover:text-ink">
          关闭
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          onClick={() => onAct((a) => a.open_pdf(paper.qp_path), '已在系统阅读器中打开 QP')}
          disabled={!paper.qp_path}
        >
          打开 QP
        </Button>
        <Button
          onClick={() => onAct((a) => a.open_pdf(paper.ms_path), '已在系统阅读器中打开 MS')}
          disabled={!paper.ms_path}
        >
          打开 MS
        </Button>
      </div>

      <div className="flex flex-wrap items-end gap-2">
        <label className="text-caption text-muted">
          得分
          <input
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            inputMode="decimal"
            className="ml-2 w-20 rounded-ui border border-hairline bg-panel px-2 py-1 text-body text-ink"
            style={{ cursor: 'text', userSelect: 'text' }}
          />
        </label>
        <label className="text-caption text-muted">
          满分
          <input
            value={total}
            onChange={(e) => setTotal(e.target.value)}
            inputMode="decimal"
            className="ml-2 w-20 rounded-ui border border-hairline bg-panel px-2 py-1 text-body text-ink"
            style={{ cursor: 'text', userSelect: 'text' }}
          />
        </label>
        <Button
          tone="accent"
          disabled={!raw || !total}
          onClick={() =>
            onAct(
              (a) => a.submit_score(paper.paper_id, Number(raw), Number(total)),
              '分数已记录',
            )
          }
        >
          提交分数
        </Button>
      </div>

      {/* Delete asks first and says what it will take — the files box is off by
          default, so the quick path removes the row and leaves the PDFs. */}
      <div className="flex flex-wrap items-center gap-2 border-t border-hairline pt-3">
        {confirmDelete ? (
          <>
            <span className="text-caption text-bad">
              确定删除 {paper.paper_id}？
            </span>
            <label className="flex items-center gap-1.5 text-caption text-muted">
              <input
                type="checkbox"
                checked={alsoFiles}
                onChange={(e) => setAlsoFiles(e.target.checked)}
              />
              连同本地 PDF 一起删
            </label>
            <Button
              onClick={() => {
                setConfirmDelete(false)
                onClose()
                void onAct(
                  (a) => a.delete_paper(paper.paper_id, alsoFiles),
                  `已删除 ${paper.paper_id}`,
                )
              }}
            >
              确认删除
            </Button>
            <Button onClick={() => setConfirmDelete(false)}>取消</Button>
          </>
        ) : (
          <Button onClick={() => setConfirmDelete(true)}>删除</Button>
        )}
      </div>
    </div>
  )
}
