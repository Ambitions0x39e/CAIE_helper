import type { QuerySeason } from '../../lib/types'

/** CIE's season codes — the letter in the middle of a paper id. */
export const SEASONS: readonly { code: QuerySeason; label: string }[] = [
  { code: 'm', label: 'March' },
  { code: 's', label: 'Summer' },
  { code: 'w', label: 'Winter' },
]

/** Earliest year CIEFrank holds anything for. */
export const FIRST_YEAR = 2004

export interface Session {
  syllabus: string
  year: string
  season: QuerySeason
}

/** `Winter` + `2025` → `w25`, the middle segment of a paper id. */
export function sessionCode(s: Session): string {
  return `${s.season}${s.year.slice(-2)}`
}

/** This session's grade-threshold file, e.g. `9701_w25_gt`. */
export function gtPaperId(s: Session): string {
  return `${s.syllabus}_${sessionCode(s)}_gt`
}
