/** What `analysis()` and the grading events carry. Mirrors app_web/api.py. */

export interface QuestionCfg {
  max_marks: number
  mark_scheme: string
}

export interface Analysis {
  ready: boolean
  paper_type?: 'math' | 'mcq'
  paper_id?: string
  total_marks?: number
  questions?: Record<string, QuestionCfg>
  answer_path?: string | null
  /** Questions the segmenter located, so their region can be cropped. */
  matched?: string[]
  /** The rest — they grade off whole pages instead. */
  unmatched?: string[]
  clips?: Record<string, { page_idx: number; y_top: number; y_bottom: number }[]>
}

export interface MarkDetail {
  code: string
  awarded: boolean
  reason: string
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
}
