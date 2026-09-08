import { useEffect, useState } from 'react'
import { Download, LayoutGrid, Pencil, Settings } from 'lucide-react'
import { BRIDGE_ABSENT, api, bridge } from './lib/bridge'
import type { Intent } from './lib/commands'
import { DownloadTab } from './tabs/download'
import { ManageTab } from './tabs/manage'
import { MarkTab } from './tabs/mark'
import { SettingsTab } from './tabs/settings'
import { CommandPalette } from './ui/CommandPalette'
import { OVERLAY_ROOT } from './ui/Overlay'
import { PushTrack } from './ui/PushTrack'
import { ToastHost, notify } from './ui/Toast'

const TABS = [
  { id: 'download', label: '下载', Icon: Download },
  { id: 'manage', label: '管理', Icon: LayoutGrid },
  { id: 'mark', label: '批改', Icon: Pencil },
  { id: 'settings', label: '设置', Icon: Settings },
] as const

type TabId = (typeof TABS)[number]['id']

export default function App() {
  const [tab, setTab] = useState<TabId>('download')
  const [dir, setDir] = useState(1)
  const [connected, setConnected] = useState<boolean | null>(null)
  const [palette, setPalette] = useState(false)
  /** What the palette last asked for. Handed to the destination tab as a prop
   * rather than broadcast: `PushTrack` keys on the step, so switching tabs
   * unmounts one and mounts the other, and an event would have been sent
   * before anyone was listening. Cleared once the tab has acted on it, so the
   * same command works twice in a row. */
  const [intent, setIntent] = useState<Intent | null>(null)

  const index = TABS.findIndex((t) => t.id === tab)

  const go = (id: TabId) => {
    setDir(TABS.findIndex((t) => t.id === id) > index ? 1 : -1)
    setTab(id)
  }

  const run = (next: Intent) => {
    if (next.open !== undefined) {
      const path = next.open
      api()
        .then((a) => a.open_pdf(path))
        .then((r) => notify(r.success ? 'ok' : 'bad', r.success ? '已在系统阅读器中打开' : (r.error ?? '打开失败')))
        .catch((err) => notify('bad', String(err instanceof Error ? err.message : err)))
      return
    }
    if (next.tab !== undefined) go(next.tab)
    // A bare tab switch has nothing for the tab to act on, so it leaves no
    // intent behind to go stale.
    const detailed = next.view !== undefined || next.sub !== undefined || next.param !== undefined
    setIntent(detailed ? next : null)
  }

  const consumed = () => setIntent(null)

  // Resolved once at mount rather than per call: every tab loads on mount, and
  // the bridge is either there for all of them or none.
  useEffect(() => {
    bridge().then((api) => setConnected(api !== null))
  }, [])

  // F5 / Ctrl+R reload and Ctrl+F find are browser behaviours, not app ones.
  // Ctrl+K is ours, and it opens from anywhere — including from inside the
  // palette, where it is a no-op rather than a second dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'F5' || ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'f'))) {
        e.preventDefault()
      }
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault()
        setPalette(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
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
              <DownloadTab intent={intent} onConsumed={consumed} />
            ) : tab === 'manage' ? (
              <ManageTab intent={intent} onConsumed={consumed} />
            ) : tab === 'mark' ? (
              <MarkTab />
            ) : (
              <SettingsTab intent={intent} onConsumed={consumed} />
            )}
          </PushTrack>
        </div>
        <div id={OVERLAY_ROOT} className="pointer-events-none absolute inset-0 z-10" />
      </main>

      <CommandPalette open={palette} onClose={() => setPalette(false)} onRun={run} />

      {/* One host for the whole app: what just happened is said in the same
          corner whichever tab said it. */}
      <ToastHost />
    </div>
  )
}
