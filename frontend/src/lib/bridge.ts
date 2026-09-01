/** The only place that touches `window.pywebview`.
 *
 * **`window.pywebview` existing does not mean the API is callable.** pywebview
 * injects the object early with an empty `api`, fills it in via `_createApi`,
 * and only then dispatches `pywebviewready` (see `webview/js/api.js` and
 * `finish.js`). So `window.pywebview?.api.foo()` is not a guard — it passes and
 * then throws on an undefined method. Anything running at mount has to wait for
 * the event; probing for a known method is what tells the two states apart.
 *
 * The bridge is also legitimately absent: opening the Vite dev server in an
 * ordinary browser to work on styling gets no injection at all. That degrades
 * to `absent` rather than hanging, so the UI can still be looked at.
 */
import type {
  DownloadResult,
  GTResult,
  MailResult,
  MistakeRecord,
  PaperRecord,
  QueryResult,
  QuerySeason,
  DownloadSource,
  SaveResult,
  SimpleResult,
  SyllabusConfig,
} from './types'

/** Mirrors the public methods of `app_web/api.py::Api`. */
export interface PyApi {
  ping(): Promise<string>
  open_external(url: string): Promise<boolean>
  syllabuses(): Promise<SyllabusConfig[]>
  query_session(
    subject: string, year: string, season: QuerySeason,
  ): Promise<QueryResult>
  download_paper(
    paper_id: string, source?: DownloadSource, insert?: boolean,
  ): Promise<DownloadResult>
  record_paper(paper_id: string): Promise<DownloadResult>
  downloaded_ids(): Promise<string[]>
  parse_gt(pdf_path: string, session: string): Promise<GTResult>
  papers(): Promise<PaperRecord[]>
  submit_score(
    paper_id: string, score_raw: number, score_total: number,
  ): Promise<SimpleResult>
  delete_paper(paper_id: string, delete_local_files?: boolean): Promise<SimpleResult>
  open_pdf(path: string): Promise<SimpleResult>
  mistakes(): Promise<MistakeRecord[]>
  mistake_topic_keys(): Promise<string[]>
  topics_for(paper_id: string): Promise<Record<string, string> | null>
  retag_mistake(
    paper_id: string, question_id: string, topic_id: string | null,
  ): Promise<SimpleResult>
  export_mistakes_csv(paper_ids?: string[]): Promise<SaveResult>
  export_mistakes_pdf(
    paper_ids: string[], with_ms: boolean,
  ): Promise<SaveResult & { warnings?: string[] }>
  mail_settings(): Promise<Record<string, never> | {
    configured: boolean
    smtp_server?: string
    smtp_port?: number
    sender_email?: string
    goodnotes_email?: string
  }>
  save_mail_settings(
    smtp_server: string, smtp_port: number, sender_email: string,
    sender_app_password: string, goodnotes_email: string,
  ): Promise<SimpleResult>
  grader_settings(): Promise<{
    configured: boolean
    base_url?: string
    model?: string
    dpi?: number
    enable_thinking?: boolean
  }>
  save_grader_settings(
    api_key: string, base_url: string, model: string,
  ): Promise<SimpleResult>
  syllabuses_stored(): Promise<{
    subject_id: string; topic_count: number; components: string[]; path: string
  }[]>
  forget_syllabus(subject_id: string): Promise<SimpleResult>
  app_version(): Promise<string>
  check_update(): Promise<{
    success: boolean
    error?: string | null
    update_available?: boolean
    latest_version?: string | null
    release_notes?: string | null
    download_url?: string | null
  }>
  pick_pdf(title?: string): Promise<string | null>
  start_analysis(
    ms_path: string, paper_type: string, answer_path: string | null,
    start_page: number | null, force: boolean,
  ): Promise<SimpleResult>
  analysis(): Promise<{ ready: boolean; [k: string]: unknown }>
  start_grading(question_ids: string[]): Promise<SimpleResult>
  start_mcq_detection(
    qp_path: string, source_filename?: string,
  ): Promise<SimpleResult>
  score_mcq(manual: Record<string, string>): Promise<
    SimpleResult & {
      score: number
      total: number
      per_question: Record<string, boolean>
      answers: Record<string, string>
    }
  >
  confirm_mcq(
    paper_id: string, manual: Record<string, string>,
  ): Promise<SimpleResult & { score?: number; total?: number }>
  job_running(): Promise<string | null>
  confirm_results(
    paper_id: string, overrides: Record<string, number>,
  ): Promise<SimpleResult & { score?: number; max_score?: number }>
  mail_ready(): Promise<boolean>
  send_to_goodnotes(paper_id: string, qp_path: string): Promise<MailResult>
}

declare global {
  interface Window {
    // Partial: the object arrives before its methods do.
    pywebview?: { api: Partial<PyApi> }
  }
}

/** Long enough to cover a slow injection, short enough to not look like a hang. */
const READY_TIMEOUT_MS = 5000

export const BRIDGE_ABSENT =
  '没有连上 Python 端 —— 这个页面是在普通浏览器里打开的。数据相关的操作都不会有反应；要完整功能请用 uv run python -m app_web 开应用窗口。'

function probe(): PyApi | null {
  // A method, not the object: the object is there from the first frame.
  return typeof window.pywebview?.api?.ping === 'function'
    ? (window.pywebview.api as PyApi)
    : null
}

let pending: Promise<PyApi | null> | null = null

/** Resolves with the API once it is injected, or null if it never arrives. */
export function bridge(): Promise<PyApi | null> {
  pending ??= new Promise<PyApi | null>((resolve) => {
    const found = probe()
    if (found) {
      resolve(found)
      return
    }
    const settle = () => {
      clearTimeout(timer)
      window.removeEventListener('pywebviewready', settle)
      resolve(probe())
    }
    const timer = setTimeout(settle, READY_TIMEOUT_MS)
    window.addEventListener('pywebviewready', settle)
  })
  return pending
}

/** The API, or a thrown error naming why there isn't one. */
export async function api(): Promise<PyApi> {
  const found = await bridge()
  if (!found) throw new Error(BRIDGE_ABSENT)
  return found
}
