import {
  Brain,
  Briefcase,
  Calculator,
  Dna,
  FileText,
  FlaskConical,
  Globe,
  Landmark,
  Languages,
  Monitor,
  Scroll,
  Sigma,
  Terminal,
  TrendingUp,
  Volleyball,
  Zap,
} from 'lucide-react'
import type { ComponentType, SVGProps } from 'react'

/** The names `subjectGlyph` returns, bound to one icon set.
 *
 * The mapping lives here rather than in papers.ts so that file stays free of
 * JSX and remains testable under `node --test`. */
const ICONS: Record<string, ComponentType<SVGProps<SVGSVGElement>>> = {
  flask: FlaskConical,
  bolt: Zap,
  dna: Dna,
  sigma: Sigma,
  calculator: Calculator,
  terminal: Terminal,
  monitor: Monitor,
  brain: Brain,
  globe: Globe,
  scroll: Scroll,
  bank: Landmark,
  'trending-up': TrendingUp,
  briefcase: Briefcase,
  football: Volleyball,
  languages: Languages,
  'file-text': FileText,
}

export function Glyph({ name, className }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? FileText
  return <Icon className={className} aria-hidden />
}
