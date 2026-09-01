import { useEffect, useState } from 'react'
import { BRIDGE_ABSENT, bridge } from './lib/bridge'
import { DownloadTab } from './tabs/download'
import { ManageTab } from './tabs/manage'
import { TokenSheet } from './dev/TokenSheet'
import { PushTrack } from './ui/PushTrack'

const TABS = [
  { id: 'download', label: '下载' },
  { id: 'manage', label: '管理' },
  { id: 'mark', label: '批改' },
  { id: 'settings', label: '设置' },
] as const

type TabId = (typeof TABS)[number]['id']

function Pending({ label }: { label: string }) {
  return (
    <div className="rounded-ui border border-hairline bg-panel p-6 text-caption text-muted">
      {label} —— 还没搬。
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState<TabId>('download')
  const [dir, setDir] = useState(1)
  const [connected, setConnected] = useState<boolean | null>(null)
  const [sheet, setSheet] = useState(false)

  const index = TABS.findIndex((t) => t.id === tab)

  const go = (id: TabId) => {
    setDir(TABS.findIndex((t) => t.id === id) > index ? 1 : -1)
    setTab(id)
  }

  // Resolved once at mount rather than per call: every tab loads on mount, and
  // the bridge is either there for all of them or none.
  useEffect(() => {
    bridge().then((api) => setConnected(api !== null))
  }, [])

  // F5 / Ctrl+R reload and Ctrl+F find are browser behaviours, not app ones.
  useEffect(() => {
    const block = (e: KeyboardEvent) => {
      if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'f'))) {
        e.preventDefault()
      }
    }
    window.addEventListener('keydown', block)
    return () => window.removeEventListener('keydown', block)
  }, [])

  return (
    // The nav is fixed and the main column scrolls on its own. A page-level
    // scroll would carry the nav off the top — it is chrome, it stays put.
    <div className="flex h-screen overflow-hidden bg-chrome text-body text-ink">
      <nav className="flex w-28 shrink-0 flex-col gap-0.5 border-r border-hairline p-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => go(t.id)}
            aria-current={t.id === tab}
            className={`rounded-ui px-2.5 py-1.5 text-left transition-colors ${
              t.id === tab ? 'bg-raised font-medium' : 'text-muted hover:text-ink'
            }`}
            style={{ transitionDuration: 'var(--dur-fast)' }}
          >
            {t.label}
          </button>
        ))}
        <button
          onClick={() => setSheet((v) => !v)}
          className="mt-auto rounded-ui px-2.5 py-1.5 text-left text-micro text-faint hover:text-ink"
        >
          tokens
        </button>
      </nav>

      <main className="min-w-0 flex-1 overflow-y-auto bg-page p-5">
        {connected === false && (
          <div className="mb-3 rounded-ui border border-hairline bg-panel px-3 py-2 text-caption text-warn">
            {BRIDGE_ABSENT}
          </div>
        )}

        {sheet ? (
          <TokenSheet />
        ) : (
          <PushTrack step={index} dir={dir}>
            {tab === 'download' ? (
              <DownloadTab />
            ) : tab === 'manage' ? (
              <ManageTab />
            ) : (
              <Pending label={TABS[index].label} />
            )}
          </PushTrack>
        )}
      </main>
    </div>
  )
}
