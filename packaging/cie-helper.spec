# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec, for both desktop targets.

Build from the repo root, so `dist/` and `build/` land where the packaging
scripts expect them:

    uv run pyinstaller packaging/cie-helper.spec --noconfirm

On Windows that leaves `dist/cie-helper/` — the exe plus `_internal/`, which
Inno then wraps into a single setup.exe (see windows/cie-helper.iss).
On macOS the same COLLECT is wrapped by BUNDLE into `dist/CIE Helper.app`,
which macos/build-dmg.sh stages into a .dmg.

One spec rather than one per platform: the analysis, the data files and the
exclusions are identical, and the only genuinely per-platform parts are the
icon format and the .app wrapper at the very end.

Nothing here needs a matching change in the app's own path handling. Every
runtime lookup is `Path(__file__).parents[1] / <name>` from a module one level
down, and under a frozen build that resolves to `_internal/` — which is exactly
where the `datas` entries below put things. Inside a .app that path is
`Contents/Frameworks/`, and the same lookup still lands on it.
"""
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 — injected by PyInstaller

# The .app carries its version in Info.plist, where Finder and the updater
# read it. Same single source of truth as everywhere else: [project].version.
VERSION = re.search(
    r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text("utf-8"), re.M
).group(1)

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
    # Native arch. A universal2 build needs every wheel in the tree to be
    # universal, and pypdfium2 and pillow ship per-arch ones.
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows embeds the icon in the exe; macOS reads it out of the .app's
    # Info.plist instead, so it is passed to BUNDLE below and not here.
    icon=str(ROOT / "packaging" / "windows" / "app.ico") if sys.platform == "win32" else None,
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

if sys.platform == "darwin":
    # `.icns` only — PyInstaller does not convert, and a `.ico` here is a build
    # error. Absent, the bundle gets the generic application icon and the build
    # still succeeds, which is the right trade for a target that has no
    # released artwork yet.
    icns = ROOT / "packaging" / "macos" / "app.icns"
    app = BUNDLE(  # noqa: F821
        coll,
        name="CIE Helper.app",
        icon=str(icns) if icns.exists() else None,
        bundle_identifier="xyz.asanagi.cie-helper",
        version=VERSION,
        info_plist={
            # Without this the window renders at 72 dpi and every glyph in the
            # webview is soft on a Retina display.
            "NSHighResolutionCapable": True,
            # Nothing here is a document handler or a background agent; it is a
            # plain windowed app.
            "LSApplicationCategoryType": "public.app-category.education",
            "CFBundleShortVersionString": VERSION,
        },
    )
