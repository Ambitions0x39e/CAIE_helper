import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { PushTrack } from '../../ui/PushTrack'
import { About } from './About'
import { GraderView } from './GraderView'
import { MailView } from './MailView'
import { SyllabusView } from './SyllabusView'

const PAGES = [
  { id: 'mail', label: 'SMTP / GoodNotes', hint: '批改完把卷子发去 GoodNotes' },
  { id: 'grader', label: 'Grader API', hint: '批改用的视觉模型凭证' },
  { id: 'syllabus', label: '已存 syllabus', hint: '错题按 topic 归类的依据' },
  { id: 'about', label: '关于', hint: '版本与更新' },
] as const

type PageId = (typeof PAGES)[number]['id']

/** Menu on the left of the track, the chosen sub-page on the right — the two
 * panes the drawer pushes between. */
const MENU = 0
const SUB = 1

export function SettingsTab() {
  const [page, setPage] = useState<PageId | null>(null)

  const back = () => setPage(null)

  return (
    <PushTrack step={page === null ? MENU : SUB} dir={page === null ? -1 : 1}>
      {page === null ? (
        <div className="overflow-hidden rounded-ui border border-hairline bg-panel">
          {PAGES.map((p, i) => (
            <button
              key={p.id}
              onClick={() => setPage(p.id)}
              className={`flex w-full items-center gap-3 p-3 text-left hover:bg-raised
                          ${i > 0 ? 'border-t border-hairline' : ''}`}
              style={{ transitionDuration: 'var(--dur-fast)' }}
            >
              <span className="min-w-0 flex-1">
                <span className="block text-body">{p.label}</span>
                <span className="block text-caption text-muted">{p.hint}</span>
              </span>
              <ChevronRight className="size-4 shrink-0 text-faint" aria-hidden />
            </button>
          ))}
        </div>
      ) : page === 'mail' ? (
        <MailView onBack={back} />
      ) : page === 'grader' ? (
        <GraderView onBack={back} />
      ) : page === 'syllabus' ? (
        <SyllabusView onBack={back} />
      ) : (
        <About onBack={back} />
      )}
    </PushTrack>
  )
}
