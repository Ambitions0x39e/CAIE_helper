/** Where a parse has got to, as the steps the 解析 button draws.
 *
 * The events already carry every boundary, so this is a fold over them rather
 * than anything the backend has to be asked. Kept pure and separate from the
 * component so it can be pinned by a test.
 */
import type { JobEvent } from '../../lib/jobs'
import type { Step } from '../../ui/StepButton'

/** The mark scheme and the answer paper are read concurrently, so each has its
 * own flag rather than one position along a line. `scan` is null until the
 * answer paper has been read. */
export interface ParseProgress {
  hasAnswer: boolean
  cached: boolean
  msDone: boolean
  scan: 'done' | 'failed' | null
  failed: boolean
}

/** A parse has been asked for. Whether an answer paper came with it decides
 * how many steps there are, so it is fixed here rather than read off the
 * page, which the user may change mid-run. */
export const begin = (hasAnswer: boolean): ParseProgress => ({
  hasAnswer,
  cached: false,
  msDone: false,
  scan: null,
  failed: false,
})

export function nextProgress(p: ParseProgress, e: JobEvent): ParseProgress {
  switch (e.type) {
    case 'ms_cache':
      return { ...p, cached: e.cached }
    case 'ms_done':
      return { ...p, msDone: true }
    case 'scan':
      return { ...p, scan: e.ok ? 'done' : 'failed' }
    default:
      return p
  }
}

export function parseSteps(p: ParseProgress): Step[] {
  const steps: Step[] = [
    { label: p.cached ? '读取缓存' : '解析 Mark Scheme', state: p.msDone ? 'done' : 'active' },
  ]
  if (p.hasAnswer)
    steps.push({ label: '解析答卷', state: p.scan ?? 'active' })
  return steps
}
