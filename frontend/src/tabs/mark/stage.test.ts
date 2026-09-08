/** Run with `npm test` (node --test, no framework dependency). */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import type { JobEvent } from '../../lib/jobs.ts'
import { nextStage } from './stage.ts'

/** Fold a run of events the way the component does. */
function run(events: JobEvent[], hasAnswer: boolean): string {
  return events.reduce((s, e) => nextStage(s, e, { hasAnswer }), '准备中…')
}

describe('nextStage', () => {
  test('a cold parse names the render before any batch has been counted', () => {
    // The gap this closes: render_pages runs before the first ms_progress,
    // so a run that only reacts to batches says nothing for the longest
    // silent stretch of the whole parse.
    assert.equal(run([{ type: 'ms_cache', cached: false }], true), '渲染 Mark Scheme 页面…')
  })

  test('counts batches while the mark scheme is being read', () => {
    assert.equal(
      run(
        [
          { type: 'ms_cache', cached: false },
          { type: 'ms_progress', batch: 3, total: 8 },
        ],
        true,
      ),
      '解析 Mark Scheme 第 3/8 批…',
    )
  })

  test('an answer scan landing mid-parse does not wipe the batch counter', () => {
    // Both halves run concurrently. The scan is the fast one, so its
    // completion is not what the reader is waiting on.
    assert.equal(
      run(
        [
          { type: 'ms_cache', cached: false },
          { type: 'ms_progress', batch: 2, total: 8 },
          { type: 'scan', ok: true, error: '' },
        ],
        true,
      ),
      '解析 Mark Scheme 第 2/8 批…',
    )
  })

  test('the last batch gives way to the answer scan instead of going stale', () => {
    assert.equal(
      run(
        [
          { type: 'ms_progress', batch: 8, total: 8 },
          { type: 'ms_done' },
        ],
        true,
      ),
      '分析答卷…',
    )
  })

  test('a cache hit says so, and reports whatever is left', () => {
    assert.equal(run([{ type: 'ms_cache', cached: true }], true), '读取缓存，分析答卷…')
    assert.equal(run([{ type: 'ms_cache', cached: true }], false), '读取缓存…')
  })

  test('both terminal events clear the line', () => {
    const started: JobEvent[] = [{ type: 'ms_progress', batch: 1, total: 4 }]
    assert.equal(run([...started, { type: 'finished', job: '解析' }], true), '')
    assert.equal(run([...started, { type: 'error', job: '解析', message: 'x' }], true), '')
  })
})
