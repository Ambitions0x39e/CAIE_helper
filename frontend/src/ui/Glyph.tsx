import {
  Brain,
  Briefcase,
  Calculator,
  Dna,
  File,
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
import type { CSSProperties, ComponentType, SVGProps } from 'react'

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

export function Glyph({
  name,
  className,
  style,
}: {
  name: string
  className?: string
  style?: CSSProperties
}) {
  const Icon = ICONS[name] ?? FileText
  return <Icon className={className} style={style} aria-hidden />
}

/** The size of the subject mark inside the sheet, and the stroke that keeps
 * the two weights level: drawn at 30% of the box, a glyph's own stroke lands
 * at 30% of the sheet's, so it is scaled back up by the same factor. */
const INSET = 0.3
const SHEET_STROKE = 1

/** One paper: a sheet with its subject set into the middle of it.
 *
 * A wall of subject glyphs reads as a wall of subjects, not of papers — the
 * sheet is what says these are documents, and the mark inside is what tells
 * them apart. Both are outlines in `currentColor`, so the caller still colours
 * the whole thing with one class. */
export function PaperGlyph({ name, className }: { name: string; className?: string }) {
  return (
    <span className={`relative inline-flex shrink-0 ${className ?? ''}`}>
      <File className="size-full" strokeWidth={SHEET_STROKE} aria-hidden />
      <Glyph
        name={name}
        className="absolute inset-0 m-auto"
        style={{
          width: `${INSET * 100}%`,
          height: `${INSET * 100}%`,
          strokeWidth: SHEET_STROKE / INSET,
        }}
      />
    </span>
  )
}
