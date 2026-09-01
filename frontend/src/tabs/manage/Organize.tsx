import { useEffect, useMemo, useState } from 'react'
import { FileText, Send, Trash2 } from 'lucide-react'
import { api } from '../../lib/bridge'
import { subjectGlyph, syllabusIdOf } from '../../lib/papers'
import type { PaperRecord, SyllabusConfig } from '../../lib/types'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { Glyph } from '../../ui/Glyph'
import { Overlay } from '../../ui/Overlay'
import { SegmentedStrip } from '../../ui/SegmentedStrip'

const LAYOUTS = [
  { id: 'icons', label: '图标' },
  { id: 'detail', label: '详细信息' },
] as const
type LayoutId = (typeof LAYOUTS)[number]['id']

/** What one paper can be made to do. The same four whether they are laid out
 * as circles over the icon or as buttons at the end of a row. */
interface Action {
  key: string
  label: string
  Icon: typeof FileText
  danger?: boolean
  run: () => void
}

type Act = (
  fn: (a: Awaited<ReturnType<typeof api>>) => Promise<{ success: boolean; error?: string | null }>,
  ok: string,
) => void

export function Organize({
  papers,
  syllabuses,
  reload,
}: {
  papers: PaperRecord[]
  syllabuses: SyllabusConfig[]
  reload: () => void
}) {
  const [layout, setLayout] = useState<LayoutId>('icons')
  const [hideCompleted, setHideCompleted] = useState(false)
  const [selected, setSelected] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [alsoFiles, setAlsoFiles] = useState(false)
  const [mailReady, setMailReady] = useState(false)
  const [note, setNote] = useState<{ tone: 'ok' | 'bad'; text: string } | null>(null)

  useEffect(() => {
    api()
      .then((a) => a.mail_ready())
      .then(setMailReady)
      .catch(() => setMailReady(false))
  }, [])

  const names = useMemo(
    () => new Map(syllabuses.map((s) => [s.syllabus_id, s.name])),
    [syllabuses],
  )

  const shown = useMemo(
    () => (hideCompleted ? papers.filter((p) => p.status !== 'Completed') : papers),
    [papers, hideCompleted],
  )

  const current = shown.find((p) => p.paper_id === selected) ?? null
  const pendingDelete = papers.find((p) => p.paper_id === deleting) ?? null

  const call: Act = (fn, ok) => {
    void (async () => {
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
    })()
  }

  const actionsOf = (p: PaperRecord): Action[] => {
    const acts: Action[] = [
      {
        key: 'qp',
        label: '打开 QP',
        Icon: FileText,
        run: () => call((a) => a.open_pdf(p.qp_path), '已在系统阅读器中打开 QP'),
      },
      {
        key: 'ms',
        label: '打开 MS',
        Icon: FileText,
        run: () => call((a) => a.open_pdf(p.ms_path), '已在系统阅读器中打开 MS'),
      },
    ]
    if (mailReady && p.qp_path) {
      acts.push({
        key: 'gn',
        label: '发送到 GoodNotes',
        Icon: Send,
        run: () =>
          call(
            (a) => a.send_to_goodnotes(p.paper_id, p.qp_path),
            `已发送 ${p.paper_id}`,
          ),
      })
    }
    acts.push({
      key: 'del',
      label: '删除',
      Icon: Trash2,
      danger: true,
      run: () => {
        setAlsoFiles(false)
        // The confirm sits in the list behind the detail panel, so the panel
        // has to step aside or the question is asked where nobody can see it.
        setSelected(null)
        setDeleting(p.paper_id)
      },
    })
    return acts
  }

  return (
    <div className="space-y-3">
      {/* The strip sits centred and the switch hard right, the same balance the
          two views are read with. */}
      <div className="flex items-center">
        <div className="flex-1" />
        <SegmentedStrip items={LAYOUTS} value={layout} onChange={setLayout} />
        <label className="flex flex-1 items-center justify-end gap-1.5 text-caption text-muted">
          <input
            type="checkbox"
            checked={hideCompleted}
            onChange={(e) => setHideCompleted(e.target.checked)}
          />
          隐藏已完成
        </label>
      </div>

      {note && <Banner tone={note.tone} title={note.text} />}

      {pendingDelete && (
        <div className="flex flex-wrap items-center gap-2 rounded-ui border border-hairline bg-panel p-3">
          <span className="text-caption text-bad">
            确定删除 {pendingDelete.paper_id}？
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
              const id = pendingDelete.paper_id
              setDeleting(null)
              setSelected(null)
              call((a) => a.delete_paper(id, alsoFiles), `已删除 ${id}`)
            }}
          >
            确认删除
          </Button>
          <Button onClick={() => setDeleting(null)}>取消</Button>
        </div>
      )}

      {shown.length === 0 ? (
        <div className="text-muted">没有匹配的记录。</div>
      ) : layout === 'icons' ? (
        <div className="flex flex-wrap gap-x-3 gap-y-5">
          {shown.map((p) => (
            <IconCell
              key={p.paper_id}
              paper={p}
              glyph={subjectGlyph(names.get(syllabusIdOf(p.paper_id)))}
              actions={actionsOf(p)}
            />
          ))}
        </div>
      ) : (
        <DetailList
          shown={shown}
          onSelect={setSelected}
          selected={selected}
          actionsOf={actionsOf}
        />
      )}

      <Overlay open={current !== null} onClose={() => setSelected(null)}>
        {current && (
          <PaperDetail
            paper={current}
            actions={actionsOf(current)}
            onAct={call}
            onClose={() => setSelected(null)}
          />
        )}
      </Overlay>
    </div>
  )
}

/** The icon cell's square, and one action circle inside it. */
const CELL = 96
const CIRCLE = 34

/** One paper as an icon. Clicking the icon turns that same square into a
 * two-by-two ring of its actions; clicking the square's empty ground turns it
 * back. The square keeps its size across the flip so the grid never reflows. */
function IconCell({
  paper,
  glyph,
  actions,
}: {
  paper: PaperRecord
  glyph: string
  actions: Action[]
}) {
  const [open, setOpen] = useState(false)
  const done = paper.status === 'Completed'

  return (
    <div className="w-29 shrink-0">
      <div
        onClick={() => setOpen(!open)}
        title={open ? '点空白处收起' : paper.paper_id}
        className="flex items-center justify-center"
        style={{ width: CELL, height: CELL, margin: '0 auto' }}
      >
        {open ? (
          <div className="grid grid-cols-2 gap-2">
            {actions.map((a) => (
              <button
                key={a.key}
                title={a.label}
                onClick={(e) => {
                  e.stopPropagation()
                  setOpen(false)
                  a.run()
                }}
                className={`flex items-center justify-center rounded-full border border-hairline
                            bg-panel hover:bg-raised ${a.danger ? 'text-bad' : 'text-accent'}`}
                style={{ width: CIRCLE, height: CIRCLE }}
              >
                <a.Icon className="size-4" aria-hidden />
              </button>
            ))}
          </div>
        ) : (
          <Glyph name={glyph} className={`size-15 ${done ? 'text-ok' : 'text-muted'}`} />
        )}
      </div>
      <div className="mt-0.5 text-center text-caption tabular-nums">{paper.paper_id}</div>
      <div
        className={`text-center text-micro tabular-nums ${
          paper.percentage === null ? 'text-muted' : 'text-ink'
        }`}
      >
        {paper.percentage === null ? '待完成' : `${Math.round(paper.percentage)}%`}
      </div>
    </div>
  )
}

function DetailList({
  shown,
  selected,
  onSelect,
  actionsOf,
}: {
  shown: PaperRecord[]
  selected: string | null
  onSelect: (id: string) => void
  actionsOf: (p: PaperRecord) => Action[]
}) {
  return (
    <div className="overflow-x-auto rounded-ui border border-hairline bg-panel">
      <table className="w-full border-collapse text-body">
        <thead>
          <tr className="border-b border-hairline bg-raised text-caption font-semibold text-muted">
            <th className="px-3 py-1.5 text-left font-semibold">Paper ID</th>
            <th className="px-3 py-1.5 text-left font-semibold">状态</th>
            <th className="px-3 py-1.5 text-left font-semibold">分数</th>
            <th className="px-3 py-1.5 text-left font-semibold">%</th>
            <th className="px-3 py-1.5 text-left font-semibold">时间</th>
            <th className="px-3 py-1.5 text-right font-semibold">操作</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((p) => {
            const done = p.status === 'Completed'
            return (
              <tr
                key={p.paper_id}
                onClick={() => onSelect(p.paper_id)}
                className={`cursor-default border-b border-hairline last:border-0
                            ${selected === p.paper_id ? 'bg-raised' : ''}`}
              >
                <td className="px-3 py-1 tabular-nums">{p.paper_id}</td>
                <td className={`px-3 py-1 text-caption ${done ? '' : 'text-muted'}`}>
                  {done ? '已完成' : '待完成'}
                </td>
                <td className="px-3 py-1 tabular-nums">
                  {p.score_raw === null || p.score_total === null
                    ? '—'
                    : `${p.score_raw}/${p.score_total}`}
                </td>
                <td className="px-3 py-1 tabular-nums">
                  {p.percentage === null ? '—' : `${p.percentage.toFixed(1)}%`}
                </td>
                <td className="px-3 py-1 text-caption text-muted tabular-nums">
                  {p.timestamp ? p.timestamp.slice(0, 16).replace('T', ' ') : ''}
                </td>
                <td className="px-3 py-1">
                  <div className="flex justify-end">
                    {actionsOf(p).map((a) => (
                      <button
                        key={a.key}
                        title={a.label}
                        onClick={(e) => {
                          e.stopPropagation()
                          a.run()
                        }}
                        className={`flex size-7 items-center justify-center rounded-ui
                                    hover:bg-raised ${a.danger ? 'text-bad' : 'text-accent'}`}
                      >
                        <a.Icon className="size-4" aria-hidden />
                      </button>
                    ))}
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/** One paper, filling the content area: what is on record, what can be done
 * with it, and the score form a row has no room for. */
function PaperDetail({
  paper,
  actions,
  onAct,
  onClose,
}: {
  paper: PaperRecord
  actions: Action[]
  onAct: Act
  onClose: () => void
}) {
  const [raw, setRaw] = useState(paper.score_raw?.toString() ?? '')
  const [total, setTotal] = useState(paper.score_total?.toString() ?? '')
  const done = paper.status === 'Completed'

  const facts: [string, string][] = [
    ['状态', done ? '已完成' : '待完成'],
    [
      '分数',
      paper.score_raw === null || paper.score_total === null
        ? '—'
        : `${paper.score_raw}/${paper.score_total}`,
    ],
    ['%', paper.percentage === null ? '—' : `${paper.percentage.toFixed(1)}%`],
    ['时间', paper.timestamp ? paper.timestamp.slice(0, 16).replace('T', ' ') : '—'],
    ['GoodNotes', paper.sent_to_gn ? '已发送' : '未发送'],
    ['QP', paper.qp_path || '—'],
    ['MS', paper.ms_path || '—'],
  ]

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <button onClick={onClose} className="text-caption text-muted hover:text-ink">
          返回
        </button>
        <span className="text-section font-bold tabular-nums">{paper.paper_id}</span>
        <div className="ml-auto flex gap-2">
          {actions.map((a) => (
            <Button key={a.key} onClick={a.run} className={a.danger ? 'text-bad' : ''}>
              {a.label}
            </Button>
          ))}
        </div>
      </div>

      <div className="rounded-ui border border-hairline bg-panel">
        {facts.map(([label, value], i) => (
          <div
            key={label}
            className={`flex items-baseline gap-4 px-3 py-1.5 ${
              i > 0 ? 'border-t border-hairline' : ''
            }`}
          >
            <span className="w-24 shrink-0 text-caption text-muted">{label}</span>
            <span className="selectable min-w-0 break-all tabular-nums">{value}</span>
          </div>
        ))}
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
    </div>
  )
}
