import { useState } from 'react'
import { type EmptyMode, FREQUENT_COUNT, emptyMode, setEmptyMode } from '../../lib/commands'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { Row, SubPage } from './SubPage'

const MODES = [
  { id: 'plain', label: '简洁' },
  { id: 'frequent', label: '常用命令' },
] as const satisfies readonly { id: EmptyMode; label: string }[]

export function PaletteView({ onBack }: { onBack: () => void }) {
  const [mode, setMode] = useState<EmptyMode>(emptyMode)

  const change = (m: EmptyMode) => {
    setMode(m)
    setEmptyMode(m)
  }

  return (
    <SubPage title="命令面板" onBack={onBack}>
      <div className="rounded-ui border border-hairline bg-panel">
        <Row
          label="刚打开时列什么"
          hint={`简洁只列命令；常用命令把用得最多的 ${FREQUENT_COUNT} 条放在最前`}
        >
          <SegmentedStrip items={MODES} value={mode} onChange={change} />
        </Row>
      </div>
      <p className="text-caption text-muted">
        Ctrl+K（macOS Cmd+K）唤起。输入 file 加卷号搜已存的卷子。
      </p>
    </SubPage>
  )
}
