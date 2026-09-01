import { useEffect, useState } from 'react'
import { PushTrack } from './PushTrack'

declare global {
  interface Window {
    pywebview?: { api: { ping(): Promise<string>; open_external(url: string): Promise<boolean> } }
  }
}

/** Deliberately mismatched heights: the short step must pin to the top, not float. */
const STEPS = [
  { name: '选卷', rows: 9 },
  { name: '批改', rows: 2 },
  { name: '结果', rows: 5 },
]

function StepBody({ name, rows }: { name: string; rows: number }) {
  return (
    <div className="border border-hairline bg-panel rounded-md p-4">
      <div className="text-sm font-medium mb-3">{name}</div>
      <div className="space-y-2">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="h-5 rounded bg-black/5" style={{ width: `${95 - ((i * 13) % 40)}%` }} />
        ))}
      </div>
    </div>
  )
}

export default function App() {
  const [step, setStep] = useState(0)
  const [dir, setDir] = useState(1)
  const [pong, setPong] = useState('—')

  const go = (next: number) => {
    if (next < 0 || next >= STEPS.length) return
    setDir(next > step ? 1 : -1)
    setStep(next)
  }

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
    <div className="min-h-screen bg-page text-[13px] text-black p-6">
      <div className="mx-auto max-w-2xl space-y-4">
        <div className="flex items-center gap-2">
          {STEPS.map((s, i) => (
            <button
              key={s.name}
              onClick={() => go(i)}
              className={`px-3 py-1.5 rounded-md border border-hairline ${
                i === step ? 'bg-panel font-medium' : 'bg-transparent text-black/50'
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>

        <PushTrack step={step} dir={dir}>
          <StepBody {...STEPS[step]} />
        </PushTrack>

        <div className="flex items-center gap-2">
          <button
            onClick={() => go(step - 1)}
            disabled={step === 0}
            className="px-3 py-1.5 rounded-md border border-hairline bg-panel disabled:opacity-40"
          >
            上一步
          </button>
          <button
            onClick={() => go(step + 1)}
            disabled={step === STEPS.length - 1}
            className="px-3 py-1.5 rounded-md border border-hairline bg-panel disabled:opacity-40"
          >
            下一步
          </button>
          <button
            onClick={async () => setPong((await window.pywebview?.api.ping()) ?? 'no bridge')}
            className="px-3 py-1.5 rounded-md border border-hairline bg-panel"
          >
            ping
          </button>
          <span className="text-black/50">js_api: {pong}</span>
          <button
            onClick={() => window.pywebview?.api.open_external('https://github.com/Ambitions0x39e/CAIE_helper')}
            className="ml-auto px-3 py-1.5 rounded-md border border-hairline bg-panel"
          >
            外链
          </button>
        </div>

        <p className="selectable text-black/50">
          这一段是正文，可以选中。上面的按钮和标签不行。
        </p>
      </div>
    </div>
  )
}
