/** Run with `pnpm test` (node --test, no framework dependency). */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { compareQuestionIds, compareResultKeys, questionOf, scoreBand } from './cells.ts'

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

  test('reads the number after the Q of a mark scheme key', () => {
    assert.deepEqual(['Q10', 'Q2', 'Q1b', 'Q1a'].sort(compareQuestionIds), ['Q1a', 'Q1b', 'Q2', 'Q10'])
  })

  test('an id with no leading number sorts last', () => {
    assert.deepEqual(['extra', '2', '1'].sort(compareQuestionIds), ['1', '2', 'extra'])
  })
})

describe('resultKey', () => {
  test('groups by paper, then reading order', () => {
    const keys = ['9709_s24_qp_41:2', '9231_s23_qp_43:10', '9709_s24_qp_41:1(a)', '9231_s23_qp_43:3']
    assert.deepEqual(keys.sort(compareResultKeys), [
      '9231_s23_qp_43:3',
      '9231_s23_qp_43:10',
      '9709_s24_qp_41:1(a)',
      '9709_s24_qp_41:2',
    ])
  })

  test('a cover-page id keeps its question', () => {
    assert.equal(questionOf('9709/12/M/J/25:Q3a'), 'Q3a')
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
