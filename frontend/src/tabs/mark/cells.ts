/** What the two question grids share.
 *
 * 核对 and 结果 show the same questions, so both lay them out the same way —
 * the grid the marks land in is the grid they were picked in, and a cell keeps
 * its place from one step to the next.
 */

/** Tracks, not a fixed column count: the cells divide whatever width there is,
 * so the window can be dragged narrow without the grid overflowing. */
export const GRID_COLS = 'repeat(auto-fill, minmax(8.5rem, 1fr))'

/** Two lines of type — question id above, marks below — plus the padding. */
export const CELL_H = 'h-20'

/** Reading order for question ids, which is not the order they arrive in.
 *
 * `Object.keys` hoists the integer-like keys — `{'1(a)': …, '2': …}` enumerates
 * `2` first — and the picked set grows in click order, so both the grid and the
 * grading queue have to be sorted rather than taken as they come. A plain
 * string sort is not it either: that puts `10` before `2`. */
export function compareQuestionIds(a: string, b: string): number {
  // Mark scheme keys carry a `Q` ("Q3a"); the number after it is what orders.
  const na = Number.parseInt(a.replace(/^Q/, ''), 10)
  const nb = Number.parseInt(b.replace(/^Q/, ''), 10)
  if (na !== nb) {
    // An id with no leading number sorts last rather than compares as NaN.
    return (Number.isNaN(na) ? Infinity : na) - (Number.isNaN(nb) ? Infinity : nb)
  }
  return a.localeCompare(b)
}

/** Fill by score band. `null` is a question with no mark on it. */
export function scoreBand(got: number | null, max: number): string {
  if (got === null) return 'bg-raised'
  if (got >= max) return 'bg-ok/12'
  if (got <= 0) return 'bg-bad/12'
  return 'bg-warn/12'
}

/** A graded question's key: two papers can both have a `Q3a`. */
export function resultKey(paperId: string, question: string): string {
  return `${paperId}:${question}`
}

/** The paper half of a `resultKey`. */
export function paperOf(key: string): string {
  return key.slice(0, key.lastIndexOf(':'))
}

/** The question half of a `resultKey`. Question ids never hold a colon. */
export function questionOf(key: string): string {
  return key.slice(key.lastIndexOf(':') + 1)
}

/** Paper, then reading order within it. */
export function compareResultKeys(a: string, b: string): number {
  const pa = paperOf(a)
  const pb = paperOf(b)
  return pa === pb ? compareQuestionIds(questionOf(a), questionOf(b)) : pa.localeCompare(pb)
}
