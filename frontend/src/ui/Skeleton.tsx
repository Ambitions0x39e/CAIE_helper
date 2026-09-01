/** Placeholder rows for a list whose shape is known but whose length is not. */
export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="h-4 rounded bg-hairline"
          style={{ width: `${94 - ((i * 13) % 38)}%` }}
        />
      ))}
    </div>
  )
}
