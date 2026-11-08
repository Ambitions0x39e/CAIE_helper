import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import type { PaperRecord } from '../../lib/types'
import { BackButton } from '../../ui/BackButton'
import { Button } from '../../ui/Button'
import { notify } from '../../ui/Toast'

interface Images {
  question: string[]
  mark_scheme: string[]
}

/** Slices of one PDF, stacked. On white whatever the theme: they are pictures of
 * printed pages. */
function Slices({ urls, alt }: { urls: string[]; alt: string }) {
  return (
    <div className="space-y-2 rounded-ui border border-hairline bg-white p-3">
      {urls.map((url, i) => (
        <img key={i} src={url} alt={alt} className="block w-full" />
      ))}
    </div>
  )
}

/** One question of a paper at a time, its mark scheme kept back until asked for.
 *
 * Both sides scroll on their own: a question and its mark scheme rarely run the
 * same length, and comparing them means holding one still. The columns are in
 * proportion to the widths they are cropped to, so the two print at one size. */
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

          <section className="min-w-0 flex-[7] overflow-y-auto">
            {images && <Slices urls={images.question} alt={`${current} 题目`} />}
          </section>

          {hasMs && (
            <section className="min-w-0 flex-[10] overflow-y-auto">
              {images &&
                (revealed ? (
                  <Slices urls={images.mark_scheme} alt={`${current} mark scheme`} />
                ) : (
                  <Button onClick={() => setRevealed(true)}>显示 Mark Scheme</Button>
                ))}
            </section>
          )}
        </div>
      )}
    </div>
  )
}
