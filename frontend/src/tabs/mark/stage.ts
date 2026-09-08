/** What the parse is doing right now, as one line of standing text.
 *
 * The events already carry every stage boundary, so this is a fold over them
 * rather than anything the backend has to be asked. Kept pure and separate
 * from the component so the wording can be pinned by a test.
 */
import type { JobEvent } from '../../lib/jobs'

/** Whether an answer paper was handed in alongside the mark scheme. The scan
 * runs concurrently with the parse, so it is what remains once the mark
 * scheme lands. */
export type StageInput = { hasAnswer: boolean }

/** The line shown while a parse is in flight. Empty means show nothing. */
export function nextStage(
  current: string,
  e: JobEvent,
  { hasAnswer }: StageInput,
): string {
  switch (e.type) {
    case 'ms_cache':
      // A hit skips straight past rendering and batching; what is left is
      // whatever the answer paper needs.
      return e.cached
        ? hasAnswer
          ? '读取缓存，分析答卷…'
          : '读取缓存…'
        : '渲染 Mark Scheme 页面…'
    case 'ms_progress':
      return `解析 Mark Scheme 第 ${e.batch}/${e.total} 批…`
    case 'ms_done':
      return hasAnswer ? '分析答卷…' : '整理结果…'
    case 'scan':
      // The scan finishing while the parse is still batching must not wipe
      // the batch counter — the slower half is still the one to report.
      return current.startsWith('分析答卷') || current.startsWith('读取缓存')
        ? '整理结果…'
        : current
    case 'error':
    case 'finished':
      return ''
    default:
      return current
  }
}
