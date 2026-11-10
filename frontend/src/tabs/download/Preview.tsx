import { useState } from 'react'
import type { DownloadSource } from '../../lib/types'
import { Button } from '../../ui/Button'
import { Field } from '../../ui/Field'
import { Overlay } from '../../ui/Overlay'
import { QuestionView } from '../manage/QuestionView'

export function Preview({ source }: { source: DownloadSource }) {
  const [paperId, setPaperId] = useState('')
  /** What the panel shows. Kept through the close, so it still has a paper while
   * it shrinks away. */
  const [shown, setShown] = useState<{ id: string; source: DownloadSource; n: number } | null>(
    null,
  )
  const [open, setOpen] = useState(false)
  const [origin, setOrigin] = useState<DOMRect | null>(null)

  const start = (rect: DOMRect) => {
    const id = paperId.trim()
    if (!id) return
    setOrigin(rect)
    setShown((prev) => ({ id, source, n: (prev?.n ?? 0) + 1 }))
    setOpen(true)
  }

  return (
    <div className="rounded-ui border border-hairline bg-panel p-4.5 space-y-3">
      <Field
        label="Paper ID"
        hint="格式: <科目>_<考期>_qp_<试卷>"
        placeholder="9702_s23_qp_42"
        value={paperId}
        onChange={(e) => setPaperId(e.target.value)}
        onKeyDown={(e) =>
          e.key === 'Enter' && start(e.currentTarget.getBoundingClientRect())
        }
      />
      <Button
        tone="accent"
        onClick={(e) => start(e.currentTarget.getBoundingClientRect())}
        disabled={!paperId.trim()}
      >
        预览
      </Button>

      <Overlay open={open} origin={origin} onClose={() => setOpen(false)}>
        {shown && (
          // Keyed per opening, so the same id opened again fetches again.
          <QuestionView
            key={shown.n}
            paperId={shown.id}
            preview={shown.source}
            onClose={() => setOpen(false)}
          />
        )}
      </Overlay>
    </div>
  )
}
