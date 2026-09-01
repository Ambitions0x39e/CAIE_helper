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
  | { type: 'progress'; done: number; total: number; question: string }
  | { type: 'result'; result: Record<string, unknown> }
  | { type: 'graded'; results: unknown[]; failures: { question: string; error: string }[] }
  | { type: 'error'; job: string; message: string }
  | { type: 'finished'; job: string }

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
