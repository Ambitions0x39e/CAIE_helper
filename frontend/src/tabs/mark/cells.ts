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
  const na = Number.parseInt(a, 10)
  const nb = Number.parseInt(b, 10)
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
