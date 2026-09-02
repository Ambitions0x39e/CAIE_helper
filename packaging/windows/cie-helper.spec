# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Windows app.

Build from the repo root, so `dist/` and `build/` land where the installer
script expects them:

    uv run pyinstaller packaging/windows/cie-helper.spec --noconfirm

Output is `dist/cie-helper/` — the exe plus `_internal/`, which Inno then wraps
into a single setup.exe (see cie-helper.iss).

Nothing here needs a matching change in the app's own path handling. Every
runtime lookup is `Path(__file__).parents[1] / <name>` from a module one level
down, and under a frozen build that resolves to `_internal/` — which is exactly
where the `datas` entries below put things.
"""
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]  # noqa: F821 — injected by PyInstaller

datas = [
    # The UI. `npm run build --prefix frontend` has to have run first; the app
    # raises a plain SystemExit naming the missing path if it has not.
    (str(ROOT / "frontend" / "dist"), "frontend/dist"),
    # Syllabus names, paper-type labels and per-paper page skips. Read-only,
    # edited by hand, and the 管理 and 下载 tabs are empty without them.
    (str(ROOT / "data"), "data"),
    # `current_app_version()` reads its own version out of this, which is what
    # the About page shows and what the update check compares against.
    (str(ROOT / "pyproject.toml"), "."),
]
# Nothing else is listed by hand. pywebview's Windows backend is reached by
# name at runtime and loads .NET interop DLLs from inside its own package —
# none of it visible to a source walk — but pywebview ships the hook that
# collects it (`webview/__pyinstaller/`), and pyinstaller-hooks-contrib covers
# pythonnet, pypdfium2 and pillow. Verified in the built app: the WebView2
# DLLs, pdfium.dll and PIL's extension modules are all in `_internal`.
a = Analysis(  # noqa: F821
    [str(ROOT / "app_web" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # pdfplumber is dev-only (the segmenter fidelity check) and nothing
    # shipped imports it; the rest are dev tooling that a stray import would
    # otherwise drag in.
    #
    # pandas and numpy are here for a different reason, and it is worth 44 MB
    # of the bundle: the openai SDK ships `_extras/pandas_proxy.py`, a lazy
    # proxy that only imports pandas when something reaches through it.
    # Nothing does — but PyInstaller follows the import statically and packs
    # both libraries plus their DLLs. Dropping them is safe exactly because
    # the proxy defers; if any code path ever does touch it, this is the line
    # that turns that into an ImportError rather than a silent 44 MB.
    excludes=[
        "pdfplumber",
        "pandas",
        "numpy",
        "pytest",
        "mypy",
        "ruff",
        "tkinter",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="cie-helper",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A window app, not a terminal one. Set CIE_DEBUG=1 and run it from a shell
    # to get devtools; tracebacks still reach stderr when one is attached.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "packaging" / "windows" / "app.ico"),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="cie-helper",
)
