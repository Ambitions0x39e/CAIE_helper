/** Run with `npm test`.
 *
 * Both functions were ported out of Python and both fail quietly: a wrong
 * column digit files a paper under the wrong heading, and a wrong grade order
 * draws a table that looks entirely normal with its columns transposed.
 */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { paperDigit, sortGrades } from './columns.ts'

describe('paperDigit — which column a paper belongs in', () => {
  test('takes the second-to-last digit of the variant', () => {
    for (const [id, want] of [
      ['9231_s22_qp_11', '1'],
      ['9231_s22_qp_12', '1'],
      ['9231_s22_qp_13', '1'],
      ['9231_s22_qp_21', '2'],
      ['9231_s22_qp_41', '4'],
    ] as const) {
      assert.equal(paperDigit(id), want, id)
    }
  })

  test('a single-digit variant uses that digit', () => {
    assert.equal(paperDigit('9702_s23_qp_1'), '1')
  })

  test('anything without a digit lands in the ? column', () => {
    assert.equal(paperDigit('9701_w25_gt'), '?')
    assert.equal(paperDigit('9702_s23_qp_ab'), '?')
  })
})

describe('sortGrades — A* outranks A', () => {
  test('a plain sort would put A first because it is a prefix', () => {
    assert.deepEqual(sortGrades(['A', 'A*', 'B', 'C', 'D', 'E']), [
      'A*', 'A', 'B', 'C', 'D', 'E',
    ])
  })

  test('the order does not depend on the input order', () => {
    const want = ['A*', 'A', 'B', 'C', 'D', 'E']
    assert.deepEqual(sortGrades(['E', 'D', 'C', 'B', 'A', 'A*']), want)
    assert.deepEqual(sortGrades(['C', 'A*', 'E', 'A', 'D', 'B']), want)
  })

  test('U sorts last and duplicates collapse', () => {
    assert.deepEqual(sortGrades(['U', 'A*', 'A', 'B', 'A']), ['A*', 'A', 'B', 'U'])
  })
})
