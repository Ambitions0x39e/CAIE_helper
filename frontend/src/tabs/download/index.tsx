import { useState } from 'react'
import { PushTrack } from '../../ui/PushTrack'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { ById } from './ById'
import { Gt } from './Gt'
import { Placeholder } from './Placeholder'

/** The tab's sub-views, in strip order. `index` is what PushTrack animates
 * between, so the order here is also the direction of travel. */
const VIEWS = [
  { id: 'request', label: '按考季', from: 'download/request.py', lines: 616 },
  { id: 'by_id', label: '按卷号', from: 'download/by_id.py', lines: 238 },
  { id: 'gt', label: '分数线', from: 'download/gt.py', lines: 417 },
  { id: 'picker', label: '考季', from: 'download/session_picker.py', lines: 87 },
] as const

type ViewId = (typeof VIEWS)[number]['id']

export function DownloadTab() {
  const [view, setView] = useState<ViewId>('request')
  const index = VIEWS.findIndex((v) => v.id === view)
  const [dir, setDir] = useState(1)

  const go = (id: ViewId) => {
    setDir(VIEWS.findIndex((v) => v.id === id) > index ? 1 : -1)
    setView(id)
  }

  const current = VIEWS[index]

  return (
    <div className="space-y-3">
      <SegmentedStrip items={VIEWS} value={view} onChange={go} />
      <PushTrack step={index} dir={dir}>
        {view === 'by_id' ? (
          <ById />
        ) : view === 'gt' ? (
          <Gt />
        ) : (
          <Placeholder title={current.label} from={current.from} lines={current.lines} />
        )}
      </PushTrack>
    </div>
  )
}
