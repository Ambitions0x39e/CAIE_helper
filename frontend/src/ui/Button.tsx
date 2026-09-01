import type { ButtonHTMLAttributes } from 'react'

type Tone = 'accent' | 'neutral'

const TONE: Record<Tone, string> = {
  accent: 'bg-accent text-on-accent border-transparent',
  neutral: 'bg-raised text-ink border-hairline',
}

export function Button({
  tone = 'neutral',
  ...button
}: { tone?: Tone } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...button}
      className={`rounded-ui border px-3 py-1.5 text-body transition-opacity
                  disabled:opacity-40 ${TONE[tone]} ${button.className ?? ''}`}
      style={{ transitionDuration: 'var(--dur-fast)', ...button.style }}
    />
  )
}
