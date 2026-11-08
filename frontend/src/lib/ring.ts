export interface Offset {
  x: number
  y: number
}

/** Where `count` things sit on a regular polygon with sides `spacing` long, from
 * its centre and clockwise: point up for an odd count, flat on top for an even.
 *
 * Centred on the shape's height. An odd polygon's point reaches further from the
 * circumcentre than its base does, so that centre would sit it high in a square. */
export function ringOffsets(count: number, spacing: number): Offset[] {
  const radius = spacing / (2 * Math.sin(Math.PI / count))
  const start = -Math.PI / 2 - (count % 2 === 0 ? Math.PI / count : 0)
  const points = Array.from({ length: count }, (_, i) => {
    const angle = start + (i * 2 * Math.PI) / count
    return { x: radius * Math.cos(angle), y: radius * Math.sin(angle) }
  })
  const ys = points.map((p) => p.y)
  const shift = (Math.min(...ys) + Math.max(...ys)) / 2
  return points.map((p) => ({ x: p.x, y: p.y - shift }))
}
