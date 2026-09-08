import type { PaperRecord } from './types'

export type TabId = 'download' | 'manage' | 'mark' | 'settings'

/** Where a command lands you.
 *
 * Data, never a callback. That is what keeps the palette to navigation: there
 * is no field here a delete, a send or a grading run could hide in, so PRD
 * F1.4 holds by construction rather than by review.
 *
 * `open` is the one destination that is not a page — F1.3 asks that a paper
 * found in the palette opens its PDF — and it is still just a path.
 */
export interface Intent {
  tab?: TabId
  /** The tab's own sub-view: download's VIEWS, manage's SECTIONS, settings' PAGES. */
  view?: string
  /** One level further down: Organize's layout, Mistakes' view. */
  sub?: string
  /** Whatever the destination makes of it — a paper id to prefill, a topic to
   * filter by. A tab that has no use for one ignores it. */
  param?: string
  /** A local PDF to hand to the system viewer. */
  open?: string
}

export interface Command {
  id: string
  /** Shown as the list heading, and matched like any other word — which is
   * what makes `设置 API` reach the Grader API page. */
  group: string
  label: string
  /** Aliases, lowercase. English words and Chinese mnemonics (`kg` for 课纲)
   * are the same thing to the matcher, so they share one array. */
  keys: string[]
  intent: Intent
}

export const COMMANDS: readonly Command[] = [
  // 切 tab —— 批改 gets only this one entry. The three steps are a flow, and a
  // flow should not be entered from the middle.
  { id: 'tab.download', group: '切换', label: '下载', keys: ['dl', 'download', 'xz'], intent: { tab: 'download' } },
  { id: 'tab.manage', group: '切换', label: '管理', keys: ['manage', 'papers', 'gl'], intent: { tab: 'manage' } },
  { id: 'tab.mark', group: '切换', label: '批改', keys: ['mark', 'grade', 'pg'], intent: { tab: 'mark' } },
  { id: 'tab.settings', group: '切换', label: '设置', keys: ['settings', 'prefs', 'sz'], intent: { tab: 'settings' } },

  { id: 'dl.request', group: '下载', label: '按考季查询', keys: ['session', 'query', 'kj'], intent: { tab: 'download', view: 'request' } },
  { id: 'dl.byid', group: '下载', label: '按 ID 下载', keys: ['id'], intent: { tab: 'download', view: 'by_id' } },
  { id: 'dl.gt', group: '下载', label: '分数线', keys: ['gt', 'threshold'], intent: { tab: 'download', view: 'gt' } },

  { id: 'mg.overview', group: '管理', label: '总览', keys: ['overview', 'stats', 'zl'], intent: { tab: 'manage', view: 'overview' } },
  { id: 'mg.organize', group: '管理', label: '整理', keys: ['organize', 'files'], intent: { tab: 'manage', view: 'organize' } },
  { id: 'mg.icons', group: '管理', label: '图标视图', keys: ['icons', 'grid', 'tb'], intent: { tab: 'manage', view: 'organize', sub: 'icons' } },
  { id: 'mg.detail', group: '管理', label: '详细信息', keys: ['detail', 'list', 'lb'], intent: { tab: 'manage', view: 'organize', sub: 'detail' } },
  { id: 'mg.mistakes', group: '管理', label: '错题', keys: ['mistakes', 'wrong', 'ct'], intent: { tab: 'manage', view: 'mistakes' } },
  { id: 'mg.bypaper', group: '管理', label: '错题按卷', keys: ['by-paper'], intent: { tab: 'manage', view: 'mistakes', sub: 'paper' } },
  { id: 'mg.bytopic', group: '管理', label: '错题按 topic', keys: ['by-topic'], intent: { tab: 'manage', view: 'mistakes', sub: 'topic' } },

  { id: 'st.mail', group: '设置', label: 'SMTP / GoodNotes', keys: ['mail', 'gn'], intent: { tab: 'settings', view: 'mail' } },
  { id: 'st.grader', group: '设置', label: 'Grader API', keys: ['api', 'key'], intent: { tab: 'settings', view: 'grader' } },
  { id: 'st.syllabus', group: '设置', label: '已存 syllabus', keys: ['syllabus', 'kg'], intent: { tab: 'settings', view: 'syllabus' } },
  { id: 'st.about', group: '设置', label: '关于', keys: ['about', 'version'], intent: { tab: 'settings', view: 'about' } },
  // Takes you to 关于; it does not press the button for you.
  { id: 'st.update', group: '设置', label: '检查更新', keys: ['update', 'upgrade'], intent: { tab: 'settings', view: 'about' } },
  { id: 'st.theme', group: '设置', label: '主题', keys: ['theme', 'dark', 'zt'], intent: { tab: 'settings', view: 'theme' } },
  { id: 'st.palette', group: '设置', label: '命令面板', keys: ['palette', 'mlmb'], intent: { tab: 'settings', view: 'palette' } },
]

export interface Query {
  /** `file` searches papers and nothing else; `default` searches commands and
   * topics and never papers. Several hundred records must not pour out of the
   * palette because you typed `9`. */
  mode: 'file' | 'default'
  /** Words that must *all* match, so `设置 API` narrows to one page. */
  tokens: string[]
  /** Digit-bearing words, carried to the destination as they were typed. No
   * command contains a digit, so a word with one is never a filter. */
  param?: string
}

/** `file`, `file:`, `file 9709 s25` — the prefix is what puts the palette into
 * paper mode. `filename` is not: the separator has to be there. */
const FILE_MODE = /^file(?:[:\s]([\s\S]*))?$/i

export function parseQuery(raw: string): Query {
  const trimmed = raw.trim()
  const file = FILE_MODE.exec(trimmed)
  if (file) return { mode: 'file', tokens: [(file[1] ?? '').trim().toLowerCase()] }

  const words = trimmed.toLowerCase().split(/\s+/).filter(Boolean)
  const tokens = words.filter((w) => !/\d/.test(w))
  const digits = words.filter((w) => /\d/.test(w))
  return { mode: 'default', tokens, ...(digits.length > 0 && { param: digits.join(' ') }) }
}

const haystack = (c: Command) => `${c.label} ${c.group} ${c.keys.join(' ')}`.toLowerCase()

/** Substring, not fuzzy scoring. The aliases are hand-picked, so `zl` should
 * mean 总览 and nothing else — a scorer would helpfully offer three more. */
export function matchCommands(q: Query, commands: readonly Command[] = COMMANDS): Command[] {
  // Digits alone say "a paper", and papers are only reachable through `file`.
  // Without this an all-digit query leaves no filter words behind, and "every
  // word matches" would vacuously admit the whole registry.
  if (q.tokens.length === 0 && q.param !== undefined) return []
  const hits = commands.filter((c) => {
    const hay = haystack(c)
    return q.tokens.every((t) => hay.includes(t))
  })
  if (q.param === undefined) return hits
  return hits.map((c) => ({ ...c, intent: { ...c.intent, param: q.param } }))
}

/** Ignore everything that is not a letter or a digit, so `9709 s25 12`,
 * `9709_s25_12` and `9709s25` all find the same paper. */
const bare = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '')

export function matchPapers(q: Query, papers: readonly PaperRecord[]): Command[] {
  const needle = bare(q.tokens[0] ?? '')
  return papers
    .filter((p) => bare(p.paper_id).includes(needle))
    .map((p) => ({
      id: `paper.${p.paper_id}`,
      group: '卷子',
      label: p.paper_id,
      keys: [],
      intent: { open: p.qp_path },
    }))
}

/** One entry per `<syllabus> · <topic>` key, which is also what Mistakes
 * filters by — so the command carries the key straight through. */
export function topicCommands(keys: readonly string[]): Command[] {
  return keys.map((k) => ({
    id: `topic.${k}`,
    group: '管理',
    label: k,
    keys: ['错题', 'mistakes', 'ct'],
    intent: { tab: 'manage' as const, view: 'mistakes', sub: 'topic', param: k },
  }))
}

// --- Preferences and usage counts -------------------------------------------
//
// `app_web/main.py` runs the webview with `private_mode=False`, which is what
// makes localStorage outlive a restart. Every read is still guarded: a browser
// with site data blocked throws on access rather than returning null.

export type EmptyMode = 'plain' | 'frequent'

const MODE_KEY = 'cie.palette.emptyMode'
const COUNTS_KEY = 'cie.palette.counts'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

function write(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // A preference is not worth failing a render over.
  }
}

export function emptyMode(): EmptyMode {
  return read<EmptyMode>(MODE_KEY, 'plain') === 'frequent' ? 'frequent' : 'plain'
}

export function setEmptyMode(mode: EmptyMode): void {
  write(MODE_KEY, mode)
}

export type Theme = 'system' | 'light' | 'dark'

const THEME_KEY = 'cie.theme'

export function theme(): Theme {
  const t = read<Theme>(THEME_KEY, 'system')
  return t === 'light' || t === 'dark' ? t : 'system'
}

export function setTheme(t: Theme): void {
  write(THEME_KEY, t)
  applyTheme(t)
}

/** Puts the choice where tokens.css can see it. `system` removes the attribute
 * rather than writing one: an unstamped root is what the `prefers-color-scheme`
 * query matches, and any other value pins the page to light on a dark desktop. */
export function applyTheme(t: Theme): void {
  const root = document.documentElement
  if (t === 'system') delete root.dataset.theme
  else root.dataset.theme = t
}

/** Only static commands are counted. Papers live behind the `file` prefix and
 * could never reach this list anyway. */
export function bumpUsage(id: string): void {
  if (!COMMANDS.some((c) => c.id === id)) return
  const counts = read<Record<string, number>>(COUNTS_KEY, {})
  write(COUNTS_KEY, { ...counts, [id]: (counts[id] ?? 0) + 1 })
}

export const FREQUENT_COUNT = 5

export function frequent(commands: readonly Command[] = COMMANDS): Command[] {
  const counts = read<Record<string, number>>(COUNTS_KEY, {})
  return commands
    .filter((c) => (counts[c.id] ?? 0) > 0)
    .sort((a, b) => (counts[b.id] ?? 0) - (counts[a.id] ?? 0))
    .slice(0, FREQUENT_COUNT)
}
