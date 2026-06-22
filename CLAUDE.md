# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app
uv run streamlit run app.py

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

# Run tests (none exist yet — pytest configured in pyproject.toml)
# uv run pytest
```

## Stack

- **Python 3.13+** with `uv` as package manager
- **Streamlit** for the web UI (single-page app with 3 tabs + 2 multipage admin pages)
- **Pydantic v2** for all validation, settings, and domain models (strict mode enabled on most models)
- **pandas** for CSV store and analytics DataFrames
- **pdfplumber** for parsing grade threshold PDFs
- **requests** for downloading PDFs
- **ruff** (E/F/I/UP/B/SIM) + **mypy strict** for linting/typing

## Architecture

### Entry point
- `app.py` — main Streamlit app with 3 tabs: Download, Manage, Analytics
- `pages/admin.py` — syllabus/paper-type config admin page
- `pages/gt_checker.py` — grade threshold checker with bulk download + score entry

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
- **`visualizer.py`** — `PaperVisualizer` renders Streamlit analytics: overall metrics, per-syllabus breakdown, per-paper-type trend charts via `st.line_chart`.

### Data patterns
- **Result objects** — all operations return typed result objects (`DownloadResult`, `MailResult`, `UpdateResult`, `DeleteResult`, `OpenResult`) with `success: bool`, `error: str | None`, and operation-specific fields. Exceptions are caught and wrapped — never propagate to the UI layer.
- **Validation at boundaries** — `DownloadRequest`, `MailRequest`, `ScoreUpdate`, `DeleteRequest` are Pydantic models that validate user input at the entry point.
- **CSV as database** — file lives at `~/.cie_helper/data.csv`; no SQL database.
- **`.env`** — SMTP credentials stored at repo root, loaded by `MailConfig`/pydantic-settings.
- **`__init__.py`** re-exports — both `core/__init__.py` and `modules/__init__.py` re-export the public API of their submodules.

### Syllabus config
- `data/syllabus_config.json` — JSON array of `{syllabus_id, name, paper_types[]}` entries. Managed via pages/admin.py. Used by visualizer to label analytics groups.

## Key conventions

- Uses `from __future__ import annotations` everywhere
- `typing.Literal` for string enum patterns (DownloadSource, PaperRecord.status)
- Cross-field validation via `@model_validator(mode="after")`
- Private exception classes (`_DownloadError`, `_MailError`) to encapsulate module internals
- Streamlit error display via shared `fmt_validation_error()` helper formatting Pydantic errors
