import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import type { SyllabusConfig } from '../../lib/types'
import { Button } from '../../ui/Button'
import { Select } from '../../ui/Select'
import { notify } from '../../ui/Toast'
import { compactIds } from './compact'
import { SubPage } from './SubPage'

/** pastpapers.co folder names, copied off its A Level and IGCSE directories.
 * They cannot be built from the config's subject names: 9231 is
 * `mathematics-further`, 9618 carries its first examination year, 0510 is
 * `english-second-language-oral-endorsement`. */
const PASTPAPERS_FOLDERS: Record<string, string> = {
  '0413': 'physical-education-0413',
  '0450': 'business-studies-0450',
  '0452': 'accounting-0452',
  '0455': 'economics-0455',
  '0460': 'geography-0460',
  '0470': 'history-0470',
  '0478': 'computer-science-0478',
  '0500': 'english-first-language-0500',
  '0509': 'chinese-first-language-0509',
  '0510': 'english-second-language-oral-endorsement-0510',
  '0511': 'english-second-language-count-in-oral-0511',
  '0580': 'mathematics-0580',
  '0606': 'mathematics-additional-0606',
  '0610': 'biology-0610',
  '0620': 'chemistry-0620',
  '0625': 'physics-0625',
  '9093': 'english-9093',
  '9231': 'mathematics-further-9231',
  '9389': 'history-9389',
  '9396': 'physical-education-9396',
  '9489': 'history-9489',
  '9609': 'business-9609',
  '9618': 'computer-science-(for-first-examination-in-2021)-(9618)',
  '9696': 'geography-9696',
  '9698': 'psychology-9698',
  '9700': 'biology-9700',
  '9701': 'chemistry-9701',
  '9702': 'physics-9702',
  '9706': 'accounting-9706',
  '9707': 'business-studies-9707',
  '9708': 'economics-9708',
  '9709': 'mathematics-9709',
  '9713': 'aict-9713',
  '9715': 'chinese-9715',
  '9990': 'psychology-9990',
}

/** IGCSE codes start with 0; everything else in the config is A Level. */
function syllabusUrl(id: string): string {
  const level = id.startsWith('0') ? 'igcse' : 'a-level'
  return `https://pastpapers.co/caie/${level}/${PASTPAPERS_FOLDERS[id]}/syllabus-%26-specimen`
}

interface Stored {
  subject_id: string
  topic_count: number
  components: string[]
  path: string
}

export function SyllabusView({ onBack }: { onBack: () => void }) {
  const [items, setItems] = useState<Stored[] | null>(null)
  const [confirm, setConfirm] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)
  const [subjects, setSubjects] = useState<SyllabusConfig[]>([])
  const [subject, setSubject] = useState('')

  const load = () =>
    api()
      .then((a) => a.syllabuses_stored())
      .then(setItems)
      .catch(() => setItems([]))

  useEffect(() => {
    load()
    api()
      .then((a) => a.syllabuses())
      .then((list) => {
        const linked = list
          .filter((s) => s.syllabus_id in PASTPAPERS_FOLDERS)
          .sort((a, b) => a.syllabus_id.localeCompare(b.syllabus_id))
        setSubjects(linked)
        if (linked.length > 0) setSubject(linked[0].syllabus_id)
      })
      .catch(() => setSubjects([]))
  }, [])

  const forget = async (id: string) => {
    setConfirm(null)
    const r = await (await api()).forget_syllabus(id)
    notify(
      r.success ? 'ok' : 'warn',
      r.success ? `已删除 ${id} 的 syllabus` : `${id} 没有可删除的记录`,
    )
    load()
  }

  const importPdf = async () => {
    const a = await api()
    const path = await a.pick_pdf()
    if (!path) return
    setImporting(true)
    try {
      const r = await a.import_syllabus(path)
      notify(
        r.success ? 'ok' : 'bad',
        r.success ? `已导入 ${r.subject_id} 的 syllabus` : `导入失败: ${r.error ?? ''}`,
      )
    } finally {
      setImporting(false)
      load()
    }
  }

  return (
    <SubPage title="已存 syllabus" onBack={onBack}>
      <p className="text-caption text-muted">批改时按 topic 归类错题要靠它。</p>

      <div className="flex flex-wrap items-end gap-2">
        <Select
          className="min-w-60 flex-1"
          label="科目"
          value={subject}
          onChange={setSubject}
          options={subjects.map((s) => ({
            value: s.syllabus_id,
            label: `${s.syllabus_id} — ${s.name}`,
          }))}
        />
        <Button
          onClick={() => api().then((a) => a.open_external(syllabusUrl(subject)))}
          disabled={subject === ''}
        >
          去 pastpapers 下载
        </Button>
        <Button onClick={importPdf} disabled={importing}>
          {importing ? '解析中…' : '选择 syllabus PDF'}
        </Button>
      </div>

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
