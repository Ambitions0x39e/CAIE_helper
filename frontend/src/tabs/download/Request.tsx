import { useEffect, useMemo, useState } from 'react'
import { api } from '../../lib/bridge'
import { paperDigit } from '../../lib/papers'
import type { DownloadSource, QueryEntry, SyllabusConfig } from '../../lib/types'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { Skeleton } from '../../ui/Skeleton'
import { SessionPicker } from './SessionPicker'
import type { Session } from './session'

function rowNote(entry: QueryEntry): string {
  if (entry.kind === 'gt') return '分数线'
  if (entry.kind === 'other') return '暂不支持'
  return ''
}

/** A MS/insert hanging under its QP, drawn the way `tree` draws one.
 *
 * Box-drawing rather than an arrow glyph: `├──` and `└──` are full-height at
 * the body size and join up into a single vertical rule down the group, so the
 * branch reads as one shape instead of as a column of small marks. The last
 * child closes the corner, which is what says the group ended.
 *
 * A tree library would bring selection, virtualisation and drag — none of which
 * this has. It is two fixed levels of text.
 *
 * Not selectable: ticking the QP takes the whole set, because
 * `download(insert=true)` fetches QP+MS+in together.
 */
function Leaf({ text, last }: { text: string; last: boolean }) {
  return (
    <div className="flex items-center text-caption text-faint">
      <span
        aria-hidden
        // Monospace so the trunk lines up under itself, and `leading-none` so
        // consecutive rows' verticals meet instead of breaking at every line.
        className="select-none whitespace-pre font-mono leading-none"
      >
        {last ? ' └─ ' : ' ├─ '}
      </span>
      <span className="tabular-nums">{text}</span>
    </div>
  )
}

export function Request({ source }: { source: DownloadSource }) {
  const [session, setSession] = useState<Session | null>(null)
  const [syllabuses, setSyllabuses] = useState<SyllabusConfig[]>([])
  const [entries, setEntries] = useState<QueryEntry[] | null>(null)
  const [queriedSyllabus, setQueriedSyllabus] = useState<string | null>(null)
  const [picked, setPicked] = useState<ReadonlySet<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [status, setStatus] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [warnings, setWarnings] = useState<string[]>([])

  useEffect(() => {
    api()
      .then((a) => a.syllabuses())
      .then(setSyllabuses)
      .catch(() => setSyllabuses([]))
  }, [])

  /** digit -> paper name, for the syllabus this result was queried with.
   * Reading the picker instead would relabel an old result with a new
   * subject's names the moment the user changes the dropdown. */
  const typeNames = useMemo(() => {
    const s = syllabuses.find((x) => x.syllabus_id === queriedSyllabus)
    return new Map((s?.paper_types ?? []).map((p) => [p.digit, p.name]))
  }, [syllabuses, queriedSyllabus])

  /** QP entries grouped into columns, plus the ids shown as leaves under them. */
  const { columns, leftovers } = useMemo(() => {
    if (!entries) return { columns: [], leftovers: [] as QueryEntry[] }
    const present = new Set(entries.map((e) => e.paper_id))
    const nested = new Set<string>()
    const groups = new Map<string, QueryEntry[]>()

    for (const e of entries) {
      if (e.kind !== 'qp') continue
      const digit = paperDigit(e.paper_id)
      groups.set(digit, [...(groups.get(digit) ?? []), e])
      const ms = e.paper_id.replace('_qp_', '_ms_')
      if (present.has(ms)) nested.add(ms)
      if (e.has_insert) nested.add(e.paper_id.replace('_qp_', '_in_'))
    }

    return {
      columns: [...groups.entries()].sort(([a], [b]) => a.localeCompare(b)),
      leftovers: entries.filter((e) => e.kind !== 'qp' && !nested.has(e.paper_id)),
    }
  }, [entries])

  /** Every row that carries a checkbox: the QPs plus any loose gt. */
  const selectable = useMemo(
    () => (entries ?? []).filter((e) => e.kind === 'qp' || e.kind === 'gt'),
    [entries],
  )

  const skipCount = selectable.filter(
    (e) => picked.has(e.paper_id) && e.already_downloaded,
  ).length

  const runQuery = async () => {
    if (!session || busy) return
    setBusy(true)
    setLoading(true)
    setEntries(null)
    setPicked(new Set())
    setErrors([])
    setWarnings([])
    setFailure(null)
    setStatus('查询中…')
    try {
      const a = await api()
      const result = await a.query_session(session.syllabus, session.year, session.season)
      if (!result.success) {
        setFailure(`查询失败: ${result.error}`)
        setStatus(null)
        return
      }
      if (result.entries.length === 0) {
        setStatus('这个考季没有查到任何文件')
        return
      }
      setEntries(result.entries)
      setQueriedSyllabus(session.syllabus)
      setStatus(null)
    } catch (err) {
      setFailure(String(err instanceof Error ? err.message : err))
      setStatus(null)
    } finally {
      setLoading(false)
      setBusy(false)
    }
  }

  const toggle = (paperId: string) => {
    const next = new Set(picked)
    if (!next.delete(paperId)) next.add(paperId)
    setPicked(next)
  }

  const setAll = (on: boolean) =>
    setPicked(on ? new Set(selectable.map((e) => e.paper_id)) : new Set())

  const batchDownload = async () => {
    const chosen = selectable.filter((e) => picked.has(e.paper_id))
    if (busy || chosen.length === 0) return
    setBusy(true)
    setErrors([])
    setWarnings([])
    let ok = 0
    let skipped = 0
    const failed: string[] = []
    const warned: string[] = []
    const done = new Set<string>()
    try {
      const a = await api()
      for (const [i, entry] of chosen.entries()) {
        if (entry.already_downloaded) {
          skipped++
          continue
        }
        setStatus(`下载中 ${i + 1}/${chosen.length} — ${entry.paper_id}`)
        // Only fetch the insert for rows that showed one.
        const dl = await a.download_paper(entry.paper_id, source, entry.has_insert)
        if (dl.success) {
          ok++
          done.add(entry.paper_id)
          if (dl.insert_error) {
            warned.push(`${entry.paper_id} 的 insert 没下到: ${dl.insert_error}`)
          }
        } else {
          failed.push(`${entry.paper_id}: ${dl.error}`)
        }
      }
    } catch (err) {
      failed.push(String(err instanceof Error ? err.message : err))
    } finally {
      setEntries((prev) =>
        prev?.map((e) =>
          done.has(e.paper_id) ? { ...e, already_downloaded: true } : e,
        ) ?? null,
      )
      setPicked(new Set())
      setErrors(failed)
      setWarnings(warned)
      setStatus(`成功 ${ok} · 跳过 ${skipped} · 失败 ${failed.length}`)
      setBusy(false)
    }
  }

  const Row = ({ entry }: { entry: QueryEntry }) => (
    <label className="flex h-6 items-center gap-2">
      <input
        type="checkbox"
        checked={picked.has(entry.paper_id)}
        onChange={() => toggle(entry.paper_id)}
      />
      <span className="tabular-nums">{entry.paper_id}</span>
      <span className="ml-auto text-caption text-muted">{rowNote(entry)}</span>
    </label>
  )

  return (
    <div className="space-y-4">
      <div className="rounded-ui border border-hairline bg-panel p-4.5 space-y-3">
        <SessionPicker onChange={setSession} />
        <Button tone="accent" onClick={runQuery} disabled={busy || !session}>
          查询
        </Button>
      </div>

      {failure && <Banner tone="bad" title={failure} />}

      {(status || entries) && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-caption text-muted">
            {status ??
              `共 ${entries?.length ?? 0} 个文件，${selectable.length} 份可下载 · 已勾选 ${picked.size}` +
                (skipCount ? `（其中 ${skipCount} 个本地已有，会跳过）` : '')}
          </span>
          {entries && (
            <>
              <Button tone="accent" onClick={batchDownload} disabled={busy || picked.size === 0}>
                批量下载
              </Button>
              <Button onClick={() => setAll(true)}>全选可下载</Button>
              <Button onClick={() => setAll(false)}>清空</Button>
            </>
          )}
        </div>
      )}

      {loading && (
        <div className="rounded-ui border border-hairline bg-panel p-4.5">
          <Skeleton />
        </div>
      )}

      {entries && columns.length > 0 && (
        // One column per paper number, as many across as the width allows.
        //
        // Every column's header shares a row via `subgrid`, so they all end up
        // as tall as the tallest and the paper lists start on one baseline.
        // Alignment comes out of a layout pass rather than out of measuring
        // text: no per-character width estimate, no line count to pick, and
        // nothing to recompute on resize.
        <div
          className="grid gap-4 rounded-ui border border-hairline bg-panel p-3.5"
          style={{
            gridTemplateColumns: 'repeat(auto-fill, minmax(15rem, 1fr))',
            gridTemplateRows: 'auto auto',
          }}
        >
          {columns.map(([digit, qps]) => (
            <div key={digit} className="grid row-span-2 gap-y-2" style={{ gridTemplateRows: 'subgrid' }}>
              {/* The number always fits; the name is all or nothing.
                  A column is as narrow as 15rem and "Further Probability &
                  Statistics" does not fit in one — and half a subject name
                  under an ellipsis says less than no subject name at all.
                  The wrap does the deciding: both items refuse to shrink, so
                  a name that does not fit is pushed onto a second line, and
                  the one-line height clips that line away whole. */}
              <div className="border-b border-hairline pb-1.5 text-body font-medium">
                <div className="flex h-[1lh] flex-wrap items-baseline gap-1 overflow-hidden">
                  <span className="whitespace-nowrap">Paper {digit}</span>
                  {typeNames.get(digit) && (
                    // The gap is the container's, not a leading space in here:
                    // a flex item's own leading whitespace is trimmed away.
                    <span className="whitespace-nowrap text-muted">
                      · {typeNames.get(digit)}
                    </span>
                  )}
                </div>
              </div>
              <div className="space-y-2">
                {qps.map((entry) => {
                  const ms = entry.paper_id.replace('_qp_', '_ms_')
                  const hasMs = entries.some((e) => e.paper_id === ms)
                  return (
                    <div key={entry.paper_id}>
                      <Row entry={entry} />
                      <Leaf
                        text={hasMs ? ms : '（没有对应 MS）'}
                        last={!entry.has_insert}
                      />
                      {entry.has_insert && (
                        <Leaf text={entry.paper_id.replace('_qp_', '_in_')} last />
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {entries && leftovers.length > 0 && (
        <div className="rounded-ui border border-hairline bg-panel p-4.5 space-y-1">
          {leftovers.map((entry) =>
            entry.kind === 'gt' ? (
              <Row key={entry.paper_id} entry={entry} />
            ) : (
              <div key={entry.paper_id} className="flex h-6 items-center gap-2 pl-6 text-muted">
                <span className="tabular-nums">{entry.paper_id}</span>
                <span className="ml-auto text-caption">{rowNote(entry)}</span>
              </div>
            ),
          )}
        </div>
      )}

      {errors.slice(0, 5).map((e) => (
        <Banner key={e} tone="bad" title={e} />
      ))}
      {errors.length > 5 && (
        <Banner tone="bad" title={`…另有 ${errors.length - 5} 条失败`} />
      )}
      {warnings.slice(0, 5).map((w) => (
        <Banner key={w} tone="warn" title={w} />
      ))}
    </div>
  )
}
