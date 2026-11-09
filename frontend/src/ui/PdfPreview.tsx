import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/bridge'
import type { PdfKind } from '../lib/types'
import { BackButton } from './BackButton'
import { Overlay } from './Overlay'
import { SegmentedStrip } from './SegmentedStrip'
import { notify } from './Toast'

const KINDS = [
  { id: 'qp', label: 'QP' },
  { id: 'ms', label: 'MS' },
] as const

interface Request {
  paperId: string
  kind: PdfKind
  origin: DOMRect | null
}

/** Set by the one mounted host. Module level for the same reason as `notify`:
 * the palette at the app root and a button deep in a tab open the same panel. */
let deliver: ((request: Request | null) => void) | null = null

export function openPreview(paperId: string, kind: PdfKind, origin: DOMRect | null = null): void {
  deliver?.({ paperId, kind, origin })
}

export function closePreview(): void {
  deliver?.(null)
}

function blobUrl(base64: string): string {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
  return URL.createObjectURL(new Blob([bytes], { type: 'application/pdf' }))
}

/** Mounted once, at the app root. */
export function PdfPreviewHost() {
  const [request, setRequest] = useState<Request | null>(null)
  /** Held past `request` going null so the PDF is still there while the panel
   * shrinks back. */
  const [shown, setShown] = useState(request)
  if (request && request !== shown) setShown(request)

  useEffect(() => {
    deliver = setRequest
    return () => {
      deliver = null
    }
  }, [])

  const close = () => setRequest(null)

  return (
    <Overlay open={request !== null} origin={shown?.origin} onClose={close}>
      {shown && (
        <Preview
          key={shown.paperId}
          paperId={shown.paperId}
          kind={shown.kind}
          onKind={(kind) => setRequest({ ...shown, kind })}
          onClose={close}
        />
      )}
    </Overlay>
  )
}

function Preview({
  paperId,
  kind,
  onKind,
  onClose,
}: {
  paperId: string
  kind: PdfKind
  onKind: (kind: PdfKind) => void
  onClose: () => void
}) {
  const [docs, setDocs] = useState<Partial<Record<PdfKind, string>>>({})
  const [kinds, setKinds] = useState<PdfKind[]>([])
  const urls = useRef<string[]>([])

  useEffect(() => {
    if (docs[kind]) return
    let live = true
    void (async () => {
      try {
        const r = await (await api()).paper_pdf(paperId, kind)
        if (!live) return
        if (!r.success) throw new Error(r.error ?? '打开失败')
        const url = blobUrl(r.data)
        urls.current.push(url)
        setKinds(r.kinds)
        setDocs((d) => ({ ...d, [kind]: url }))
      } catch (err) {
        if (!live) return
        notify('bad', String(err instanceof Error ? err.message : err))
        onClose()
      }
    })()
    return () => {
      live = false
    }
    // Only the paper and the kind can ask for a file; `docs` changing is the
    // answer arriving, and onClose is a new closure on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paperId, kind])

  useEffect(
    () => () => {
      urls.current.forEach((url) => URL.revokeObjectURL(url))
      urls.current = []
    },
    [],
  )

  return (
    <div className="flex h-full flex-col gap-4">
      <div className="flex items-center gap-3">
        <BackButton onClick={onClose} />
        <span className="text-section font-bold tabular-nums">{paperId}</span>
        {kinds.length > 1 && (
          <div className="ml-auto">
            <SegmentedStrip items={KINDS} value={kind} onChange={onKind} />
          </div>
        )}
      </div>

      {/* Both stay loaded once opened, so going from QP to MS and back returns
          to the page that was being read. */}
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-ui border border-hairline">
        {KINDS.map(
          ({ id, label }) =>
            docs[id] && (
              <iframe
                key={id}
                title={`${paperId} ${label}`}
                src={docs[id]}
                className={`absolute inset-0 size-full ${id === kind ? '' : 'invisible'}`}
              />
            ),
        )}
      </div>
    </div>
  )
}
