import { useState } from 'react'

const STEPS = [
  { name: 'chrome', cls: 'bg-chrome', use: '窗口外框 / 侧边导航' },
  { name: 'page', cls: 'bg-page', use: '页面底' },
  { name: 'panel', cls: 'bg-panel', use: '面板 / 列表 / 表单块' },
  { name: 'raised', cls: 'bg-raised', use: '浮层 / 对话框 / 命令面板' },
]

const STATUS = [
  { name: 'accent', cls: 'bg-accent', on: 'text-on-accent' },
  { name: 'ok', cls: 'bg-ok', on: 'text-raised' },
  { name: 'warn', cls: 'bg-warn', on: 'text-raised' },
  { name: 'bad', cls: 'bg-bad', on: 'text-raised' },
]

const TYPE = [
  { name: 'title', cls: 'text-title' },
  { name: 'section', cls: 'text-section' },
  { name: 'subhead', cls: 'text-subhead' },
  { name: 'body', cls: 'text-body' },
  { name: 'caption', cls: 'text-caption' },
  { name: 'micro', cls: 'text-micro' },
]

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-3 items-start">
      <div className="text-caption text-muted pt-1">{label}</div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

/** One theme's worth of tokens, forced to `theme` regardless of the OS setting. */
function Sheet({ theme }: { theme: 'light' | 'dark' }) {
  const [lifted, setLifted] = useState(false)
  return (
    <div data-theme={theme} className="bg-chrome p-4 rounded-ui">
      <div className="bg-page rounded-ui p-4 space-y-5 text-ink text-body">
        <div className="text-subhead font-medium">{theme}</div>

        <Row label="面阶梯">
          {/* Nested, not side by side: the question is whether each step reads
              as sitting on top of the one under it. */}
          <div className="bg-chrome border border-hairline rounded-ui p-2">
            <div className="bg-page border border-hairline rounded-ui p-2">
              <div className="bg-panel border border-hairline rounded-ui p-2">
                <div className="bg-raised border border-hairline rounded-ui p-2 text-caption">
                  raised — 四层都嵌在这里，每层之间只有 1px 描边
                </div>
              </div>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-4 gap-2">
            {STEPS.map((s) => (
              <div key={s.name} className={`${s.cls} border border-hairline rounded-ui p-2`}>
                <div className="text-micro font-medium">{s.name}</div>
                <div className="text-micro text-faint leading-tight mt-0.5">{s.use}</div>
              </div>
            ))}
          </div>
        </Row>

        <Row label="描边">
          <div className="flex gap-2">
            {STEPS.map((s) => (
              <div key={s.name} className={`${s.cls} flex-1 rounded-ui p-2 text-micro`}>
                <div className="border border-hairline rounded p-1.5">hairline</div>
                <div className="border border-hairline-strong rounded p-1.5 mt-1.5">strong</div>
              </div>
            ))}
          </div>
          <div className="text-micro text-faint mt-1.5">
            同一条 token 铺在四档面上 —— 固定灰做不到这件事
          </div>
        </Row>

        <Row label="阴影">
          <div className="flex gap-3">
            {(['popover', 'dialog', 'command'] as const).map((k) => (
              <div
                key={k}
                className="bg-raised rounded-ui p-2.5 text-micro border border-hairline"
                style={{ boxShadow: `var(--shadow-${k})` }}
              >
                {k}
              </div>
            ))}
          </div>
          <div className="text-micro text-faint mt-1.5">全系统只有这三个，内联元素一律没有</div>
        </Row>

        <Row label="状态色">
          <div className="flex gap-2">
            {STATUS.map((s) => (
              <div key={s.name} className={`${s.cls} ${s.on} rounded-ui px-2.5 py-1 text-micro`}>
                {s.name}
              </div>
            ))}
          </div>
          <div className="flex gap-2 mt-2">
            {STATUS.map((s) => (
              <span key={s.name} className="text-micro" style={{ color: `var(--ui-${s.name})` }}>
                {s.name} 作为文字
              </span>
            ))}
          </div>
        </Row>

        <Row label="字号">
          <div className="bg-panel border border-hairline rounded-ui p-2.5 space-y-1">
            {TYPE.map((t) => (
              <div key={t.name} className={`${t.cls} flex items-baseline gap-2`}>
                <span className="text-micro text-faint w-14 shrink-0">{t.name}</span>
                <span className="truncate">密度靠收紧行高和内边距，一屏多放信息</span>
              </div>
            ))}
          </div>
        </Row>

        <Row label="时长">
          <button
            onClick={() => setLifted((v) => !v)}
            className="bg-panel border border-hairline rounded-ui px-2.5 py-1 text-micro"
          >
            点一下看三档
          </button>
          <div className="flex gap-2 mt-2">
            {(['fast', 'base', 'slow'] as const).map((k) => (
              <div key={k} className="flex-1">
                <div className="text-micro text-faint mb-1">{k}</div>
                <div className="bg-panel border border-hairline rounded-ui h-7 overflow-hidden">
                  <div
                    className="bg-accent h-full"
                    style={{
                      width: lifted ? '100%' : '8%',
                      transition: `width var(--dur-${k}) var(--ease-ui)`,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </Row>
      </div>
    </div>
  )
}

export function TokenSheet() {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <Sheet theme="light" />
      <Sheet theme="dark" />
    </div>
  )
}
