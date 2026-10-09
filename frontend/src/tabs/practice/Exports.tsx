import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import type { ExportRecord } from '../../lib/types'
import { Button } from '../../ui/Button'
import { notify } from '../../ui/Toast'

const when = (iso: string) =>
  new Date(iso).toLocaleString('zh-CN', { dateStyle: 'short', timeStyle: 'short' })

export function Exports() {
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
        </div>
      ))}
    </div>
  )
}
