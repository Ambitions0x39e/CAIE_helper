import { useEffect, useState } from 'react'
import type { Intent } from '../../lib/commands'
import { PushTrack } from '../../ui/PushTrack'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { Exports } from './Exports'
import { Mistakes } from './Mistakes'
import { Topics } from './Topics'

const SECTIONS = [
  { id: 'topics', label: '专项练习' },
  { id: 'mistakes', label: '错题本' },
  { id: 'exports', label: '导出记录' },
] as const
type SectionId = (typeof SECTIONS)[number]['id']

export function PracticeTab({
  intent,
  onConsumed,
  navigate,
}: {
  intent?: Intent | null
  onConsumed?: () => void
  /** Hands an intent to another tab — a hand-back lands on 批改. */
  navigate?: (intent: Intent) => void
}) {
  const [section, setSection] = useState<SectionId>('topics')
  const [dir, setDir] = useState(1)
  /** The palette's request, held for 错题本, which reads the grouping and the
   * topic out of it. Held as the object so asking twice for the same thing is
   * two distinct requests. */
  const [sub, setSub] = useState<Intent | null>(null)

  const index = SECTIONS.findIndex((s) => s.id === section)

  const go = (id: SectionId) => {
    setDir(SECTIONS.findIndex((s) => s.id === id) > index ? 1 : -1)
    setSection(id)
  }

  useEffect(() => {
    if (!intent || intent.tab !== 'practice') return
    const target = SECTIONS.find((s) => s.id === intent.view)?.id
    if (target) go(target)
    setSub(intent)
    onConsumed?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intent])

  return (
    <div className="space-y-4">
      <SegmentedStrip items={SECTIONS} value={section} onChange={go} />
      <PushTrack step={index} dir={dir}>
        {section === 'topics' ? (
          <Topics />
        ) : section === 'mistakes' ? (
          <Mistakes intent={sub} />
        ) : (
          <Exports navigate={navigate} />
        )}
      </PushTrack>
    </div>
  )
}
