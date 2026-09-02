import { useEffect, useState } from 'react'
import { Download, LayoutGrid, Pencil, Settings } from 'lucide-react'
import { BRIDGE_ABSENT, bridge } from './lib/bridge'
import { DownloadTab } from './tabs/download'
import { ManageTab } from './tabs/manage'
import { MarkTab } from './tabs/mark'
import { SettingsTab } from './tabs/settings'
import { OVERLAY_ROOT } from './ui/Overlay'
import { PushTrack } from './ui/PushTrack'

const TABS = [
  { id: 'download', label: '下载', Icon: Download },
  { id: 'manage', label: '管理', Icon: LayoutGrid },
  { id: 'mark', label: '批改', Icon: Pencil },
  { id: 'settings', label: '设置', Icon: Settings },
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
      {/* One entry is one square: icon and label are a single group, centred
          together. 设置 sits at the far end — it is the app's own settings,
          not a fourth destination alongside the three. */}
      <nav className="flex shrink-0 flex-col items-center gap-2 border-r border-hairline px-2.5 py-3">
        {TABS.map((t, i) => (
          <button
            key={t.id}
            onClick={() => go(t.id)}
            aria-current={t.id === tab}
            className={`flex size-16 flex-col items-center justify-center gap-1 rounded-[14px]
                        border transition-colors ${
                          t.id === tab
                            ? 'border-hairline bg-panel font-medium text-accent'
                            : 'border-transparent text-muted hover:text-ink'
                        } ${i === TABS.length - 1 ? 'mt-auto' : ''}`}
            style={{ transitionDuration: 'var(--dur-fast)' }}
          >
            <t.Icon className="size-6" aria-hidden />
            <span className="text-caption">{t.label}</span>
          </button>
        ))}
      </nav>

      {/* The scroll lives one level in so this element stays the size of the
          viewport, which is what an overlay pinned to `inset-0` needs to cover.
          Put the scroll here and an overlay would stretch to the content's full
          height instead. */}
      {/* The content region runs one step roomier than the chrome. Every
          spacing utility Tailwind emits is `calc(var(--spacing) * N)`, so
          redefining that one variable here scales every padding, gap and box
          inside — and the nav, which sits outside, keeps the size it has. */}
      <main
        className="relative min-w-0 flex-1 overflow-hidden bg-page"
        style={{ '--spacing': '0.275rem' } as React.CSSProperties}
      >
        <div className="h-full overflow-y-auto px-7 py-6">
          {connected === false && (
            <div className="mb-3 rounded-ui border border-hairline bg-panel px-3 py-2 text-caption text-warn">
              {BRIDGE_ABSENT}
            </div>
          )}

          <PushTrack step={index} dir={dir}>
            {tab === 'download' ? (
              <DownloadTab />
            ) : tab === 'manage' ? (
              <ManageTab />
            ) : tab === 'mark' ? (
              <MarkTab />
            ) : tab === 'settings' ? (
              <SettingsTab />
            ) : (
              <Pending label={TABS[index].label} />
            )}
          </PushTrack>
        </div>
        <div id={OVERLAY_ROOT} className="pointer-events-none absolute inset-0 z-10" />
      </main>
    </div>
  )
}
