import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { isValidManual } from './mcq.ts'

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
