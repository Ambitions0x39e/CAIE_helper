/** `1..22` → `"1–22"`, `1,2,5,6,7` → `"1–2, 5–7"`.
 *
 * A science paper covers 22 or 37 topics; spelling every id out overflows the
 * row and buries the one thing worth reading, which is the range.
 *
 * Two cases are easy to lose and both are load-bearing. Ids sort **numerically**
 * — lexicographic order puts "10" before "9" and silently breaks every run past
 * single digits. And non-numeric ids (the maths family's `N.M`) are left alone:
 * those lists are short, and a range over them would be a lie.
 */
export function compactIds(ids: readonly string[]): string {
  if (ids.length === 0) return '（空）'
  if (!ids.every((i) => /^\d+$/.test(i))) return ids.join(', ')

  const nums = [...ids].map(Number).sort((a, b) => a - b)
  const runs: [number, number][] = []
  let start = nums[0]
  let previous = nums[0]
  for (const n of nums.slice(1)) {
    if (n === previous + 1) {
      previous = n
      continue
    }
    runs.push([start, previous])
    start = previous = n
  }
  runs.push([start, previous])
  return runs.map(([lo, hi]) => (lo === hi ? String(lo) : `${lo}–${hi}`)).join(', ')
}
