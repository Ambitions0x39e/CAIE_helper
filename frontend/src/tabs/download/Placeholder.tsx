/** Stands in for a sub-view that has not been migrated yet.
 *
 * Deleted as each view lands — by the end of the download tab there should be
 * no import of this file left.
 */
export function Placeholder({ title, from, lines }: { title: string; from: string; lines: number }) {
  return (
    <div className="rounded-ui border border-hairline bg-panel p-4">
      <div className="text-subhead font-medium">{title}</div>
      <div className="mt-1 text-caption text-muted">
        待搬：<code className="text-ink">{from}</code>（{lines} 行）
      </div>
      <div className="mt-3 space-y-1.5">
        {Array.from({ length: Math.min(6, Math.round(lines / 100)) }, (_, i) => (
          <div
            key={i}
            className="h-4 rounded bg-hairline"
            style={{ width: `${92 - ((i * 17) % 45)}%` }}
          />
        ))}
      </div>
    </div>
  )
}
