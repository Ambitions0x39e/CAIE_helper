import { useState } from 'react'
import type { DownloadSource } from '../../lib/types'
import { PushTrack } from '../../ui/PushTrack'
import { SegmentedStrip } from '../../ui/SegmentedStrip'
import { ById } from './ById'
import { Gt } from './Gt'
import { Request } from './Request'

/** The tab's sub-views, in strip order. `index` is what PushTrack animates
 * between, so the order here is also the direction of travel. */
const VIEWS = [
  { id: 'request', label: '按考季查询' },
  { id: 'by_id', label: '按 ID 下载' },
  { id: 'gt', label: '分数线' },
] as const

type ViewId = (typeof VIEWS)[number]['id']

const SOURCES = [
  { id: 'CIEFrank', label: 'CIEFrank' },
  { id: 'PapaCambridge', label: 'PapaCambridge' },
] as const satisfies readonly { id: DownloadSource; label: string }[]

export function DownloadTab() {
  const [view, setView] = useState<ViewId>('request')
  const [dir, setDir] = useState(1)
  // Owned by the tab rather than by 按 ID 下载: it says where every download on
  // this tab is fetched from, so it belongs beside the view nav, not inside one
  // of the views.
  const [source, setSource] = useState<DownloadSource>('CIEFrank')
  const index = VIEWS.findIndex((v) => v.id === view)

  const go = (id: ViewId) => {
    setDir(VIEWS.findIndex((v) => v.id === id) > index ? 1 : -1)
    setView(id)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <SegmentedStrip items={VIEWS} value={view} onChange={go} />
        <div className="ml-auto flex items-center gap-2">
          <span className="text-caption text-muted">来源:</span>
          <SegmentedStrip items={SOURCES} value={source} onChange={setSource} />
        </div>
      </div>
      <PushTrack step={index} dir={dir}>
        {view === 'request' ? (
          <Request source={source} />
        ) : view === 'by_id' ? (
          <ById source={source} />
        ) : (
          <Gt source={source} />
        )}
      </PushTrack>
    </div>
  )
}
