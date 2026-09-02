# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 死规则：成品不留修改痕迹

**改完的东西，读起来必须像它一开始就是对的。**

做了番茄炒蛋，自己放了青椒，被指出后把青椒挑掉 —— 端上桌的就是番茄炒蛋。
不叫「番茄炒蛋（不放青椒版）」，也不在旁边贴一张纸条说明为什么没有青椒。

成品里不允许出现：

- 版本对照 —— 「此前……的说法已经过时」「原本是 X，现在改成 Y」
- 解释某处为什么被删掉 / 为什么现在不这么写了
- 「不再」「已改为」「新版」这类只有知道修改历史才看得懂的措辞
- 给自己上一版留的注解、免责声明、致歉

读的人不知道也不需要知道中间过程。留痕只会让成品显得犹豫，而且把已经作废
的说法又复述了一遍 —— 等于把错误内容重新讲给读者听。

**改动记在该记的地方**：commit message、`dev/CIE-Helper-Notes/update_history.md`、
release notes。那些地方是写「变化」的；成品是写「现状」的。

适用范围是用户会读到的一切：使用手册、官网、应用内文案、README、错误提示。
代码注释同理 —— 纯描述「这里以前是什么」的要删。

**例外**：用实测证据说明「为什么代码必须这样写」的注释要留。那不是痕迹，
是防止别人重新踩坑的护栏，属于现状的一部分（`core/gt_parser.py` 的
「Never re-introduce a per-file CID table」就是这类）。区别在于句子的主语
是**代码**还是**改动**。

## Commands

```bash
# Run the app (needs `npm run build --prefix frontend` once, for the UI)
uv run python -m app_web

# Install dependencies
uv sync

# Add a dependency
uv add <package>

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check — name the three packages. `tests/` is outside strict mode
# (see [[tool.mypy.overrides]]), so a bare `.` reports dozens of errors that
# are not the app's.
uv run mypy app_web core modules

# Run tests
uv run pytest
```

## Building the packaged app

`app_web` is packaged with PyInstaller. Three steps, in order
— the spec bundles `frontend/dist` as it finds it, so a stale UI build ships
without a word:

```bash
npm run build --prefix frontend
uv run pyinstaller packaging/windows/cie-helper.spec --noconfirm
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\cie-helper.iss
```

Output: `dist/cie-helper/` (~84 MB) and `dist/cie-helper-<version>-setup.exe`
(~38 MB).

- **No path handling in the app needs to know it is frozen.** All three runtime
  lookups (`core/config_store.py`'s `data/`, `modules/updater.py`'s
  `pyproject.toml`, `app_web/main.py`'s `frontend/dist`) are
  `Path(__file__).parents[1] / <name>` from a module one level down, which
  under a onedir build resolves to `_internal/` — where the spec's `datas` put
  them.
- **Dependencies are not listed by hand.** pywebview ships its own hook
  (`webview/__pyinstaller/`) that collects the WebView2 interop DLLs, and
  pyinstaller-hooks-contrib covers pythonnet, pypdfium2 and pillow. A
  `collect_all` loop over those was tried and removed: the hooks already do it.
- **pandas and numpy are excluded on purpose**, worth 44 MB. The openai SDK's
  `_extras/pandas_proxy.py` is a lazy proxy nothing reaches through, but
  PyInstaller follows the import statically and packs both libraries.
- **The installer wipes two payload shapes.** `[InstallDelete]` lists
  `_internal` alongside the 1.x layout's loose `app\`, `site-packages\`, `Lib\`
  and `DLLs\`: an upgrade from 1.x lands in the same `{app}`, and `ignoreversion`
  overwrites files but never deletes ones the new build stopped shipping.

## 平台范围：桌面（Windows + macOS）

**目标平台是桌面：Windows 和 macOS。** 不为 iOS/iPadOS 做任何权衡 —— 上架
需要付费开发者账号，而这个 app 的用户量和收入撑不起来。移动端如果哪天真要
做，那是整个 app 换一套技术方案的事，不是现在往代码里留钩子能省下的。

具体意味着：布局按桌面窗口尺寸和鼠标交互设计（断点、间距、hover 态），
触屏手势和小屏折叠都不用考虑；依赖要有 Windows 和 macOS 的 wheel，但不必有
iOS 的。

**目前只有 Windows 打了包。** macOS 要出货得自己写一份 PyInstaller spec 和
dmg 流程，而且只能在 Mac 上跑 —— 交叉编译不存在。

## Stack

- **Python 3.13+** with `uv` as package manager
- **pywebview + React/TypeScript** for the UI — a native window hosting a built
  Vite bundle, with `window.pywebview.api` as the only bridge (`app_web/`,
  `frontend/`)
- **Pydantic v2** for all validation, settings, and domain models (strict mode enabled on most models)
- **pdfminer.six** for all PDF text/geometry extraction — segmentation *and* grade thresholds. **pdfplumber is dev-only now**, kept solely for the segmenter fidelity check that diffs the two engines; nothing shipped imports it, and the old `gt` extra is gone
- **requests** for downloading PDFs
- **ruff** (E/F/I/UP/B/SIM) + **mypy strict** for linting/typing

`core/gt_parser.py` is UI-agnostic and drives the 分数线 view. The syllabus
config has no in-app editor — `data/syllabus_config.json` is edited by hand.

## Architecture

### Entry point
- `app_web/main.py` — the pywebview host: opens the window, loads
  `frontend/dist/index.html` off disk, and hands the page an `Api` instance as
  `js_api`. `CIE_DEV=1` points it at the Vite dev server instead; `CIE_DEBUG=1`
  restores devtools.
- `app_web/api.py` — every `window.pywebview.api.*` method. Thin adapters only:
  take JSON, build the Pydantic model, call `core`/`modules`, return
  `model_dump(mode="json")`. A business rule appearing here is in the wrong layer.
  Failures come back one way — `_invalid` folds `ValidationError` into the same
  `{success, error}` shape the operations return, so the frontend never has to
  handle a rejected promise for a mistyped paper id.
- `app_web/jobs.py` — long-running work (parse, grade, MCQ detect) runs on a
  thread and pushes progress events to the page; one in-progress flag at a time.
- `frontend/src/App.tsx` — the four-tab shell (下载 / 管理 / 批改 / 设置) plus the
  overlay root that full-cover panels portal into.
- `frontend/src/tabs/<tab>/` — one directory per tab. `manage/` splits into
  `Overview` (donut + per-syllabus cards), `Organize` (icon / detail layouts)
  and `Mistakes`; `mark/` into `SetupStep` / `GradeStep` / `McqStep` /
  `ResultsStep`.
  - **The donut counts one unit per paper, not per mark.** A Pending record has
    no `score_total` (`completed_requires_scores` only demands them for
    Completed), so the grey slice has no marks to contribute. Each paper is one
    unit: a completed one splits into earned/lost by its score rate, a pending
    one is one whole grey unit. `frontend/src/lib/papers.test.ts` pins the
    slices summing to the paper count.
- `frontend/src/ui/` — the shared primitives. `Overlay` is the full-cover panel
  (portal + clip-path grow from the clicked rect); `PushTrack` the sliding
  N-step track; `motion.ts` the two springs everything animates on.

### `core/` — infrastructure layer
- **`settings.py`** — `AppSettings` (paths: `~/.cie_helper/`) and `MailConfig` (SMTP from .env). Singleton `app_settings` imported by all modules.
- **`storage.py`** — `CSVStore` loads/saves `PaperRecord` list from/to `~/.cie_helper/data.csv` via the stdlib `csv` module. Provides `load_all`, `save_all`, `append`, `update`, `delete`. `MistakeStore` is its append-only sibling for `mistakes.csv`. Both open with `newline=""` — without it the csv module's `
` gets translated again on Windows and every row is followed by a blank line.
- **`models.py`** — `PaperRecord` Pydantic model with computed `percentage` field and cross-field validators (scores required when Completed, raw ≤ total).
- **`config_store.py`** — `ConfigStore` reads `data/syllabus_config.json` (syllabus names + paper type labels used by analytics); `grading_type_for_paper` resolves a paper_id to its grading path, and `qp_skip_pages` reads `data/paper_page_config.json`. Read-only: both files are edited by hand.
- **`gt_parser.py`** — `GTParser` parses CIE grade threshold PDFs into `GTDocument` / per-option `GradeThreshold`. Three things to know, all covered by `tests/test_gt_parser.py`:
  - **Tables come from ruling lines**, not pdfplumber's `extract_tables()` — CIE draws every border as a thin `LTRect`. Verticals from *different tables on one page* must not be pooled (that sliced `250` into `25`+`0`), and multi-line cells must be read line-by-line or their glyphs interleave.
  - **CID decoding is derived, not transcribed.** These PDFs embed Arial as an Identity-H subset with no ToUnicode *and* the font's own `cmap` stripped, so pdfminer emits `(cid:N)` where N is the raw glyph id. Those ids follow the standard Macintosh TrueType glyph order, whose entries 3–97 are printable ASCII — `_cid_to_char` computes that. The hand-transcribed table it replaced came from one document and silently mistranslated every other syllabus (9701_w25 reported a D boundary of `10` instead of `103`). **Never re-introduce a per-file CID table.**
  - **`GradeThreshold` rejects inverted rows** (a higher grade needing fewer marks) and thresholds above the paper maximum. That is the net under the decoding: a dropped digit produces a plausible-looking boundary, and an inversion is its fingerprint. `_try_parse_options_table` skips rows that fail to construct, so a bad row is lost rather than shown.

### `modules/` — business logic layer
- **`downloader.py`** — `PaperDownloader` streams PDFs from CIEFrank or PapaCambridge, saves to `~/.cie_helper/pdfs/`, appends `PaperRecord` to store. Uses `_DownloadError` (never leaks outside module).
- **`manager.py`** — `PaperManager` handles score submission (marks Completed, timestamps), record deletion (optionally removes local PDFs), and opening PDFs in system viewer (cross-platform).
- **`mailer.py`** — `GoodNotesMailer` sends QP PDF to GoodNotes import email via SMTP SSL, updates `sent_to_gn` flag on success. Uses `_MailError` (never leaks outside module).
- **`updater.py`** — in-app update check / download / silent install against GitHub releases.
- **`marking/`** — the Mark tab's pipeline, split out because these served one flow: `ms_parser` (mark scheme → `PaperConfig`), `mcq_parser`, `page_segmenter` (question regions), `renderer` (page → image clips), `grader` (LLM grading), `workflow` (orchestration). Nothing outside `app_web/api.py` imports them.
  - **`page_segmenter` is two-phase**: `scan_document(pdf)` does every PDF-only step and `match_scanned(doc, question_ids)` the rest, so the Mark tab can scan the answer paper *while* the mark scheme is still parsing. `segment_questions_report()` is still the one-shot composition of the two.
  - **`workflow.py` must never import `app_web`.** That constraint is what makes the grading pipeline testable (`tests/test_marking_workflow.py`); keep user-facing strings on the UI side of the boundary.

### Data patterns
- **Result objects** — all operations return typed result objects (`DownloadResult`, `MailResult`, `UpdateResult`, `DeleteResult`, `OpenResult`) with `success: bool`, `error: str | None`, and operation-specific fields. Exceptions are caught and wrapped — never propagate to the UI layer.
- **Validation at boundaries** — `DownloadRequest`, `MailRequest`, `ScoreUpdate`, `DeleteRequest` are Pydantic models that validate user input at the entry point.
- **CSV as database** — file lives at `~/.cie_helper/data.csv`; no SQL database.
- **`.env`** — SMTP credentials stored at repo root, loaded by `MailConfig`/pydantic-settings.
- **No package re-exports** — `modules/__init__.py` and `modules/marking/__init__.py` are deliberately empty of imports, so `import modules.marking.page_segmenter` doesn't drag in siblings' heavy deps. `tests/test_modules_import.py` guards this in a subprocess. `core/__init__.py` is empty of imports for the same reason — `from core.models import PaperType` must not pull in `storage` and `settings` to reach an enum.

### Syllabus config
- `data/syllabus_config.json` — JSON array of `{syllabus_id, name, paper_types[]}` entries. Read by the 管理 and 下载 tabs for syllabus/paper-type labels, and by `manage/paper_icon.py`, which picks a subject glyph by **keyword in the name** rather than by code — one entry covers a subject at both IGCSE and A Level, and a new code needs no table edit. **No in-app editor** since the Streamlit admin page was removed — edit the JSON by hand.

## Key conventions

- Uses `from __future__ import annotations` everywhere
- `typing.Literal` for string enum patterns (DownloadSource, PaperRecord.status)
- Cross-field validation via `@model_validator(mode="after")`
- Private exception classes (`_DownloadError`, `_MailError`) to encapsulate module internals
- Layering is one-directional: `core ← modules ← app_web ← frontend`. Nothing in `core/` or `modules/` may import `app_web`.
