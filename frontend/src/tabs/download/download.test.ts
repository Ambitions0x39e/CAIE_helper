/** Run with `npm test`.
 *
 * Ported out of Python, and it fails quietly: a wrong grade order draws a
 * table that looks entirely normal with its columns transposed.
 */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { sortGrades } from './columns.ts'

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
