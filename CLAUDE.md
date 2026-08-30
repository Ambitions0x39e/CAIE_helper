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
# Run the app
uv run flet run app_flet

# Install dependencies
uv sync

# Add a dependency
uv add <package>

# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check — name the three packages. `tests/` and `main.py` are outside
# strict mode (see [[tool.mypy.overrides]]), so a bare `.` reports dozens of
# errors that are not the app's.
uv run mypy app_flet core modules

# Run tests
uv run pytest
```

## Building the packaged app (Flet)

The distributable app is built with `flet build <platform>` (`windows`, `macos`, `ipa`, `ios-simulator`, …). Two hard-won gotchas — see memory `reference_flet_build_windows.md` and `reference_flet_build_size.md`:

```bash
# The bundled CPython comes from `requires-python`, NOT from a CLI flag — see
# the note below. No --python-version needed; passing one only overrides it.
# Windows (Chinese/GBK console): force UTF-8 or rich crashes on emoji output.
# CL=-utf-8 guarded MSVC against non-GBK chars in plugin sources (C4819→C2220);
# flet 0.86.1 fixed that (#6686) so it is probably redundant now — kept until
# someone verifies a build without it. Dash spelling, NOT /utf-8, which Git Bash
# mangles into a Program Files path.
# Build from a SHORT real path (deep worktree paths overflow MSBuild).
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 CL=-utf-8 uv run flet build windows
```

- **`requires-python` picks the bundled CPython — keep its upper bound.** An
  earlier version of this file claimed `--python-version` was the only control.
  It isn't: `flet_cli/utils/python_versions.py::resolve_python_version` resolves
  `--python-version` → `[project].requires-python` → manifest default, and for
  the specifier it takes the **highest supported version that satisfies it**
  (supported today: 3.12, 3.13, 3.14). So bare `>=3.13` bundled **3.14** while
  the dev venv stayed on 3.13 — the suite ran on one Python and users got
  another, silently. The project is pinned to `>=3.13,<3.14`; verified mapping:

  | `requires-python` | bundles |
  |---|---|
  | `>=3.13` | 3.14 |
  | `>=3.13,<3.14` | 3.13 |
  | `>=3.14` | 3.14 |

  Never leave the bound open: the day flet supports 3.15, an open `>=` jumps to
  it on the next build with no diff to show for it. Moving to 3.14 is a
  deliberate change — bump this specifier, `[tool.ruff] target-version` and
  `[tool.mypy] python_version` together, then re-run the suite on 3.14. Runtime
  deps all have cp314 dual-arch macOS wheels already; the one snag is dev-only
  `watchdog` (6.0.0 tops out at cp313 on macOS, so it may need an sdist build).
- **Switching Python versions self-cleans.** 0.86 records the version in
  `build/.python-version` and forces a rebuild when it changes ("bad magic
  number" from mixed `.pyc` is what this prevents), so no manual `flet clean`
  for a version switch — unlike a *toolchain* bump, below.
- **After any toolchain bump, `uv run flet clean` first.** 0.86 ships Flutter 3.44.8; a `build/` left over from an older Flutter holds `hook.dill` files compiled by the previous Dart SDK, and the new one dies on them with `Can't load Kernel binary: Invalid kernel binary format version (expected 130, found 127)`. The failure names `package:objective_c`, which makes it look like a plugin problem — it isn't, it's a stale cache.
- **What ships**: `flet build` installs `[project.dependencies]` FRESH into the bundle (`build/windows/site-packages`). Separately it copies the **entire working directory** and **ignores `.gitignore`** — only top-level names in `[tool.flet.app].exclude` are left out.
- **No more `app.zip`.** serious_python 4.x (via flet 0.86) ships the app **unpacked** at `build/windows/app/`, compiled to `.pyc`, alongside `site-packages` — there is no first-launch extraction and no `%APPDATA%\…\flet\app\` copy. `pyproject.toml` still ships next to the sources, so `current_app_version()` keeps working.
- **Keep the exclude list complete.** Anything heavy not listed there (`.venv`, `.claude`, `.mypy_cache`, `.git`, caches, stray root PDFs) ships inside the bundle and bloats it — this is what once took it to ~1.2 GB. With the full exclude list `build/windows` is ~243 MB. When adding a new top-level dir/cache, add it to `exclude`.
- **`uv sync --no-dev` does NOT shrink the app** — the `.venv` folder is copied wholesale regardless of what's installed; only `exclude` controls size.
- **Keep `flet`, `flet-cli`, `flet-desktop` pinned in the same minor, in lockstep** (see memory `reference_flet_version_pin.md`), and keep the extension pubspec's `flet:` range covering that minor. The bundle's Python flet is pip-installed fresh from `[project.dependencies]` (uv.lock is ignored), while the Flutter client comes from flet-cli's template — if they diverge the packaged app opens to a permanent white screen (session never registers, `main()` never runs). 0.86 makes this stricter: its stream transports use a length-prefixed framing incompatible with pre-0.86 peers. Debug a white-screening package by running the exe with `--debug` (keeps Dart-side logs); the app sources are now editable in place at `build/windows/app/` (but they are `.pyc`).

## Stack

- **Python 3.13+** with `uv` as package manager
- **Flet** for the UI (desktop/iOS app; `flet run app_flet`)
- **Pydantic v2** for all validation, settings, and domain models (strict mode enabled on most models)
- **pdfminer.six** for all PDF text/geometry extraction — segmentation *and* grade thresholds (both iOS-safe). **pdfplumber is dev-only now**, kept solely for the segmenter fidelity check that diffs the two engines; nothing shipped imports it, and the old `gt` extra is gone
- **requests** for downloading PDFs
- **ruff** (E/F/I/UP/B/SIM) + **mypy strict** for linting/typing

The Streamlit app (`app.py`, `pages/`, `modules/visualizer.py`) was removed once
it had been fully superseded by the Flet app — it no longer even imported. Two of
its features were never ported: the grade-threshold checker and the syllabus
config editor. `core/gt_parser.py` (UI-agnostic) is kept for a future port; the
deleted UI is recoverable from git history.

## Architecture

### Entry point
- `main.py` / `app_flet/main.py` — Flet app: header + 5 tabs (下载 / 管理 / 统计 / 批改 / 设置)
- `app_flet/state.py` — `AppState`, the mutable state shared across tabs
- `app_flet/tabs/*.py` — one `build_*_tab()` per tab; `app_flet/components/` holds shared widgets and dialogs
- `app_flet/tabs/mark/` — the one tab too big for a single file. `tab.py` owns the rebuild loop, `setup_step` / `answer_pages` / `grade_step` / `results` / `mcq` are the sections, and they share mutable state through `MarkTabContext` (`context.py`) instead of the closure refs the old single-file version used. UI-agnostic decisions live one layer down, in `modules/marking/workflow.py`.

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
- **`marking/`** — the Mark tab's pipeline, split out because these served one flow: `ms_parser` (mark scheme → `PaperConfig`), `mcq_parser`, `page_segmenter` (question regions), `renderer` (page → image clips), `grader` (LLM grading), `workflow` (orchestration). Nothing outside `app_flet/tabs/mark/` imports them.
  - **`page_segmenter` is two-phase**: `scan_document(pdf)` does every PDF-only step and `match_scanned(doc, question_ids)` the rest, so the Mark tab can scan the answer paper *while* the mark scheme is still parsing. `segment_questions_report()` is still the one-shot composition of the two.
  - **`workflow.py` must never import `flet`/`app_flet`.** That constraint is what makes the grading pipeline testable (`tests/test_marking_workflow.py`); keep user-facing strings on the UI side of the boundary.

### Data patterns
- **Result objects** — all operations return typed result objects (`DownloadResult`, `MailResult`, `UpdateResult`, `DeleteResult`, `OpenResult`) with `success: bool`, `error: str | None`, and operation-specific fields. Exceptions are caught and wrapped — never propagate to the UI layer.
- **Validation at boundaries** — `DownloadRequest`, `MailRequest`, `ScoreUpdate`, `DeleteRequest` are Pydantic models that validate user input at the entry point.
- **CSV as database** — file lives at `~/.cie_helper/data.csv`; no SQL database.
- **`.env`** — SMTP credentials stored at repo root, loaded by `MailConfig`/pydantic-settings.
- **No package re-exports** — `modules/__init__.py` and `modules/marking/__init__.py` are deliberately empty of imports, so `import modules.marking.page_segmenter` doesn't drag in siblings' platform-specific deps (several have no iOS wheel, which would break `flet build ipa`). `tests/test_modules_import.py` guards this in a subprocess. `core/__init__.py` is empty of imports for the same reason — `from core.models import PaperType` must not pull in `storage` and `settings` to reach an enum.

### Syllabus config
- `data/syllabus_config.json` — JSON array of `{syllabus_id, name, paper_types[]}` entries. Read by the Analytics and Download tabs for syllabus/paper-type labels. **No in-app editor** since the Streamlit admin page was removed — edit the JSON by hand.

## Key conventions

- Uses `from __future__ import annotations` everywhere
- `typing.Literal` for string enum patterns (DownloadSource, PaperRecord.status)
- Cross-field validation via `@model_validator(mode="after")`
- Private exception classes (`_DownloadError`, `_MailError`) to encapsulate module internals
- Layering is one-directional: `core ← modules ← app_flet`. Nothing in `core/` or `modules/` may import `app_flet`.
