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

// -- modules.mailer ----------------------------------------------------------

export interface MailResult {
  success: boolean
  paper_id: string
  recipient: string | null
  error: string | null
}

/** Every failed js_api call looks like this, including validation failures. */
export interface Failure {
  success: false
  error: string
}
