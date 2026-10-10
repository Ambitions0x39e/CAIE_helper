/** The steps the 生成 button draws, in the order the backend works through
 * them. A step with nothing to do (every paper already downloaded) reports
 * nothing, so a step counts as done once a later one has begun. */
import type { Step } from '../../ui/StepButton'

export const STAGES = ['下载', '分类', '答案'] as const

/** The last `practice_progress` seen; null before the first. */
export interface Stage {
  name: string
  done: number
  total: number
}

export function practiceSteps(stage: Stage | null): Step[] {
  const at = stage ? STAGES.indexOf(stage.name as (typeof STAGES)[number]) : -1
  return STAGES.map((label, i) =>
    i < at
      ? { label, state: 'done' }
      : i === at && stage
        ? {
            label: `${label} ${stage.done}/${stage.total}`,
            state: 'active',
            // The event fires as the item starts, so it is the one in flight.
            units: { done: stage.done - 1, total: stage.total },
          }
        : { label, state: 'pending' },
  )
}
