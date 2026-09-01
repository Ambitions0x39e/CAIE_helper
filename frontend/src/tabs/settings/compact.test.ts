import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import { compactIds } from './compact.ts'

describe('compactIds — ported from settings.py::_compact_ids', () => {
  test('a full run collapses to one range', () => {
    assert.equal(compactIds(Array.from({ length: 22 }, (_, i) => String(i + 1))), '1–22')
  })

  test('gaps split into several runs', () => {
    assert.equal(compactIds(['1', '2', '5', '6', '7']), '1–2, 5–7')
  })

  test('a run of two is still a range, not a list', () => {
    assert.equal(compactIds(['1', '2']), '1–2')
  })

  test('a lone id stays a lone id', () => {
    assert.equal(compactIds(['3']), '3')
    assert.equal(compactIds(['1', '3', '5']), '1, 3, 5')
  })

  test('ids sort numerically, not lexicographically', () => {
    // The bug this pins: "10" < "9" as strings, which breaks every run that
    // crosses ten and produces a plausible-looking wrong range.
    assert.equal(compactIds(['9', '10', '11']), '9–11')
    assert.equal(compactIds(['10', '9', '11']), '9–11')
  })

  test('non-numeric ids are left alone', () => {
    assert.equal(compactIds(['1.1', '1.2', '2.1']), '1.1, 1.2, 2.1')
  })

  test('empty', () => {
    assert.equal(compactIds([]), '（空）')
  })
})
