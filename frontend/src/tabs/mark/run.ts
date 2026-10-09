import { GRADE_JOB, onJobEvent } from '../../lib/jobs'
import { notify } from '../../ui/Toast'
import type { GradeProgress, QuestionResult } from './types'

/** A grading run, held at module scope rather than in the tab: a hand-back
 * starts from 练习, and its first events arrive before 批改 has mounted to
 * hear them. A listener bound with the module never misses one. */
export interface Run {
  kind: 'paper' | 'practice' | 'mistakes'
  title: string
  /** What the run grades, as `resultKey`s, in sheet order. */
  queue: string[]
  max: Record<string, number>
  /** Paper → its topic list. Empty for a whole paper, whose topics follow the
   * paper id typed on the results page. */
  topics: Record<string, Record<string, string> | null>
  results: QuestionResult[]
  grading: boolean
  progress: GradeProgress | null
}

const EMPTY: Run = {
  kind: 'paper',
  title: '',
  queue: [],
  max: {},
  topics: {},
  results: [],
  grading: false,
  progress: null,
}

let state: Run = EMPTY
const listeners = new Set<() => void>()

function set(next: Partial<Run>) {
  state = { ...state, ...next }
  for (const l of listeners) l()
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const getSnapshot = (): Run => state

/** A run has been asked for: clear the last one before its events land. */
export function begin(total: number, kind: Run['kind'] = 'paper') {
  set({ ...EMPTY, kind, grading: true, progress: { done: 0, total } })
}

/** The run could not start. */
export function abort() {
  set({ grading: false, progress: null })
}

onJobEvent((e) => {
  if (e.type === 'sheet') {
    set({
      kind: e.kind,
      title: e.title,
      queue: e.queue,
      max: e.max,
      topics: e.topics,
      results: [],
      grading: true,
      progress: { done: 0, total: e.queue.length },
    })
    if (e.skipped.length > 0) notify('warn', `未批改：${e.skipped.join('；')}`)
  } else if (e.type === 'progress') set({ progress: { done: e.done, total: e.total } })
  // Cleared by the first question's progress, which replaces the whole state.
  else if (e.type === 'syllabus_fetch')
    set({ progress: state.progress && { ...state.progress, fetching: e.subject_id } })
  // Results arrive as each question lands, not in question order — the
  // whole point of streaming them is that the grid fills in live.
  else if (e.type === 'result')
    set({ results: [...state.results, e.result as unknown as QuestionResult] })
  else if (e.type === 'graded') {
    set({ progress: null })
    if (e.failures.length > 0) {
      const [first] = e.failures
      notify(
        'bad',
        e.failures.length === 1
          ? `${first.question} 批改失败: ${first.error}`
          : `${e.failures.length} 题批改失败，第一题 ${first.question}: ${first.error}`,
      )
    }
  }
  // Both terminal events are shared by every job, so they are read only when
  // they belong to this one — the parse on the first step pushes the same two.
  else if (e.type === 'error' && e.job === GRADE_JOB) notify('bad', `批改失败: ${e.message}`)
  else if (e.type === 'finished' && e.job === GRADE_JOB) set({ grading: false, progress: null })
})

/** A new paper was analysed: the last run's results are not its. */
export function clear() {
  set(EMPTY)
}
