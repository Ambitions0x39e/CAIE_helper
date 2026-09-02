/** Column-shaping helpers for the download tab.
 *
 * These live in a `.ts` file rather than beside the components that use them
 * because `node --test` strips TypeScript types but not JSX — a helper exported
 * from a `.tsx` file cannot be imported by a test.
 */

/** Plain sort puts "A" before "A*" — "A" is a prefix, so it compares shorter.
 * CIE reads A* as the higher grade. Group by the letter with the star stripped
 * and put the starred one first; the remaining letters (B/C/D/E/U) already run
 * high-to-low alphabetically. */
export function sortGrades(grades: Iterable<string>): string[] {
  return [...new Set(grades)].sort((a, b) => {
    const base = a.replace(/\*/g, '').localeCompare(b.replace(/\*/g, ''))
    if (base !== 0) return base
    return a.includes('*') ? -1 : 1
  })
}
