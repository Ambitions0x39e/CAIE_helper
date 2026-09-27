/** What `analysis()` and the grading events carry. Mirrors app_web/api.py. */

import type { PaperType } from '../../lib/types'

export interface QuestionCfg {
  max_marks: number
  mark_scheme: string
}

export interface Analysis {
  ready: boolean
  paper_type?: PaperType
  paper_id?: string
  total_marks?: number
  questions?: Record<string, QuestionCfg>
  answer_path?: string | null
  /** Pages in the answer PDF; 0 when none was picked. */
  total_pages?: number
  /** Questions the segmenter located, so their region can be cropped. The
   * rest grade off whole pages instead. */
  matched?: string[]
  clips?: Record<string, { page_idx: number; y_top: number; y_bottom: number }[]>
}

export interface MarkDetail {
  code: string
  awarded: boolean
  reason: string
}

/** Mirrors `core.models.ErrorType`. */
export type ErrorType = 'concept' | 'method' | 'slip' | 'misread' | 'wording' | 'blank'

export const ERROR_LABELS: Record<ErrorType, string> = {
  concept: '概念',
  method: '方法',
  slip: '失误',
  misread: '审题',
  wording: '表述',
  blank: '未作答',
}

export interface QuestionResult {
  question: string
  marks: MarkDetail[]
  total: number
  max: number
  comment: string
  /** Syllabus topic the model picked. null whenever no syllabus was
   * available, the component is not in it, or the model could not place the
   * question — all three land in 未分类 downstream. */
  topic: string | null
  /** Why the marks were lost; null at full marks or when unclassified. */
  error_type: ErrorType | null
}

export interface GradeProgress {
  done: number
  total: number
  /** Set while the subject's syllabus is being fetched, before any question
   * is graded. */
  fetching?: string
}
