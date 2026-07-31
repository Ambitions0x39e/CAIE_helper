# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

# Type check
uv run mypy .

# Run tests
uv run pytest
```

## Building the packaged app (Flet)

The distributable app is built with `flet build <platform>` (`windows`, `macos`, `ipa`, `ios-simulator`, …). Two hard-won gotchas — see memory `reference_flet_build_windows.md` and `reference_flet_build_size.md`:

```bash
# Windows (Chinese/GBK console): force UTF-8 or rich crashes on emoji output;
# CL=-utf-8 or MSVC fails plugins containing non-GBK chars (C4819→C2220) —
# dash spelling, NOT /utf-8, which Git Bash mangles into a Program Files path;
# build from a SHORT real path (deep worktree paths overflow MSBuild).
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 CL=-utf-8 uv run flet build windows
```

- **What ships**: `flet build` installs `[project.dependencies]` FRESH into the bundle (`build/site-packages`) — that path is clean, streamlit is never there. Separately it copies the **entire working directory** into `app.zip` and **ignores `.gitignore`**. Only top-level names in `[tool.flet.app].exclude` are left out.
- **Keep the exclude list complete.** Anything heavy not listed there (`.venv`, `.claude`, `.mypy_cache`, `.git`, caches, stray root PDFs) ships inside `app.zip` and bloats the app — this is what took it to ~1.2 GB. With the full exclude list, `build/windows` is ~190 MB. When adding a new top-level dir/cache, add it to `exclude`.
- **`uv sync --no-dev` does NOT shrink the app** — the `.venv` folder is copied wholesale regardless of what's installed; only `exclude` controls size.
- **Keep `flet`, `flet-cli`, `flet-desktop` pinned in the same minor, in lockstep** (see memory `reference_flet_version_pin.md`). The bundle's Python flet is pip-installed fresh from `[project.dependencies]` (uv.lock is ignored), while the Flutter client comes from flet-cli's template — if they diverge (e.g. bundle grabs a newer flet), the packaged app opens to a permanent white screen (session never registers, `main()` never runs). Debug a white-screening package by running the exe with `--debug` (keeps Dart-side logs) and editing the extracted app at `%APPDATA%\Roaming\<company>\<app>\flet\app\` (no rebuild needed).

## Stack

- **Python 3.13+** with `uv` as package manager
- **Flet** for the UI (desktop/iOS app; `flet run app_flet`)
- **Pydantic v2** for all validation, settings, and domain models (strict mode enabled on most models)
- **pandas** for CSV store and analytics DataFrames
- **pdfminer.six** for text extraction / segmentation (iOS-safe); **pdfplumber** only for grade-threshold PDFs, behind the `gt` extra
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

### `core/` — infrastructure layer
- **`settings.py`** — `AppSettings` (paths: `~/.cie_helper/`) and `MailConfig` (SMTP from .env). Singleton `app_settings` imported by all modules.
- **`storage.py`** — `CSVStore` loads/saves `PaperRecord` list from/to `~/.cie_helper/data.csv` via pandas. Provides `load_all`, `save_all`, `append`, `update`, `delete`, `to_dataframe`.
- **`models.py`** — `PaperRecord` Pydantic model with computed `percentage` field and cross-field validators (scores required when Completed, raw ≤ total).
- **`config_store.py`** — `ConfigStore` manages `data/syllabus_config.json` (syllabus names + paper type labels used by analytics).
- **`gt_parser.py`** — `GTParser` parses CIE grade threshold PDFs, handling their non-standard CID font encoding. Produces `GTDocument` with per-option `GradeThreshold`.

### `modules/` — business logic layer
- **`downloader.py`** — `PaperDownloader` streams PDFs from CIEFrank or PapaCambridge, saves to `~/.cie_helper/pdfs/`, appends `PaperRecord` to store. Uses `_DownloadError` (never leaks outside module).
- **`manager.py`** — `PaperManager` handles score submission (marks Completed, timestamps), record deletion (optionally removes local PDFs), and opening PDFs in system viewer (cross-platform).
- **`mailer.py`** — `GoodNotesMailer` sends QP PDF to GoodNotes import email via SMTP SSL, updates `sent_to_gn` flag on success. Uses `_MailError` (never leaks outside module).
- **`updater.py`** — in-app update check / download / silent install against GitHub releases.
- **`marking/`** — the Mark tab's pipeline, split out because these five served one flow: `ms_parser` (mark scheme → `PaperConfig`), `mcq_parser`, `page_segmenter` (question regions), `renderer` (page → image clips), `grader` (LLM grading). Nothing outside `app_flet/tabs/mark.py` imports them.

### Data patterns
- **Result objects** — all operations return typed result objects (`DownloadResult`, `MailResult`, `UpdateResult`, `DeleteResult`, `OpenResult`) with `success: bool`, `error: str | None`, and operation-specific fields. Exceptions are caught and wrapped — never propagate to the UI layer.
- **Validation at boundaries** — `DownloadRequest`, `MailRequest`, `ScoreUpdate`, `DeleteRequest` are Pydantic models that validate user input at the entry point.
- **CSV as database** — file lives at `~/.cie_helper/data.csv`; no SQL database.
- **`.env`** — SMTP credentials stored at repo root, loaded by `MailConfig`/pydantic-settings.
- **No `modules/` re-exports** — `modules/__init__.py` and `modules/marking/__init__.py` are deliberately empty of imports, so `import modules.marking.page_segmenter` doesn't drag in siblings' platform-specific deps (several have no iOS wheel, which would break `flet build ipa`). `tests/test_modules_import.py` guards this in a subprocess. `core/__init__.py` does re-export.

### Syllabus config
- `data/syllabus_config.json` — JSON array of `{syllabus_id, name, paper_types[]}` entries. Read by the Analytics and Download tabs for syllabus/paper-type labels. **No in-app editor** since the Streamlit admin page was removed — edit the JSON by hand.

## Key conventions

- Uses `from __future__ import annotations` everywhere
- `typing.Literal` for string enum patterns (DownloadSource, PaperRecord.status)
- Cross-field validation via `@model_validator(mode="after")`
- Private exception classes (`_DownloadError`, `_MailError`) to encapsulate module internals
- Layering is one-directional: `core ← modules ← app_flet`. Nothing in `core/` or `modules/` may import `app_flet`.
