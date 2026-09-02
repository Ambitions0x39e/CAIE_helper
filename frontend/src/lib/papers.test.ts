/** Run with `npm test` (node --test, no framework dependency).
 *
 * These pin the arithmetic the 总览 donut and the subject glyphs read out.
 */
import assert from 'node:assert/strict'
import { describe, test } from 'node:test'
import {
  FALLBACK_GLYPH,
  comparePaperIds,
  subjectGlyph,
  syllabusIdOf,
  tally,
} from './papers.ts'
import type { PaperRecord } from './types.ts'

const done = (paper_id: string, raw: number, total: number): PaperRecord => ({
  paper_id,
  status: 'Completed',
  qp_path: '',
  ms_path: '',
  score_raw: raw,
  score_total: total,
  sent_to_gn: false,
  timestamp: '2026-01-01T00:00:00Z',
  percentage: Math.round((raw / total) * 10000) / 100,
})

const pending = (paper_id: string): PaperRecord => ({
  paper_id,
  status: 'Pending',
  qp_path: '',
  ms_path: '',
  score_raw: null,
  score_total: null,
  sent_to_gn: false,
  timestamp: null,
  percentage: null,
})

describe('tally — one unit per paper, and the three slices must add up', () => {
  test('slices sum to the paper count', () => {
    const t = tally([
      done('9702_s24_qp_11', 40, 50),
      done('9709_s24_qp_12', 30, 60),
      pending('9701_s24_qp_21'),
    ])
    assert.equal(t.total, 3)
    assert.ok(Math.abs(t.earned + t.lost + t.pending - 3) < 1e-9)
  })

  test('earned is the score rate, not the paper count', () => {
    // 80% and 50% → 1.3 units earned, 0.7 lost. Counting papers gives 2 and 0.
    const t = tally([done('9702_s24_qp_11', 40, 50), done('9709_s24_qp_12', 30, 60)])
    assert.ok(Math.abs(t.earned - 1.3) < 1e-9)
    assert.ok(Math.abs(t.lost - 0.7) < 1e-9)
  })

  test('a pending paper has no marks to split', () => {
    const t = tally([pending('9702_s24_qp_11')])
    assert.deepEqual([t.earned, t.lost, t.pending], [0, 0, 1])
  })

  test('empty store', () => {
    assert.deepEqual(tally([]), { total: 0, earned: 0, lost: 0, pending: 0 })
  })
})

describe('subjectGlyph — the keyword table is ordered, longest first', () => {
  test('further maths does not fall into maths', () => {
    assert.notEqual(
      subjectGlyph('Further Mathematics'),
      subjectGlyph('Mathematics'),
    )
  })

  test('the same subject at both levels shares a glyph', () => {
    // 0620 and 9701 are both Chemistry — a property of matching on the name,
    // which matching on the code would not have.
    assert.equal(subjectGlyph('Chemistry'), subjectGlyph('Chemistry (9701)'))
  })

  test('an unknown subject falls back', () => {
    assert.equal(subjectGlyph('Underwater Basket Weaving'), FALLBACK_GLYPH)
    assert.equal(subjectGlyph(undefined), FALLBACK_GLYPH)
  })
})

describe('syllabusIdOf', () => {
  test('takes the leading four digits', () => {
    assert.equal(syllabusIdOf('9702_s24_qp_11'), '9702')
  })
})

describe('comparePaperIds', () => {
  test('year comes before series', () => {
    // The trap in sorting the ids as strings: the series letter is to the
    // left of the year, so `m24` would sort ahead of `s23`.
    assert.deepEqual(
      ['9709_m24_qp_11', '9709_s23_qp_11'].sort(comparePaperIds),
      ['9709_s23_qp_11', '9709_m24_qp_11'],
    )
  })

  test('within a year it runs March, Summer, Winter', () => {
    assert.deepEqual(
      ['9709_w23_qp_11', '9709_s23_qp_11', '9709_m23_qp_11'].sort(comparePaperIds),
      ['9709_m23_qp_11', '9709_s23_qp_11', '9709_w23_qp_11'],
    )
  })

  test('same sitting falls back to the paper number', () => {
    assert.deepEqual(
      ['9709_s23_qp_12', '9709_s23_qp_11'].sort(comparePaperIds),
      ['9709_s23_qp_11', '9709_s23_qp_12'],
    )
  })

  test('an id the table has not seen still appears, at the end', () => {
    const sorted = ['9709_x23_qp_11', '9709_s23_qp_11'].sort(comparePaperIds)
    assert.deepEqual(sorted, ['9709_s23_qp_11', '9709_x23_qp_11'])
  })
})
