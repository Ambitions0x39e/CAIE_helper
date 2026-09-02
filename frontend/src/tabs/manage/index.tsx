import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import type { PaperRecord, SyllabusConfig } from '../../lib/types'
import { PushTrack } from '../../ui/PushTrack'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { Mistakes } from './Mistakes'
import { Organize } from './Organize'
import { Overview } from './Overview'

const SECTIONS = [
  { id: 'overview', label: '总览' },
  { id: 'organize', label: '整理' },
  { id: 'mistakes', label: '错题' },
] as const
type SectionId = (typeof SECTIONS)[number]['id']

export function ManageTab() {
  const [section, setSection] = useState<SectionId>('overview')
  const [dir, setDir] = useState(1)
  const [papers, setPapers] = useState<PaperRecord[]>([])
  const [syllabuses, setSyllabuses] = useState<SyllabusConfig[]>([])

  const index = SECTIONS.findIndex((s) => s.id === section)

  // 总览 and 整理 read the same rows, so they are loaded once here and an
  // action in 整理 refreshes both.
  const reload = useCallback(() => {
    api()
      .then((a) => Promise.all([a.papers(), a.syllabuses()]))
      .then(([p, s]) => {
        setPapers(p)
        setSyllabuses(s)
      })
      .catch(() => {
        setPapers([])
        setSyllabuses([])
      })
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const go = (id: SectionId) => {
    setDir(SECTIONS.findIndex((s) => s.id === id) > index ? 1 : -1)
    setSection(id)
  }

  return (
    <div className="space-y-4">
      <SegmentedStrip items={SECTIONS} value={section} onChange={go} />
      <PushTrack step={index} dir={dir}>
        {section === 'overview' ? (
          <Overview papers={papers} syllabuses={syllabuses} />
        ) : section === 'organize' ? (
          <Organize papers={papers} syllabuses={syllabuses} reload={reload} />
        ) : (
          <Mistakes />
        )}
      </PushTrack>
    </div>
  )
}
