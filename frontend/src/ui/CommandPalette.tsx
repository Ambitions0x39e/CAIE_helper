import { Command } from 'cmdk'
import { type KeyboardEvent, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/bridge'
import {
  COMMANDS,
  type Command as Cmd,
  type Intent,
  bumpUsage,
  emptyMode,
  frequent,
  matchCommands,
  matchPapers,
  parseQuery,
  topicCommands,
} from '../lib/commands'
import type { PaperRecord } from '../lib/types'

/** The heading the most-used commands sit under. Not a `group` any command
 * carries — it is assembled at open time, so the same command can appear here
 * and under its own heading. */
const FREQUENT = '常用'

/** Ctrl+K / Cmd+K.
 *
 * The shell is a native `<dialog>` shown with `showModal()`, same as
 * `ui/Dialog.tsx`: the top layer, the backdrop, the focus trap, inertness for
 * everything behind and Esc-to-close all come from the browser. cmdk is here
 * for the list — the roving highlight, scrolling it into view, and the
 * listbox semantics — not for its shell and not for its scoring.
 */
export function CommandPalette({
  open,
  onClose,
  onRun,
}: {
  open: boolean
  onClose: () => void
  onRun: (intent: Intent) => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const [q, setQ] = useState('')
  const [picked, setPicked] = useState('')
  const [papers, setPapers] = useState<PaperRecord[]>([])
  const [topics, setTopics] = useState<string[]>([])

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) {
      el.showModal()
      // showModal() puts focus on the dialog, not on the box you are meant to
      // type into — and `autoFocus` only fires on mount, while this dialog is
      // mounted once and reopened many times. Without this the palette opens
      // deaf and the whole thing has to be driven with the mouse.
      input.current?.focus()
    }
    if (!open && el.open) el.close()
  }, [open])

  // Both come off local files, so one read per opening is cheap and the list
  // stays instant while typing. A fresh read each time also means a paper
  // downloaded a minute ago is already in here.
  useEffect(() => {
    if (!open) return
    api()
      .then((a) => Promise.all([a.papers(), a.mistake_topic_keys()]))
      .then(([p, t]) => {
        setPapers(p)
        setTopics(t)
      })
      .catch(() => {
        setPapers([])
        setTopics([])
      })
  }, [open])

  const blank = q.trim() === ''
  const query = useMemo(() => parseQuery(q), [q])
  const mode = emptyMode()

  /** 简洁, before anything is typed: the panel is the input box and nothing
   * else. Not an empty result — there is no query yet to have missed. */
  const bare = blank && query.mode === 'default' && mode === 'plain'

  const results = useMemo(() => {
    if (query.mode === 'file') return matchPapers(query, papers)
    // Topics join the pool only once something has been typed — they are
    // runtime entries, and an empty palette should read as a table of
    // contents, not as a dump of the mistake book.
    return matchCommands(query, blank ? COMMANDS : [...COMMANDS, ...topicCommands(topics)])
  }, [query, blank, papers, topics])

  const groups = useMemo(() => {
    const out = new Map<string, Cmd[]>()
    if (blank && query.mode === 'default') {
      if (mode === 'plain') return []
      const top = frequent()
      if (top.length > 0) out.set(FREQUENT, top)
    }
    for (const c of results) out.set(c.group, [...(out.get(c.group) ?? []), c])
    return [...out.entries()]
  }, [results, blank, query.mode, mode])

  /** cmdk's own default lands on an arbitrary row — with filtering off its
   * scores are all equal and it settles on whatever registered first, which
   * is not the row at the top of the list. Enter on a freshly opened palette
   * has to run the thing you are looking at, so the highlight is ours: keep
   * the pick while it is still on screen, otherwise fall to the first row.
   * Derived during render, so retyping re-aims it without an extra pass. */
  const rows = groups.flatMap(([group, items]) => items.map((c) => `${group}:${c.id}`))
  const value = rows.includes(picked) ? picked : (rows[0] ?? '')

  /** Every way out goes through here, so the box is empty next time however
   * it was closed — Esc, the backdrop, or running something. */
  const close = () => {
    setQ('')
    setPicked('')
    onClose()
  }

  const run = (c: Cmd) => {
    bumpUsage(c.id)
    onRun(c.intent)
    close()
  }

  // While an IME is composing, the browser still dispatches Enter and the
  // arrows — typing 下载 goes through `xiazai` first, and the Enter that
  // commits those characters would otherwise run whatever is highlighted.
  // Capture phase, so cmdk never sees them; the IME itself is unaffected,
  // it reads the keys below the DOM.
  const holdForIme = (e: KeyboardEvent<HTMLDivElement>) => {
    const composing = e.nativeEvent.isComposing || e.keyCode === 229
    if (composing && (e.key === 'Enter' || e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.stopPropagation()
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={close}
      onClick={(e) => e.target === ref.current && close()}
      // Sits high rather than centred: a palette is something you type into,
      // and the results grow downwards into space that is already empty.
      //
      // The scrim is barely there — it says "this is on top" and no more. The
      // lifting is the shadow's job, and a heavy scrim would flatten it by
      // darkening the very ground the shadow falls on.
      className="mx-auto mt-[12vh] mb-auto w-[min(36rem,90vw)] rounded-ui border border-hairline
                 bg-panel p-0 text-ink backdrop:bg-black/8"
      style={{ boxShadow: 'var(--shadow-command)' }}
    >
      <div onKeyDownCapture={holdForIme}>
        <Command shouldFilter={false} loop label="命令面板" value={value} onValueChange={setPicked}>
          <Command.Input
            ref={input}
            value={q}
            onValueChange={setQ}
            placeholder="输入命令，或 file 加卷号"
            className={`w-full bg-transparent px-4 py-3 text-body text-ink outline-none
                        placeholder:text-faint ${bare ? '' : 'border-b border-hairline'}`}
          />
          {!bare && (
            <Command.List className="max-h-[min(24rem,60vh)] overflow-y-auto p-1.5">
              {/* Only once something has been typed: with an empty box nothing
                  has been missed, so saying so would be a lie. */}
              {!blank && (
                <Command.Empty className="px-3 py-6 text-center text-caption text-muted">
                  没有匹配的命令
                </Command.Empty>
              )}
              {groups.map(([group, items]) => (
                <Command.Group
                  key={group}
                  heading={group}
                  className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pt-2
                             [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-caption
                             [&_[cmdk-group-heading]]:text-faint"
                >
                  {items.map((c) => (
                    <Command.Item
                      // The same command can sit under 常用 and under its own
                      // heading; cmdk keys the highlight by value, so the
                      // heading has to be part of it.
                      key={`${group}:${c.id}`}
                      value={`${group}:${c.id}`}
                      onSelect={() => run(c)}
                      className="flex cursor-default items-center gap-3 rounded-ui px-2.5 py-1.5
                                 text-body data-[selected=true]:bg-raised
                                 data-[selected=true]:text-accent"
                    >
                      <span className="min-w-0 flex-1 truncate">{c.label}</span>
                      {c.intent.param !== undefined && c.intent.open === undefined && (
                        <span className="shrink-0 text-caption text-faint">{c.intent.param}</span>
                      )}
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
          )}
        </Command>
      </div>
    </dialog>
  )
}
