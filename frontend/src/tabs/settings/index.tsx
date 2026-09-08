import { useEffect, useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { Intent } from '../../lib/commands'
import { PushTrack } from '../../ui/PushTrack'
import { About } from './About'
import { GraderView } from './GraderView'
import { MailView } from './MailView'
import { PaletteView } from './PaletteView'
import { SyllabusView } from './SyllabusView'
import { ThemeView } from './ThemeView'

const PAGES = [
  { id: 'mail', label: 'SMTP / GoodNotes', hint: '批改完把卷子发去 GoodNotes' },
  { id: 'grader', label: 'Grader API', hint: '批改用的视觉模型凭证' },
  { id: 'syllabus', label: '已存 syllabus', hint: '错题按 topic 归类的依据' },
  { id: 'theme', label: '主题', hint: '浅色、深色，或跟着系统走' },
  { id: 'palette', label: '命令面板', hint: 'Ctrl+K 唤起的那个' },
  { id: 'about', label: '关于', hint: '版本与更新' },
] as const

type PageId = (typeof PAGES)[number]['id']

/** Menu on the left of the track, the chosen sub-page on the right — the two
 * panes the drawer pushes between. */
const MENU = 0
const SUB = 1

export function SettingsTab({
  intent,
  onConsumed,
}: {
  intent?: Intent | null
  onConsumed?: () => void
}) {
  const [page, setPage] = useState<PageId | null>(null)

  const back = () => setPage(null)

  useEffect(() => {
    if (!intent || intent.tab !== 'settings') return
    const target = PAGES.find((p) => p.id === intent.view)?.id
    if (target) setPage(target)
    onConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent])

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
      ) : page === 'theme' ? (
        <ThemeView onBack={back} />
      ) : page === 'palette' ? (
        <PaletteView onBack={back} />
      ) : (
        <About onBack={back} />
      )}
    </PushTrack>
  )
}
