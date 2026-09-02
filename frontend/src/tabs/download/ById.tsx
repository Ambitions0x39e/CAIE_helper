import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import type { DownloadResult, DownloadSource, MailResult } from '../../lib/types'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
import { Field } from '../../ui/Field'

/** What the result area is showing. `null` is the empty state. */
type Outcome =
  | { kind: 'downloaded'; result: DownloadResult }
  | { kind: 'recorded'; result: DownloadResult }
  | { kind: 'failed'; error: string }
  | null

export function ById({ source }: { source: DownloadSource }) {
  const [paperId, setPaperId] = useState('')
  const [busy, setBusy] = useState(false)
  const [outcome, setOutcome] = useState<Outcome>(null)
  const [mailReady, setMailReady] = useState(false)
  const [sent, setSent] = useState<MailResult | null>(null)

  useEffect(() => {
    api()
      .then((a) => a.mail_ready())
      .then(setMailReady)
      .catch(() => setMailReady(false))
  }, [])

  /** Shared by both buttons: the only difference is which call they make. */
  const run = async (call: (id: string) => Promise<DownloadResult>, kind: 'downloaded' | 'recorded') => {
    const id = paperId.trim()
    if (!id || busy) return
    setBusy(true)
    setOutcome(null)
    setSent(null)
    try {
      const result = await call(id)
      setOutcome(result.success ? { kind, result } : { kind: 'failed', error: result.error ?? '未知错误' })
    } catch (err) {
      setOutcome({ kind: 'failed', error: String(err instanceof Error ? err.message : err) })
    } finally {
      setBusy(false)
    }
  }

  const download = () =>
    run((id) => api().then((a) => a.download_paper(id, source)), 'downloaded')
  const record = () => run((id) => api().then((a) => a.record_paper(id)), 'recorded')

  const sendToGoodNotes = async () => {
    if (outcome?.kind !== 'downloaded' || !outcome.result.qp_path) return
    const { paper_id, qp_path } = outcome.result
    setSent(await api().then((a) => a.send_to_goodnotes(paper_id, qp_path)))
  }

  // Offered only once there is a QP on disk to attach.
  const canSend =
    mailReady && outcome?.kind === 'downloaded' && Boolean(outcome.result.qp_path) && !sent?.success

  return (
    <div className="space-y-4">
      <div className="rounded-ui border border-hairline bg-panel p-4.5 space-y-3">
        <Field
          label="Paper ID"
          hint="格式: <科目>_<考期>_qp_<试卷>"
          placeholder="9702_s23_qp_11"
          value={paperId}
          onChange={(e) => setPaperId(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && download()}
        />

        <div className="flex items-center gap-2">
          <Button tone="accent" onClick={download} disabled={busy || !paperId.trim()}>
            下载
          </Button>
          <Button onClick={record} disabled={busy || !paperId.trim()}>
            仅记录
          </Button>
        </div>
      </div>

      {outcome?.kind === 'downloaded' && (
        <Banner
          tone="ok"
          title={`已下载: ${outcome.result.paper_id}`}
          details={[
            `QP → ${outcome.result.qp_path}`,
            `MS → ${outcome.result.ms_path}`,
          ]}
        />
      )}
      {outcome?.kind === 'recorded' && (
        <Banner tone="ok" title={`已记录 (无PDF): ${outcome.result.paper_id}`} />
      )}
      {outcome?.kind === 'failed' && <Banner tone="bad" title={outcome.error} />}

      {canSend && (
        <div className="flex items-center gap-2">
          <span className="text-caption text-muted">
            准备发送: {outcome.result.paper_id}
          </span>
          <Button onClick={sendToGoodNotes}>发送到 GoodNotes</Button>
        </div>
      )}
      {sent && (
        <Banner
          tone={sent.success ? 'ok' : 'bad'}
          title={sent.success ? `已发送到 ${sent.recipient}` : `发送失败: ${sent.error}`}
        />
      )}
    </div>
  )
}
