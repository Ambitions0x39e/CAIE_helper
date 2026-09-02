/** Derived facts about a set of papers.
 *
 * Everything here is arithmetic the UI reads out loud, and every one of these
 * is silent when wrong — a donut whose slices do not add up still draws a full
 * ring, and a subject that falls through to the fallback glyph still shows *a*
 * glyph. They are pinned in papers.test.ts for that reason.
 */
import type { PaperRecord } from './types'

/** How a set of papers splits, counting **one unit per paper, not per mark**.
 *
 * A pending paper has no `score_total` in data.csv — that column is only
 * written on completion — so the ring cannot be divided by marks. Each paper
 * is one unit instead: a completed one splits into earned/lost by its score
 * rate, a pending one is one whole pending unit.
 */
export interface Tally {
  total: number
  earned: number
  lost: number
  pending: number
}

export function tally(records: readonly PaperRecord[]): Tally {
  let done = 0
  let earned = 0
  for (const r of records) {
    if (r.status !== 'Completed') continue
    done++
    earned += (r.percentage ?? 0) / 100
  }
  return {
    total: records.length,
    earned,
    lost: done - earned,
    pending: records.length - done,
  }
}

/** Subject glyph keywords. **Order is priority — first match wins.**
 * "Further Mathematics" has to precede "Mathematics" or it lands on the
 * plain-maths glyph. Matching on the subject *name* rather than the four-digit
 * code is what lets one entry cover a subject at both IGCSE and A Level
 * (0620 and 9701 are both Chemistry) without touching this table when a new
 * code is added to syllabus_config.json. */
export const SUBJECT_KEYWORDS: readonly (readonly [string, string])[] = [
  ['Chemistry', 'flask'],
  ['Physics', 'bolt'],
  ['Biology', 'dna'],
  ['Further Mathematics', 'sigma'],
  ['Mathematics', 'calculator'],
  ['Computer Science', 'terminal'],
  ['ICT', 'monitor'],
  ['Psychology', 'brain'],
  ['Geography', 'globe'],
  ['History', 'scroll'],
  ['Accounting', 'bank'],
  ['Economics', 'trending-up'],
  ['Business', 'briefcase'],
  ['Physical Education', 'football'],
  ['English', 'languages'],
  ['Chinese', 'languages'],
]

/** Unrecognised subjects get a written-on sheet — more like "a paper" than a
 * blank one. */
export const FALLBACK_GLYPH = 'file-text'

export function subjectGlyph(syllabusName: string | undefined): string {
  if (!syllabusName) return FALLBACK_GLYPH
  for (const [keyword, glyph] of SUBJECT_KEYWORDS) {
    if (syllabusName.includes(keyword)) return glyph
  }
  return FALLBACK_GLYPH
}

/** `9702_s24_qp_11` → `9702`. */
export function syllabusIdOf(paperId: string): string {
  return paperId.slice(0, 4)
}

/** Sitting order of the three exam series within a year.
 *
 * March (`m`) is the Feb/March series, `s` the May/June one and `w` the
 * Oct/Nov one. Anything else sorts after all three rather than being dropped,
 * so an id this table has not seen still appears in the list. */
const SERIES: Record<string, number> = { m: 0, s: 1, w: 2 }

/** `9709_s23_qp_12` → the year and series it was sat in. */
function sitting(paperId: string): [number, number] {
  const code = paperId.split('_')[1] ?? ''
  const year = Number(code.slice(1))
  return [
    Number.isFinite(year) ? year : Number.POSITIVE_INFINITY,
    SERIES[code[0]] ?? Object.keys(SERIES).length,
  ]
}

/** Chronological order: year, then March → Summer → Winter, then paper number.
 *
 * Sorting the ids as plain strings looks right on one year and is wrong across
 * two — the series letter sits left of the year, so `m24` lands before `s23`
 * and every March paper the user owns is bunched at the top of the list. */
export function comparePaperIds(a: string, b: string): number {
  const [ay, as] = sitting(a)
  const [by, bs] = sitting(b)
  return ay - by || as - bs || a.localeCompare(b)
}
