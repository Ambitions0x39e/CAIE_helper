import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
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

  useEffect(() => {
    api()
      .then((a) => a.app_version())
      .then((v) => setVersion(v || '—'))
      .catch(() => setVersion('—'))
  }, [])

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

      <Dialog open={result !== null} title="有新版本" onClose={() => setResult(null)}>
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
            {result.download_url && (
              <p className="text-caption text-muted">
                应用内下载安装还没接上。现在先去 Releases 页面手动下载。
              </p>
            )}
          </div>
        )}
      </Dialog>
    </SubPage>
  )
}
