import { api } from '../../lib/bridge'
import { PRACTICE_JOB, onJobEvent } from '../../lib/jobs'
import type { QuerySeason } from '../../lib/types'
import { notify } from '../../ui/Toast'

/** Module scope, not component state: the tab unmounts on a tab switch, and the
 * save step after `practice_ready` still has to happen. */
export interface PracticeJob {
  busy: boolean
  progress: string | null
}

let state: PracticeJob = { busy: false, progress: null }
const listeners = new Set<() => void>()

function set(next: Partial<PracticeJob>) {
  state = { ...state, ...next }
  for (const l of listeners) l()
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

export const getSnapshot = (): PracticeJob => state

const message = (err: unknown) => String(err instanceof Error ? err.message : err)

onJobEvent((e) => {
  if (e.type === 'practice_progress') {
    set({ progress: `${e.stage} ${e.done}/${e.total} · ${e.paper}` })
  } else if (e.type === 'practice_ready') {
    set({ progress: null })
    api()
      .then((a) => a.save_practice())
      .then((r) => {
        if (r.cancelled) return
        if (!r.success) {
          notify('bad', r.error ?? '保存失败')
          return
        }
        notify(
          e.warnings.length ? 'warn' : 'ok',
          e.warnings.length
            ? `${e.count} 道题 → ${r.path}；${e.warnings.join('；')}`
            : `${e.count} 道题 → ${r.path}`,
        )
      })
      .catch((err) => notify('bad', message(err)))
  } else if (e.type === 'error' && e.job === PRACTICE_JOB) {
    notify('bad', e.message)
  } else if (e.type === 'finished' && e.job === PRACTICE_JOB) {
    set({ busy: false, progress: null })
  }
})

export async function startPractice(
  subject: string,
  component: string,
  fromYear: number,
  fromSeason: QuerySeason,
  toYear: number,
  toSeason: QuerySeason,
  topicIds: string[],
): Promise<void> {
  set({ busy: true })
  try {
    const r = await (await api()).start_practice(
      subject, component, fromYear, fromSeason, toYear, toSeason, topicIds,
    )
    if (!r.success) {
      set({ busy: false })
      notify('bad', r.error ?? '生成失败')
    }
  } catch (err) {
    set({ busy: false })
    notify('bad', message(err))
  }
}
