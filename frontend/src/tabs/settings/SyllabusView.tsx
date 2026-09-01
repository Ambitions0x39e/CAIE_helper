import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { compactIds } from './compact'
import { SubPage } from './SubPage'

interface Stored {
  subject_id: string
  topic_count: number
  components: string[]
  path: string
}

export function SyllabusView({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<Stored[] | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)

  const load = () =>
    api()
      .then((a) => a.syllabuses_stored())
      .then(setItems)
      .catch(() => setItems([]))

  useEffect(() => {
    load()
  }, [])

  const forget = async (id: string) => {
    setConfirm(null)
    const r = await (await api()).forget_syllabus(id)
    setNote(r.success ? `已删除 ${id} 的 syllabus` : `${id} 没有可删除的记录`)
    load()
  }

  return (
    <SubPage title="已存 syllabus" onBack={onBack}>
      <p className="text-caption text-muted">
        批改时按 topic 归类错题要靠它。删掉之后下次批改会重新解析 ——
        那是一次要花钱的视觉模型调用，所以这里不做「一键清空」。
      </p>

      {note && <Banner tone="ok" title={note} />}

      {items === null ? (
        <div className="text-caption text-muted">读取中…</div>
      ) : items.length === 0 ? (
        <div className="rounded-ui border border-hairline bg-panel p-6 text-caption text-muted">
          还没有解析过任何 syllabus。
        </div>
      ) : (
        <div className="rounded-ui border border-hairline bg-panel">
          {items.map((s, i) => (
            <div
              key={s.subject_id}
              className={`flex flex-wrap items-center gap-x-4 gap-y-1 p-3 ${
                i > 0 ? 'border-t border-hairline' : ''
              }`}
            >
              <div className="min-w-40 flex-1">
                <div className="text-body tabular-nums">{s.subject_id}</div>
                <div className="text-caption text-muted tabular-nums">
                  {s.topic_count} 个 topic · 卷 {compactIds(s.components)}
                </div>
              </div>
              {confirm === s.subject_id ? (
                <div className="flex items-center gap-2">
                  <span className="text-caption text-bad">确定删除？</span>
                  <Button onClick={() => forget(s.subject_id)}>确认</Button>
                  <Button onClick={() => setConfirm(null)}>取消</Button>
                </div>
              ) : (
                <Button onClick={() => setConfirm(s.subject_id)}>删除</Button>
              )}
            </div>
          ))}
        </div>
      )}
    </SubPage>
  )
}
