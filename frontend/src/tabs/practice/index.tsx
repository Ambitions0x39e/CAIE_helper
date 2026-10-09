import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { PRACTICE_JOB, onJobEvent } from '../../lib/jobs'
import type { QuerySeason, SyllabusConfig } from '../../lib/types'
import { Button } from '../../ui/Button'
import { Select } from '../../ui/Select'
import { notify } from '../../ui/Toast'
import { FIRST_YEAR, SEASONS } from '../download/session'

const thisYear = new Date().getFullYear()
const YEARS: string[] = []
for (let y = thisYear; y >= FIRST_YEAR; y--) YEARS.push(String(y))
const YEAR_OPTIONS = YEARS.map((y) => ({ value: y, label: y }))
const SEASON_OPTIONS = SEASONS.map((s) => ({ value: s.code, label: s.label }))

export function PracticeTab() {
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
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState<string | null>(null)

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

  useEffect(
    () =>
      onJobEvent((e) => {
        if (e.type === 'practice_progress') {
          setProgress(`${e.stage} ${e.done}/${e.total} · ${e.paper}`)
        } else if (e.type === 'practice_ready') {
          setProgress(null)
          api()
            .then((a) => a.save_practice())
            .then((r) => {
              if (r.cancelled) return
              if (!r.success) {
                notify('bad', r.error ?? '保存失败')
                return
              }
              notify(
                e.warnings.length ? 'warn' : 'ok',
                e.warnings.length
                  ? `${e.count} 道题 → ${r.path}；${e.warnings.join('；')}`
                  : `${e.count} 道题 → ${r.path}`,
              )
            })
            .catch((err) => notify('bad', String(err instanceof Error ? err.message : err)))
        } else if (e.type === 'error' && e.job === PRACTICE_JOB) {
          notify('bad', e.message)
        } else if (e.type === 'finished' && e.job === PRACTICE_JOB) {
          setBusy(false)
          setProgress(null)
        }
      }),
    [],
  )

  const toggle = (id: string) => {
    const next = new Set(picked)
    if (!next.delete(id)) next.add(id)
    setPicked(next)
  }

  const generate = async () => {
    setBusy(true)
    const r = await (await api()).start_practice(
      subject, component, Number(fromYear), fromSeason, Number(toYear), toSeason, [...picked],
    )
    if (!r.success) {
      setBusy(false)
      notify('bad', r.error ?? '生成失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="text-section font-bold">专项练习</div>

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
        <Button tone="accent" onClick={generate} disabled={busy || picked.size === 0}>
          生成
        </Button>
        {progress && <span className="text-caption tabular-nums text-muted">{progress}</span>}
      </div>
    </div>
  )
}
