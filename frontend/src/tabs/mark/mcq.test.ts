import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { isValidManual, mergeAnswers } from './mcq.ts'

describe('isValidManual', () => {
  test('accepts exactly one A-D letter', () => {
    for (const v of ['A', 'B', 'C', 'D']) assert.equal(isValidManual(v), true, v)
  })

  test('rejects the empty string', () => {
    // The bug this pins: `"ABCD".includes("")` is true, so a substring check
    // would let a cleared box overwrite a detected answer with nothing.
    assert.equal(isValidManual(''), false)
  })

  test('rejects anything else', () => {
    for (const v of ['E', 'a', 'AB', ' A', 'zz', '1']) {
      assert.equal(isValidManual(v), false, v)
    }
  })
})

describe('mergeAnswers — manual wins, junk is dropped', () => {
  test('a valid manual answer overrides the detected one', () => {
    assert.deepEqual(mergeAnswers({ Q1: 'A' }, { Q1: 'C' }), { Q1: 'C' })
  })

  test('junk leaves the detected answer alone', () => {
    assert.deepEqual(mergeAnswers({ Q1: 'A' }, { Q1: 'zz' }), { Q1: 'A' })
    assert.deepEqual(mergeAnswers({ Q1: 'A' }, { Q1: '' }), { Q1: 'A' })
  })

  test('a manual answer for an undetected question is kept', () => {
    assert.deepEqual(mergeAnswers({}, { Q7: 'B' }), { Q7: 'B' })
  })

  test('the detected map is not mutated', () => {
    const detected = { Q1: 'A' }
    mergeAnswers(detected, { Q1: 'D' })
    assert.deepEqual(detected, { Q1: 'A' })
  })
})
