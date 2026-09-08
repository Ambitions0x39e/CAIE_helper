import { useState } from 'react'
import { type Theme, setTheme, theme } from '../../lib/commands'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { Row, SubPage } from './SubPage'

const THEMES = [
  { id: 'system', label: '跟随系统' },
  { id: 'light', label: '浅色' },
  { id: 'dark', label: '深色' },
] as const satisfies readonly { id: Theme; label: string }[]

export function ThemeView({ onBack }: { onBack: () => void }) {
  const [current, setCurrent] = useState<Theme>(theme)

  const change = (t: Theme) => {
    setCurrent(t)
    setTheme(t)
  }

  return (
    <SubPage title="主题" onBack={onBack}>
      <div className="rounded-ui border border-hairline bg-panel">
        <Row label="配色">
          <SegmentedStrip items={THEMES} value={current} onChange={change} />
        </Row>
      </div>
    </SubPage>
  )
}
