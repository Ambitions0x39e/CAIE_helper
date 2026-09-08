/** MCQ answer helpers, in a `.ts` so `node --test` can reach them (it strips
 * TypeScript types but not JSX). */

export const LETTERS = ['A', 'B', 'C', 'D'] as const

/** Matches `mcq_parser.is_valid_manual_answer`: a single A–D letter.
 *
 * Set membership, not `"ABCD".includes(v)` — substring semantics accept the
 * empty string, which would let a cleared box overwrite a detected answer
 * with nothing.
 */
export function isValidManual(value: string): boolean {
  return (LETTERS as readonly string[]).includes(value)
}
