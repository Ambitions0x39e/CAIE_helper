/** Run with `pnpm test` (node --test, no framework dependency). */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import type { JobEvent } from '../../lib/jobs.ts'
import { begin, nextProgress, parseSteps } from './stage.ts'

/** Fold a run of events the way the component does. */
function run(events: JobEvent[], hasAnswer: boolean) {
  return parseSteps(events.reduce(nextProgress, begin(hasAnswer)))
}

describe('parseSteps', () => {
  test('a parse with an answer paper has two steps, both in flight at the start', () => {
    assert.deepEqual(run([], true), [
      { label: '解析 Mark Scheme', state: 'active' },
      { label: '解析答卷', state: 'active' },
    ])
  })

  test('without an answer paper there is only the mark scheme', () => {
    assert.deepEqual(run([], false), [{ label: '解析 Mark Scheme', state: 'active' }])
  })

  test('the two halves finish independently', () => {
    // They run concurrently and the scan is the fast one: its landing is not
    // the mark scheme's.
    assert.deepEqual(run([{ type: 'scan', ok: true, error: '' }], true), [
      { label: '解析 Mark Scheme', state: 'active' },
      { label: '解析答卷', state: 'done' },
    ])
    assert.deepEqual(run([{ type: 'ms_done' }], true), [
      { label: '解析 Mark Scheme', state: 'done' },
      { label: '解析答卷', state: 'active' },
    ])
  })

  test('a scan that failed says so', () => {
    const [, scan] = run([{ type: 'scan', ok: false, error: 'x' }], true)
    assert.equal(scan.state, 'failed')
  })

  test('a cache hit relabels the mark scheme step', () => {
    assert.equal(run([{ type: 'ms_cache', cached: true }], false)[0].label, '读取缓存')
    assert.equal(run([{ type: 'ms_cache', cached: false }], false)[0].label, '解析 Mark Scheme')
  })
})
