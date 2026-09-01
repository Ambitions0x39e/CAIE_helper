/** Shapes the Python side returns, i.e. `model_dump(mode="json")` of the
 * Pydantic models in `core/` and `modules/`.
 *
 * ponytail: hand-mirrored, so nothing stops these drifting from the models
 * they describe — rename a field in Python and TypeScript keeps compiling
 * against the old name. Four shapes is small enough to re-read; once this file
 * covers roughly twenty, generate it instead (`model_json_schema()` on the
 * Python side into `json-schema-to-typescript`) rather than keep proof-reading.
 */

// -- core.config_store -------------------------------------------------------

/** `PaperType` — which grading path a paper takes, when it is known up front. */
export type PaperType = 'mcq' | 'math'

export interface PaperTypeConfig {
  digit: string
  name: string
  /** null means "not recorded" — the Mark tab leaves the user's choice alone. */
  grading: PaperType | null
}

export interface SyllabusConfig {
  syllabus_id: string
  name: string
  paper_types: PaperTypeConfig[]
}

// -- core.models -------------------------------------------------------------

export type PaperStatus = 'Pending' | 'Completed'

export interface PaperRecord {
  paper_id: string
  status: PaperStatus
  qp_path: string
  ms_path: string
  /** Only set once Completed — `completed_requires_scores` enforces that. */
  score_raw: number | null
  score_total: number | null
  sent_to_gn: boolean
  /** ISO 8601, or null on rows written before the column existed. */
  timestamp: string | null
  /** Computed field: null unless both scores are present and total > 0. */
  percentage: number | null
}

export interface MistakeRecord {
  paper_id: string
  question_id: string
  topic_id: string | null
  topic_name: string | null
  score: number
  max_score: number
  comment: string
  timestamp: string
}

// -- modules.downloader ------------------------------------------------------

export type QueryKind = 'qp' | 'gt' | 'other'
export type QuerySeason = 'm' | 's' | 'w'
/** Capitalised exactly as the Python Literal spells them — these strings go
 * straight into DownloadRequest, which is strict. */
export type DownloadSource = 'CIEFrank' | 'PapaCambridge'

export interface QueryEntry {
  paper_id: string
  kind: QueryKind
  already_downloaded: boolean
  /** Only ever true on a `qp` entry: the session also lists its `_in_` insert. */
  has_insert: boolean
}

export interface QueryResult {
  success: boolean
  entries: QueryEntry[]
  error: string | null
}

export interface DownloadResult {
  success: boolean
  paper_id: string
  qp_path: string | null
  ms_path: string | null
  error: string | null
  /** Only a `download(insert=true)` fills these. Both null = paper has no insert. */
  insert_path: string | null
  /** Set when the insert should have been fetchable but wasn't. `success` stays
   * true — QP+MS are on disk — so this is a warning, not a failure. */
  insert_error: string | null
}

// -- core.gt_parser ----------------------------------------------------------

export interface GradeThreshold {
  option: string
  max_weighted: number
  /** Two-digit component numbers, e.g. ["11", "21"] — not full paper ids. */
  components: string[]
  /** grade -> mark, e.g. { "A*": 180, A: 165 }. */
  thresholds: Record<string, number>
}

/** `parse_gt` returns a GTDocument flattened next to a `success` flag. */
export type GTResult =
  | { success: true; syllabus_id: string; session: string; options: GradeThreshold[] }
  | { success: false; error: string }

// -- modules.mailer ----------------------------------------------------------

export interface MailResult {
  success: boolean
  paper_id: string
  recipient: string | null
  error: string | null
}

/** The shape every operation-style call returns. */
export interface SimpleResult {
  success: boolean
  error?: string | null
}

/** A save-dialog call. `cancelled` is a normal outcome, not a failure —
 * nothing is written until a destination is picked. */
export interface SaveResult {
  success: boolean
  path?: string
  cancelled?: boolean
  error?: string | null
}

/** Every failed js_api call looks like this, including validation failures. */
export interface Failure {
  success: false
  error: string
}
