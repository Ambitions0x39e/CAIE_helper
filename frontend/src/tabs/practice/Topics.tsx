import { useEffect, useState, useSyncExternalStore } from 'react'
import { api } from '../../lib/bridge'
import type { QuerySeason, SyllabusConfig } from '../../lib/types'
import { Select } from '../../ui/Select'
import { StepButton } from '../../ui/StepButton'
import { FIRST_YEAR, SEASONS } from '../download/session'
import { getSnapshot, startPractice, subscribe } from './job'
import { practiceSteps } from './steps'

const thisYear = new Date().getFullYear()
const YEARS: string[] = []
for (let y = thisYear; y >= FIRST_YEAR; y--) YEARS.push(String(y))
const YEAR_OPTIONS = YEARS.map((y) => ({ value: y, label: y }))
const SEASON_OPTIONS = SEASONS.map((s) => ({ value: s.code, label: s.label }))

export function Topics() {
  const [syllabuses, setSyllabuses] = useState<SyllabusConfig[]>([])
  const [subject, setSubject] = useState('')
  const [component, setComponent] = useState('')
  const [fromYear, setFromYear] = useState(String(thisYear - 2))
  const [fromSeason, setFromSeason] = useState<QuerySeason>('s')
  const [toYear, setToYear] = useState(String(thisYear - 1))
  const [toSeason, setToSeason] = useState<QuerySeason>('w')
  const [topics, setTopics] = useState<Record<string, string> | null>(null)
  const [topicError, setTopicError] = useState<string | null>(null)
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set())
  const { busy, stage, failed } = useSyncExternalStore(subscribe, getSnapshot)

  useEffect(() => {
    api()
      .then((a) => a.syllabuses())
      .then((list) => {
        const sorted = [...list].sort((a, b) => a.syllabus_id.localeCompare(b.syllabus_id))
        setSyllabuses(sorted)
        if (sorted.length > 0) setSubject(sorted[0].syllabus_id)
      })
      .catch(() => setSyllabuses([]))
  }, [])

  const paperTypes = syllabuses.find((s) => s.syllabus_id === subject)?.paper_types ?? []

  useEffect(() => {
    setComponent(paperTypes[0]?.digit ?? '')
    // Only a new subject resets the component; paperTypes follows from it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [subject, syllabuses])

  useEffect(() => {
    setTopics(null)
    setTopicError(null)
    setPicked(new Set())
    if (!subject || !component) return
    let live = true
    api()
      .then((a) => a.practice_topics(subject, component))
      .then((r) => {
        if (!live) return
        if (r.success) setTopics(r.topics ?? {})
        else setTopicError(r.error ?? '取不到 topic')
      })
      .catch((err) => live && setTopicError(String(err instanceof Error ? err.message : err)))
    return () => {
      live = false
    }
  }, [subject, component])

  const toggle = (id: string) => {
    const next = new Set(picked)
    if (!next.delete(id)) next.add(id)
    setPicked(next)
  }

  const generate = () =>
    startPractice(subject, component, Number(fromYear), fromSeason, Number(toYear), toSeason, [...picked])

  return (
    <div className="space-y-4">
      <div className="flex items-end gap-2">
        <Select
          className="min-w-0 grow-[3] basis-0"
          label="科目"
          value={subject}
          onChange={setSubject}
          options={syllabuses.map((s) => ({ value: s.syllabus_id, label: `${s.syllabus_id} — ${s.name}` }))}
        />
        <Select
          className="min-w-0 grow-[2] basis-0"
          label="卷"
          value={component}
          onChange={setComponent}
          options={paperTypes.map((p) => ({ value: p.digit, label: `${p.digit} — ${p.name}` }))}
        />
      </div>

      <div className="flex items-end gap-2">
        <Select className="min-w-0 grow basis-0" label="从" value={fromYear} onChange={setFromYear} options={YEAR_OPTIONS} />
        <Select
          className="min-w-0 grow basis-0"
          value={fromSeason}
          onChange={(v) => setFromSeason(v as QuerySeason)}
          options={SEASON_OPTIONS}
        />
        <Select className="min-w-0 grow basis-0" label="到" value={toYear} onChange={setToYear} options={YEAR_OPTIONS} />
        <Select
          className="min-w-0 grow basis-0"
          value={toSeason}
          onChange={(v) => setToSeason(v as QuerySeason)}
          options={SEASON_OPTIONS}
        />
      </div>

      {topicError && <div className="text-caption text-warn">{topicError}</div>}
      {topics && (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(topics).map(([id, name]) => (
            <button
              key={id}
              onClick={() => toggle(id)}
              aria-pressed={picked.has(id)}
              disabled={busy}
              className={`rounded-ui border border-hairline px-2 py-0.5 text-caption
                          ${picked.has(id) ? 'bg-accent text-on-accent' : 'bg-panel text-muted hover:text-ink'}`}
            >
              {id} {name}
            </button>
          ))}
        </div>
      )}

      <div className="flex items-center gap-3">
        <StepButton
          running={busy}
          steps={practiceSteps(stage)}
          failed={failed}
          onClick={generate}
          disabled={picked.size === 0}
        >
          生成
        </StepButton>
      </div>
    </div>
  )
}
