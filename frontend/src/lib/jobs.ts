/** Receiver for the events Python pushes during a long job.
 *
 * The Python side calls `window.__cieJobEvent(payload)` from a worker thread
 * (see app_web/jobs.py). This is the single place that name is bound, so a
 * rename only has to agree with one string.
 */

export type JobEvent =
  | { type: 'ms_cache'; cached: boolean }
  | { type: 'ms_progress'; batch: number; total: number }
  | { type: 'scan'; ok: boolean; error: string }
  | { type: 'analysis'; [k: string]: unknown }
  | { type: 'mcq_progress'; batch: number; total: number }
  | {
      type: 'mcq_detected'
      detected: Record<string, string>
      undetected: string[]
      answer_key: Record<string, string>
    }
  | { type: 'progress'; done: number; total: number; question: string }
  | { type: 'result'; result: Record<string, unknown> }
  | { type: 'graded'; results: unknown[]; failures: { question: string; error: string }[] }
  | { type: 'error'; job: string; message: string }
  | { type: 'finished'; job: string }

/** The names `error` and `finished` carry. Both events are shared by every job,
 * so a listener that cares about one has to say which. */
export const PARSE_JOB = '解析'
export const GRADE_JOB = '批改'
export const MCQ_JOB = '识别答案'

type Listener = (e: JobEvent) => void

const listeners = new Set<Listener>()

declare global {
  interface Window {
    __cieJobEvent?: (e: JobEvent) => void
  }
}

// Bound once at module load, not per subscriber: Python pushes to one global
// name, and re-assigning it while a job is mid-flight would drop events.
if (typeof window !== 'undefined') {
  window.__cieJobEvent = (e) => {
    for (const l of listeners) l(e)
  }
}

/** Subscribe for the lifetime of a component. Returns the unsubscribe. */
export function onJobEvent(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}
