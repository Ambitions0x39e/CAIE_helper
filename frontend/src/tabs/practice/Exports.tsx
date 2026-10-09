import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import type { Intent } from '../../lib/commands'
import type { ExportRecord } from '../../lib/types'
import { Button } from '../../ui/Button'
import { notify } from '../../ui/Toast'
import { abort, begin } from '../mark/run'

const when = (iso: string) =>
  new Date(iso).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' })

export function Exports({ navigate }: { navigate?: (intent: Intent) => void }) {
  const [records, setRecords] = useState<ExportRecord[] | null>(null)

  useEffect(() => {
    api()
      .then((a) => a.exports())
      .then(setRecords)
      .catch(() => setRecords([]))
  }, [])

  const saveBlank = async (id: string) => {
    const r = await (await api()).save_export_blank(id)
    if (r.cancelled) return
    notify(r.success ? 'ok' : 'bad', r.success ? `已保存 → ${r.path}` : (r.error ?? '保存失败'))
  }

  /** Pick the worked PDF, start grading it, and land on 批改's results —
   * from there the flow is a whole paper's. */
  const handBack = async (record: ExportRecord) => {
    const a = await api()
    const path = await a.pick_pdf()
    if (!path) return
    begin(record.question_count, record.kind)
    const r = await a.start_handback(record.export_id, path)
    if (!r.success) {
      abort()
      notify('bad', r.error ?? '无法开始批改')
      return
    }
    navigate?.({ tab: 'mark', view: 'results' })
  }

  const answers = async (id: string) => {
    const r = await (await api()).export_answers(id)
    if (r.cancelled) return
    if (!r.success) {
      notify('bad', r.error ?? '导出失败')
      return
    }
    const warned = r.warnings ?? []
    notify(
      warned.length ? 'warn' : 'ok',
      warned.length ? `已导出 → ${r.path}；${warned.join('；')}` : `已导出 → ${r.path}`,
    )
  }

  if (records === null) {
    return <div className="text-caption text-muted">读取中…</div>
  }
  if (records.length === 0) {
    return (
      <div className="rounded-ui border border-hairline bg-panel p-6 text-caption text-muted">
        还没有导出记录。
      </div>
    )
  }

  return (
    <div className="divide-y divide-hairline rounded-ui border border-hairline bg-panel">
      {records.map((r) => (
        <div key={r.export_id} className="flex items-center gap-3 p-2.5">
          <span className="min-w-0 truncate tabular-nums">{r.title}</span>
          <span className="ml-auto shrink-0 text-caption text-muted tabular-nums">
            {when(r.created_at)} · {r.question_count} 题 · {r.graded_at ? '已批改' : '未交回'}
          </span>
          <Button onClick={() => saveBlank(r.export_id)}>保存空白卷</Button>
          <Button tone="accent" onClick={() => handBack(r)}>
            交回批改
          </Button>
          <Button onClick={() => answers(r.export_id)} disabled={!r.graded_at}>
            答案
          </Button>
        </div>
      ))}
    </div>
  )
}
