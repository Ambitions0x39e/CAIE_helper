import { useCallback, useEffect, useRef, useState } from 'react'
import type { CSSProperties, ReactNode } from 'react'
import { flushSync } from 'react-dom'
import { Minus, Plus } from 'lucide-react'
import { api } from '../../lib/bridge'
import { read, write } from '../../lib/commands'
import type { PaperRecord } from '../../lib/types'
import { BackButton } from '../../ui/BackButton'
import { notify } from '../../ui/Toast'

interface Images {
  question: string[]
  mark_scheme: string[]
}

const MIN_ZOOM = 0.5
const MAX_ZOOM = 3
const clampZoom = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))

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
          <img key={i} src={url} alt={alt} className="block w-full" />
        ))}
      </div>
    </div>
  )
}

/** A scrolling pane with its own zoom, as a multiple of the pane's width. */
function ZoomPane({
  storageKey,
  className,
  children,
}: {
  storageKey: string
  className: string
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

  return (
    <div className={`flex min-w-0 flex-col gap-2 ${className}`}>
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
      <section ref={scroller} className="min-h-0 flex-1 overflow-auto">
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
 * run the same length, and comparing them means holding one still. The columns
 * are in proportion to the widths they are cropped to, so at one zoom the two
 * print at one size. */
export function QuestionView({
  paper,
  onClose,
}: {
  paper: PaperRecord
  onClose: () => void
}) {
  const [questions, setQuestions] = useState<string[] | null>(null)
  const [hasMs, setHasMs] = useState(false)
  const [current, setCurrent] = useState<string | null>(null)
  const [images, setImages] = useState<Images | null>(null)
  const [revealed, setRevealed] = useState(false)

  useEffect(() => {
    let live = true
    void (async () => {
      const r = await (await api()).paper_questions(paper.paper_id)
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
    }
    // The paper is fixed for this panel's life; onClose is a new closure on every
    // render and must not re-run the crop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paper.paper_id])

  useEffect(() => {
    if (!current) return
    let live = true
    setImages(null)
    setRevealed(false)
    void (async () => {
      const r = await (await api()).paper_question_images(paper.paper_id, current)
      if (!live) return
      if (r.success) setImages(r)
      else notify('bad', r.error ?? '打开失败')
    })()
    return () => {
      live = false
    }
  }, [paper.paper_id, current])

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center gap-3">
        <BackButton onClick={onClose} />
        <span className="text-section font-bold tabular-nums">{paper.paper_id}</span>
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

          <ZoomPane storageKey="cie.questionView.zoom.qp" className="flex-[7]">
            {images && <Slices urls={images.question} alt={`${current} 题目`} />}
          </ZoomPane>

          {hasMs && (
            <ZoomPane storageKey="cie.questionView.zoom.ms" className="flex-[10]">
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
      )}
    </div>
  )
}
