import { useEffect, useState } from 'react'
import { api } from '../../lib/bridge'
import { Banner } from '../../ui/Banner'
import { Button } from '../../ui/Button'
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

  const check = async () => {
    setChecking(true)
    setResult(null)
    try {
      setResult(await (await api()).check_update())
    } catch (err) {
      setResult({ success: false, error: String(err instanceof Error ? err.message : err) })
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

      {result && !result.success && (
        <Banner tone="bad" title={result.error ?? '检查失败'} />
      )}
      {result?.success && !result.update_available && (
        <Banner tone="ok" title="已经是最新版本" />
      )}
      {result?.success && result.update_available && (
        <Banner
          tone="warn"
          title={`有新版本 ${result.latest_version}`}
          details={result.release_notes ? [result.release_notes] : undefined}
        />
      )}
      {result?.success && result.update_available && result.download_url && (
        <p className="text-caption text-muted">
          应用内下载安装还没接上（M4 的活）。现在先去 Releases 页面手动下载。
        </p>
      )}
    </SubPage>
  )
}
