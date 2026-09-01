import { useState } from 'react'
import { PushTrack } from '../../ui/PushTrack'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { ById } from './ById'
import { Gt } from './Gt'
import { Request } from './Request'

/** The tab's sub-views, in strip order. `index` is what PushTrack animates
 * between, so the order here is also the direction of travel. */
const VIEWS = [
  { id: 'request', label: '按考季' },
  { id: 'by_id', label: '按卷号' },
  { id: 'gt', label: '分数线' },
] as const

type ViewId = (typeof VIEWS)[number]['id']

const PANES: Record<ViewId, () => React.ReactElement> = {
  request: Request,
  by_id: ById,
  gt: Gt,
}

export function DownloadTab() {
  const [view, setView] = useState<ViewId>('request')
  const [dir, setDir] = useState(1)
  const index = VIEWS.findIndex((v) => v.id === view)

  const go = (id: ViewId) => {
    setDir(VIEWS.findIndex((v) => v.id === id) > index ? 1 : -1)
    setView(id)
  }

  const Pane = PANES[view]

  return (
    <div className="space-y-3">
      <SegmentedStrip items={VIEWS} value={view} onChange={go} />
      <PushTrack step={index} dir={dir}>
        <Pane />
      </PushTrack>
    </div>
  )
}
