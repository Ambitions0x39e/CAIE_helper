/** Run with `pnpm test` (node --test, no framework dependency). */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { practiceSteps } from './steps.ts'

const states = (name: string | null) =>
  practiceSteps(name ? { name, done: 2, total: 5 } : null).map((s) => s.state)

describe('practiceSteps', () => {
  test('nothing has been reported yet', () => {
    assert.deepEqual(states(null), ['pending', 'pending', 'pending'])
  })

  test('the reported step is active and counts, the ones before it are done', () => {
    assert.deepEqual(practiceSteps({ name: '分类', done: 2, total: 5 }), [
      { label: '下载', state: 'done' },
      { label: '分类 2/5', state: 'active', units: { done: 1, total: 5 } },
      { label: '答案', state: 'pending' },
    ])
  })

  test('a step that never reported is done once a later one has', () => {
    assert.deepEqual(states('答案'), ['done', 'done', 'active'])
  })
})
