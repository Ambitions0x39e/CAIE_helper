import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { Minus, Plus } from 'lucide-react'
import { api } from '../../lib/bridge'
import { read, write } from '../../lib/commands'
import type { DownloadSource } from '../../lib/types'
import { BackButton } from '../../ui/BackButton'
import { notify } from '../../ui/Toast'

interface Images {
  question: string[]
  mark_scheme: string[]
}

const MIN_ZOOM = 0.5
const MAX_ZOOM = 3
const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))

const SPLIT_KEY = 'cie.questionView.split'
/** The QP's share of the two panes: the widths they are cropped to, 7 to 10. */
const DEFAULT_SPLIT = 7 / 17
const clampSplit = (f: number) => Math.min(0.8, Math.max(0.2, f))

const TOOL_CLASS = `flex h-7 min-w-7 items-center justify-center rounded-ui text-muted
  transition-colors [transition-duration:var(--dur-fast)] hover:bg-raised hover:text-ink
  disabled:pointer-events-none disabled:opacity-40`

/** Slices of one PDF, stacked. On white whatever the theme: they are pictures of
 * printed pages. The blur grows with the pane's zoom, or enlarging the page would
 * make it readable. */
function Slices({ urls, alt, blurred }: { urls: string[]; alt: string; blurred?: boolean }) {
  return (
    <div className="overflow-hidden rounded-ui border border-hairline bg-white p-3">
      <div
        className={`space-y-2 ${blurred ? '[filter:blur(calc(var(--zoom)*5px))]' : ''}`}
      >
        {urls.map((url, i) => (
          <img key={i} src={url} alt={alt} draggable={false} className="block w-full" />
        ))}
      </div>
    </div>
  )
}

/** A scrolling pane with its own zoom, as a multiple of the pane's width. */
function ZoomPane({
  storageKey,
  style,
  children,
}: {
  storageKey: string
  style?: CSSProperties
  children: ReactNode
}) {
  const [zoom, setZoom] = useState(() => clampZoom(Number(read(storageKey, 1)) || 1))
  const scroller = useRef<HTMLElement>(null)
  // Wheel events can land between renders, and each one builds on the last.
  const zoomNow = useRef(zoom)

  /** Holds the point under `at` still, or else the pane's centre. A pane resting
   * against its top or left edge stays there, so the question's opening line and
   * number are still in view after zooming. */
  const zoomTo = useCallback(
    (next: number, at?: { x: number; y: number }) => {
      const pane = scroller.current
      const z = clampZoom(next)
      const ratio = z / zoomNow.current
      if (!pane || ratio === 1) return
      const box = pane.getBoundingClientRect()
      const x = at ? at.x - box.left : pane.scrollLeft && pane.clientWidth / 2
      const y = at ? at.y - box.top : pane.scrollTop && pane.clientHeight / 2
      // Worked out before the resize: a pane that shrinks clamps its own scroll,
      // and the position would then be scaled from the clamped value.
      const left = (pane.scrollLeft + x) * ratio - x
      const top = (pane.scrollTop + y) * ratio - y
      zoomNow.current = z
      write(storageKey, z)
      flushSync(() => setZoom(z))
      pane.scrollTo({ left, top })
    },
    [storageKey],
  )

  /** To the next quarter, so a zoom left between stops by the wheel lands on one. */
  const zoomStep = (direction: 1 | -1) =>
    zoomTo((Math.round(zoomNow.current * 4) + direction) / 4)

  useEffect(() => {
    // A native listener: React's onWheel is passive and cannot preventDefault.
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return
      e.preventDefault()
      zoomTo(zoomNow.current * Math.exp(-e.deltaY * 0.002), { x: e.clientX, y: e.clientY })
    }
    const el = scroller.current
    el?.addEventListener('wheel', onWheel, { passive: false })
    return () => el?.removeEventListener('wheel', onWheel)
  }, [zoomTo])

  /** Where a press started, and the scroll then. `moved` once it is a drag. */
  const pan = useRef<{ x: number; y: number; left: number; top: number; moved: boolean } | null>(
    null,
  )

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-2" style={style}>
      <div className="flex shrink-0 items-center justify-end gap-1">
        <button
          onClick={() => zoomStep(-1)}
          disabled={zoom <= MIN_ZOOM}
          aria-label="缩小"
          title="缩小"
          className={TOOL_CLASS}
        >
          <Minus className="size-4" aria-hidden />
        </button>
        <button
          onClick={() => zoomTo(1)}
          aria-label="适合宽度"
          title="适合宽度"
          className={`${TOOL_CLASS} w-12 text-caption tabular-nums`}
        >
          {Math.round(zoom * 100)}%
        </button>
        <button
          onClick={() => zoomStep(1)}
          disabled={zoom >= MAX_ZOOM}
          aria-label="放大"
          title="放大"
          className={TOOL_CLASS}
        >
          <Plus className="size-4" aria-hidden />
        </button>
      </div>
      <section
        ref={scroller}
        className="min-h-0 flex-1 cursor-grab overflow-auto active:cursor-grabbing"
        onPointerDown={(e) => {
          if (e.button !== 0) return
          const pane = e.currentTarget
          pan.current = {
            x: e.clientX, y: e.clientY, left: pane.scrollLeft, top: pane.scrollTop, moved: false,
          }
        }}
        onPointerMove={(e) => {
          const start = pan.current
          if (!start) return
          if (!(e.buttons & 1)) {
            pan.current = null
            return
          }
          const dx = e.clientX - start.x
          const dy = e.clientY - start.y
          // A few pixels of wobble is still a click: the blurred mark scheme opens on one.
          if (!start.moved && Math.hypot(dx, dy) < 4) return
          if (!start.moved) {
            start.moved = true
            e.currentTarget.setPointerCapture(e.pointerId)
          }
          e.currentTarget.scrollTo({ left: start.left - dx, top: start.top - dy })
        }}
        onPointerUp={() => {
          // Cleared after the click this release fires, which a drag swallows.
          setTimeout(() => (pan.current = null))
        }}
        onPointerCancel={() => (pan.current = null)}
        onClickCapture={(e) => {
          if (pan.current?.moved) e.stopPropagation()
        }}
      >
        {/* Gone while the next question loads, which is what returns the scroll
            to the start of it. */}
        {children && (
          <div
            className="mx-auto"
            style={{ width: `${zoom * 100}%`, '--zoom': zoom } as CSSProperties}
          >
            {children}
          </div>
        )}
      </section>
    </div>
  )
}

/** One question of a paper at a time, its mark scheme blurred until asked for.
 *
 * Both sides scroll and zoom on their own: a question and its mark scheme rarely
 * run the same length, and comparing them means holding one still. The line
 * between them sets their widths, starting from the widths they are cropped to,
 * where at one zoom the two print at one size.
 *
 * With `preview` the paper is fetched from that source into a temp folder rather
 * than read from the library, and the folder goes when the panel does. */
export function QuestionView({
  paperId,
  preview,
  onClose,
}: {
  paperId: string
  preview?: DownloadSource
  onClose: () => void
}) {
  const [questions, setQuestions] = useState<string[] | null>(null)
  const [hasMs, setHasMs] = useState(false)
  const [current, setCurrent] = useState<string | null>(null)
  const [images, setImages] = useState<Images | null>(null)
  const [revealed, setRevealed] = useState(false)
  const [split, setSplit] = useState(() =>
    clampSplit(Number(read(SPLIT_KEY, DEFAULT_SPLIT)) || DEFAULT_SPLIT),
  )
  const panes = useRef<HTMLDivElement>(null)

  const moveSplit = (f: number) => {
    const next = clampSplit(f)
    setSplit(next)
    write(SPLIT_KEY, next)
  }

  useEffect(() => {
    let live = true
    void (async () => {
      const a = await api()
      const r = await (preview ? a.preview_paper(paperId, preview) : a.paper_questions(paperId))
      if (!live) return
      if (!r.success) {
        notify('bad', r.error ?? '打开失败')
        onClose()
        return
      }
      setQuestions(r.questions)
      setHasMs(r.has_ms)
      setCurrent(r.questions[0])
    })()
    return () => {
      live = false
      if (preview) void api().then((a) => a.close_preview())
    }
    // The paper is fixed for this panel's life; onClose is a new closure on every
    // render and must not re-run the crop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId])

  useEffect(() => {
    if (!current) return
    let live = true
    setImages(null)
    setRevealed(false)
    void (async () => {
      const a = await api()
      const r = await (preview
        ? a.preview_question_images(current)
        : a.paper_question_images(paperId, current))
      if (!live) return
      if (r.success) setImages(r)
      else notify('bad', r.error ?? '打开失败')
    })()
    return () => {
      live = false
    }
  }, [paperId, preview, current])

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center gap-3">
        <BackButton onClick={onClose} />
        <span className="text-section font-bold tabular-nums">{paperId}</span>
      </div>

      {questions === null ? (
        <div className="text-muted">正在切题…</div>
      ) : (
        <div className="flex min-h-0 flex-1 gap-4">
          <nav className="flex w-14 shrink-0 flex-col gap-1 overflow-y-auto">
            {questions.map((q) => (
              <button
                key={q}
                onClick={() => setCurrent(q)}
                className={`shrink-0 rounded-ui px-2 py-1.5 text-caption tabular-nums ${
                  q === current
                    ? 'bg-accent font-semibold text-on-accent'
                    : 'text-muted hover:bg-raised hover:text-ink'
                }`}
              >
                {q}
              </button>
            ))}
          </nav>

          <div ref={panes} className="flex min-w-0 flex-1">
            <ZoomPane
              storageKey="cie.questionView.zoom.qp"
              style={hasMs ? { flex: `${split} 1 0` } : undefined}
            >
              {images && <Slices urls={images.question} alt={`${current} 题目`} />}
            </ZoomPane>

            {hasMs && (
              <div
                role="separator"
                aria-orientation="vertical"
                aria-valuenow={Math.round(split * 100)}
                tabIndex={0}
                className="group flex w-4 shrink-0 cursor-col-resize touch-none justify-center outline-none"
                onPointerDown={(e) => e.currentTarget.setPointerCapture(e.pointerId)}
                onPointerMove={(e) => {
                  const box = panes.current?.getBoundingClientRect()
                  if (!box || !e.currentTarget.hasPointerCapture(e.pointerId)) return
                  moveSplit((e.clientX - box.left) / box.width)
                }}
                onKeyDown={(e) => {
                  if (e.key === 'ArrowLeft') moveSplit(split - 0.02)
                  if (e.key === 'ArrowRight') moveSplit(split + 0.02)
                }}
              >
                <div className="w-px bg-hairline transition-colors [transition-duration:var(--dur-fast)] group-hover:w-0.5 group-hover:bg-accent group-focus-visible:w-0.5 group-focus-visible:bg-accent group-active:w-0.5 group-active:bg-accent" />
              </div>
            )}

            {hasMs && (
              <ZoomPane
                storageKey="cie.questionView.zoom.ms"
                style={{ flex: `${1 - split} 1 0` }}
              >
                {images &&
                  (revealed ? (
                    <Slices urls={images.mark_scheme} alt={`${current} mark scheme`} />
                  ) : (
                    // Without the press every button gets: a whole page shrinking
                    // under the pointer moves every line on it.
                    <button
                      onClick={() => setRevealed(true)}
                      aria-label="显示 Mark Scheme"
                      className="block w-full cursor-pointer text-left"
                      style={{ scale: '1' }}
                    >
                      <Slices urls={images.mark_scheme} alt="" blurred />
                    </button>
                  ))}
              </ZoomPane>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
