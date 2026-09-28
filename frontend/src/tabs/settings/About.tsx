import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { onJobEvent, UPDATE_JOB } from '../../lib/jobs'
import { Button } from '../../ui/Button'
import { Dialog } from '../../ui/Dialog'
import { notify } from '../../ui/Toast'
import { Row, SubPage } from './SubPage'

const ISSUES_URL = 'https://github.com/Ambitions0x39e/CAIE_helper/issues'

interface CheckResult {
  success: boolean
  error?: string | null
  update_available?: boolean
  latest_version?: string | null
  release_notes?: string | null
  download_url?: string | null
}

export function About({ onBack }: { onBack: () => void }) {
  const [version, setVersion] = useState('—')
  const [checking, setChecking] = useState(false)
  const [result, setResult] = useState<CheckResult | null>(null)
  /** Set once the download starts; the app quits when the installer runs. */
  const [progress, setProgress] = useState<{ fraction: number | null; text: string } | null>(null)

  useEffect(() => {
    api()
      .then((a) => a.app_version())
      .then((v) => setVersion(v || '—'))
      .catch(() => setVersion('—'))
  }, [])

  useEffect(
    () =>
      onJobEvent((e) => {
        if (e.type === 'update_progress') setProgress({ fraction: e.fraction, text: e.text })
        else if (e.type === 'error' && e.job === UPDATE_JOB) {
          notify('bad', e.message)
          setProgress(null)
        }
      }),
    [],
  )

  const install = async () => {
    setProgress({ fraction: 0, text: '准备下载…' })
    const r = await (await api()).install_update()
    if (!r.success) {
      notify('bad', r.error ?? '更新失败')
      setProgress(null)
    }
  }

  /** Only a new version gets the dialog. A one-line answer — nothing new, or
   * the check itself failed — is said in the corner like every other one. */
  const check = async () => {
    setChecking(true)
    setResult(null)
    try {
      const r = await (await api()).check_update()
      if (!r.success) notify('bad', r.error ?? '检查失败')
      else if (!r.update_available) notify('ok', `${version} 已经是最新版本`)
      else setResult(r)
    } catch (err) {
      notify('bad', String(err instanceof Error ? err.message : err))
    } finally {
      setChecking(false)
    }
  }

  return (
    <SubPage title="关于" onBack={onBack}>
      <div className="rounded-ui border border-hairline bg-panel">
        <Row label="CIE Helper">
          <span className="text-body tabular-nums text-muted">{version}</span>
        </Row>
        <Row label="检查更新" hint="从 GitHub Releases 取最新版本">
          <Button onClick={check} disabled={checking}>
            {checking ? '检查中…' : '检查'}
          </Button>
        </Row>
        <Row label="反馈问题" hint="在 GitHub 上提 issue">
          <Button onClick={() => api().then((a) => a.open_external(ISSUES_URL))}>
            打开
          </Button>
        </Row>
      </div>

      <Dialog open={result !== null} title="有新版本" onClose={() => progress === null && setResult(null)}>
        {result && (
          <div className="space-y-3">
            <p className="text-body">
              当前 <span className="tabular-nums">{version}</span>，最新{' '}
              <span className="tabular-nums font-semibold">{result.latest_version}</span>。
            </p>
            {result.release_notes && (
              <p className="selectable whitespace-pre-wrap text-caption text-muted">
                {result.release_notes}
              </p>
            )}
            {progress ? (
              <div className="space-y-1">
                <div className="text-caption tabular-nums text-muted">{progress.text}</div>
                <div className="h-1 overflow-hidden rounded bg-hairline">
                  <div
                    className="h-full bg-accent"
                    style={{
                      width: `${(progress.fraction ?? 0) * 100}%`,
                      transition: 'width var(--dur-base) var(--ease-ui)',
                    }}
                  />
                </div>
              </div>
            ) : (
              <div className="flex justify-end">
                <Button tone="accent" onClick={install}>
                  下载并安装
                </Button>
              </div>
            )}
          </div>
        )}
      </Dialog>
    </SubPage>
  )
}
