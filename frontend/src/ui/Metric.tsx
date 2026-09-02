/** One headline number from a finished run — score, percentage, question
 * count. Read across, not down: three of them side by side are the summary. */
export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-32 rounded-ui border border-hairline bg-panel px-4 py-2.5">
      <div className="text-caption text-muted">{label}</div>
      <div className="text-title tabular-nums">{value}</div>
    </div>
  )
}
