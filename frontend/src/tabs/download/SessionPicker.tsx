import { useEffect, useRef, useState } from 'react'
import { api } from '../../lib/bridge'
import type { QuerySeason, SyllabusConfig } from '../../lib/types'
import { FIRST_YEAR, SEASONS, type Session } from './session'

const SELECT =
  'rounded-ui border border-hairline bg-raised px-2 py-1.5 text-body text-ink'

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

  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="min-w-0 flex-1">
        <span className="block text-caption text-muted">科目</span>
        <select
          className={`mt-1 w-full ${SELECT}`}
          value={syllabus}
          onChange={(e) => setSyllabus(e.target.value)}
        >
          {syllabuses.map((s) => (
            <option key={s.syllabus_id} value={s.syllabus_id}>
              {s.syllabus_id} — {s.name}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span className="block text-caption text-muted">年份</span>
        <select
          className={`mt-1 ${SELECT}`}
          value={year}
          onChange={(e) => setYear(e.target.value)}
        >
          {years.map((y) => (
            <option key={y} value={String(y)}>
              {y}
            </option>
          ))}
        </select>
      </label>

      <label>
        <span className="block text-caption text-muted">考季</span>
        <select
          className={`mt-1 ${SELECT}`}
          value={season}
          onChange={(e) => setSeason(e.target.value as QuerySeason)}
        >
          {SEASONS.map((s) => (
            <option key={s.code} value={s.code}>
              {s.label}
            </option>
          ))}
        </select>
      </label>
    </div>
  )
}
