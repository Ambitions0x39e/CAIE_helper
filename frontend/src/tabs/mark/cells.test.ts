/** Run with `npm test` (node --test, no framework dependency). */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { compareQuestionIds, scoreBand } from './cells.ts'

describe('compareQuestionIds', () => {
  test('puts the parts of a question together, in paper order', () => {
    // The order Object.keys hands back for these very keys: the integer-like
    // ones first, the rest in insertion order.
    const ids = ['2', '4', '10', '1(a)', '1(b)', '3(b)', '3(a)']
    assert.deepEqual(
      [...ids].sort(compareQuestionIds),
      ['1(a)', '1(b)', '2', '3(a)', '3(b)', '4', '10'],
    )
  })

  test('an id with no leading number sorts last', () => {
    assert.deepEqual(['extra', '2', '1'].sort(compareQuestionIds), ['1', '2', 'extra'])
  })
})

describe('scoreBand', () => {
  test('separates full, partial, zero and not-yet-marked', () => {
    assert.equal(scoreBand(6, 6), 'bg-ok/12')
    assert.equal(scoreBand(4, 6), 'bg-warn/12')
    assert.equal(scoreBand(0, 6), 'bg-bad/12')
    assert.equal(scoreBand(null, 6), 'bg-raised')
  })
})
