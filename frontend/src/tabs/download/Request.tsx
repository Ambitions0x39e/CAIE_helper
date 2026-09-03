import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api } from '../../lib/bridge'
import { paperDigit } from '../../lib/papers'
import type { DownloadSource, QueryEntry, SyllabusConfig } from '../../lib/types'
import { Button } from '../../ui/Button'
import { Skeleton } from '../../ui/Skeleton'
import { notify } from '../../ui/Toast'
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

  /** One decision for the whole row of headers: either every column names its
   * subject or none does. Per-column, the same header row ends up half named
   * and half bare, which reads as missing data rather than as a fit. */
  const [namesFit, setNamesFit] = useState(true)
  const gridRef = useRef<HTMLDivElement>(null)
  const probeRef = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const grid = gridRef.current
    const probe = probeRef.current
    if (!grid || !probe) return
    // The probe is `w-max` over one nowrap line per column, so its own width is
    // the widest header's natural width. Both sides of the comparison are
    // independent of `namesFit` — the probe is never hidden by it, and a `1fr`
    // track is sized by the container, not by what is in it — so the reading
    // cannot oscillate between the two answers.
    const measure = () => {
      const track = grid.querySelector<HTMLElement>('[data-col]')?.clientWidth ?? 0
      setNamesFit(probe.getBoundingClientRect().width <= track)
    }
    // Measured here rather than left to the observer's first callback: that one
    // is delivered with the rendering steps, and a host that is not painting
    // never delivers it — the names would then stay on at any width. The
    // observer is for what happens after, when the window is resized.
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(grid)
    return () => observer.disconnect()
  }, [columns, typeNames])

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
    setStatus('查询中…')
    try {
      const a = await api()
      const result = await a.query_session(session.syllabus, session.year, session.season)
      if (!result.success) {
        notify('bad', `查询失败: ${result.error}`)
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
      notify('bad', String(err instanceof Error ? err.message : err))
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
      setStatus(`成功 ${ok} · 跳过 ${skipped} · 失败 ${failed.length}`)
      // One line each, and only for what went wrong: the counts are already on
      // the status line, so a toast repeating them would say nothing new.
      if (failed.length > 0) {
        notify(
          'bad',
          failed.length === 1 ? failed[0] : `${failed.length} 份失败 — ${failed[0]}`,
        )
      } else if (warned.length > 0) {
        notify(
          'warn',
          warned.length === 1 ? warned[0] : `${warned.length} 份的 insert 没下到`,
        )
      }
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
        // One column per paper number, all of them across if they fit.
        //
        // `auto-fit` and a column narrow enough to hold an id: the papers of a
        // syllabus belong on one row, and 11rem is what one costs. `auto-fill`
        // at 15rem picked three fat columns out of the same width and dropped
        // Paper 4 onto a row of its own — the subject name survived, and the
        // shape of the set did not. Empty tracks collapse under `auto-fit`, so
        // a syllabus with three papers still spreads across the full width.
        //
        // Every column's header shares a row via `subgrid`, so they all end up
        // as tall as the tallest and the paper lists start on one baseline.
        // Alignment comes out of a layout pass rather than out of measuring
        // text: no per-character width estimate, no line count to pick, and
        // nothing to recompute on resize.
        <div
          ref={gridRef}
          className="relative grid gap-4 rounded-ui border border-hairline bg-panel p-3.5"
          style={{
            gridTemplateColumns: 'repeat(auto-fit, minmax(11rem, 1fr))',
            gridTemplateRows: 'auto auto',
          }}
        >
          {columns.map(([digit, qps]) => (
            <div
              key={digit}
              data-col
              className="grid row-span-2 gap-y-2"
              style={{ gridTemplateRows: 'subgrid' }}
            >
              {/* The number always fits; the name is all or nothing, and the
                  same answer for every column. Half a subject name under an
                  ellipsis says less than no subject name at all, and one named
                  column beside three bare ones reads as data that failed to
                  load. The one-line height is what holds the row steady. */}
              <div className="border-b border-hairline pb-1.5 text-body font-medium">
                <div className="flex h-[1lh] items-baseline gap-1 overflow-hidden">
                  <span className="whitespace-nowrap">Paper {digit}</span>
                  {namesFit && typeNames.get(digit) && (
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

          {/* Every header at its full length, laid out and measured but never
              painted. `w-max` over one nowrap line each makes this box exactly
              as wide as the longest of them. Out of flow, so it generates no
              track and moves nothing. */}
          <div
            ref={probeRef}
            aria-hidden
            className="pointer-events-none invisible absolute left-0 top-0 w-max
                       text-body font-medium"
          >
            {columns.map(([digit]) => (
              <div key={digit} className="whitespace-nowrap">
                Paper {digit} · {typeNames.get(digit) ?? ''}
              </div>
            ))}
          </div>
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

    </div>
  )
}
