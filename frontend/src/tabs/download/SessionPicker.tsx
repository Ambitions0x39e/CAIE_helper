import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/bridge'
import { Select } from '../../ui/Select'
import type { QuerySeason, SyllabusConfig } from '../../lib/types'
import { FIRST_YEAR, SEASONS, type Session } from './session'

/** Subject / year / season. Shared by 按考季 and 分数线 — they pick the same
 * thing, and building the id from the parts is what stops it being mistyped.
 *
 * Uncontrolled on purpose. A `value` prop would mean the parent has to invent a
 * session before the syllabus list has loaded, and the picker would then have
 * to correct it — an effect that both reads and writes the same prop. Owning
 * the three fields here and reporting upward leaves one direction of flow.
 */
export function SessionPicker({ onChange }: { onChange: (s: Session) => void }) {
  const [syllabuses, setSyllabuses] = useState<SyllabusConfig[]>([])
  const [syllabus, setSyllabus] = useState('')
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [season, setSeason] = useState<QuerySeason>('m')

  // Held in a ref so the report-upward effect below depends on the session
  // fields alone; an inline arrow from the parent changes identity every render
  // and would re-fire it forever.
  const report = useRef(onChange)
  useEffect(() => {
    report.current = onChange
  })

  useEffect(() => {
    api()
      .then((a) => a.syllabuses())
      .then((list) => {
        const sorted = [...list].sort((a, b) =>
          a.syllabus_id.localeCompare(b.syllabus_id),
        )
        setSyllabuses(sorted)
        if (sorted.length > 0) setSyllabus(sorted[0].syllabus_id)
      })
      .catch(() => setSyllabuses([]))
  }, [])

  useEffect(() => {
    if (syllabus) report.current({ syllabus, year, season })
  }, [syllabus, year, season])

  const years: number[] = []
  for (let y = new Date().getFullYear(); y >= FIRST_YEAR; y--) years.push(y)

  // 70 / 10 / 20 of the row. The subject line carries a code and a name; the
  // other two are a four-digit year and one word.
  return (
    <div className="flex items-end gap-2">
      <Select
        className="min-w-0 grow-[7] basis-0"
        label="科目"
        value={syllabus}
        onChange={setSyllabus}
        options={syllabuses.map((s) => ({
          value: s.syllabus_id,
          label: `${s.syllabus_id} — ${s.name}`,
        }))}
      />
      <Select
        className="min-w-0 grow basis-0"
        label="年份"
        value={year}
        onChange={setYear}
        options={years.map((y) => ({ value: String(y), label: String(y) }))}
      />
      <Select
        className="min-w-0 grow-[2] basis-0"
        label="考季"
        value={season}
        onChange={(v) => setSeason(v as QuerySeason)}
        options={SEASONS.map((s) => ({ value: s.code, label: s.label }))}
      />
    </div>
  )
}
