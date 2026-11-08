import assert from 'node:assert/strict'
import { test } from 'node:test'
import { ringOffsets } from './ring.ts'

const near = (a: number, b: number) => Math.abs(a - b) < 0.01

test('five sit on a regular pentagon, point up', () => {
  const points = ringOffsets(5, 40)
  assert.equal(points.length, 5)
  // Clockwise from the top: the middle of the top row is the first action.
  assert.ok(near(points[0].x, 0))
  assert.ok(points[1].x > 0 && points[4].x < 0)
  // Every side the same length, and that length the spacing asked for.
  for (let i = 0; i < 5; i++) {
    const a = points[i]
    const b = points[(i + 1) % 5]
    assert.ok(near(Math.hypot(a.x - b.x, a.y - b.y), 40), `side ${i}`)
  }
})

test('the shape is centred on its height, not on its circumcentre', () => {
  // A pentagon's top reaches further from the circumcentre than its base does,
  // which left to itself sits the cluster visibly high in its square.
  const ys = ringOffsets(5, 40).map((p) => p.y)
  assert.ok(near(Math.min(...ys), -Math.max(...ys)))
})

test('four sit flat as a square, not on a corner', () => {
  const points = ringOffsets(4, 40)
  assert.deepEqual(
    points.map((p) => [Math.round(p.x), Math.round(p.y)]),
    [[-20, -20], [20, -20], [20, 20], [-20, 20]],
  )
})
