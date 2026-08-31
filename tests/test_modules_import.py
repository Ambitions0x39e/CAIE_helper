"""Guard: importing individual `modules.*` submodules must stay lightweight.

`modules/__init__.py` and `modules/marking/__init__.py` hold no imports, so
`import modules.marking.page_segmenter` costs one parser and nothing else. An
eager re-export added to either file would quietly make every `modules.*`
import drag in every sibling's dependencies; these tests fail when it does.

Each test runs in a fresh subprocess so sys.modules isn't polluted by pytest.
"""
from __future__ import annotations

import subprocess
import sys


def _import_leaks(submodule: str, forbidden: list[str]) -> tuple[int, str]:
    checks = "; ".join(
        f"assert {m!r} not in sys.modules, {m!r} + ' leaked'" for m in forbidden
    )
    code = f"import sys; import {submodule}; {checks}; print('OK')"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stderr


def test_page_segmenter_import_is_light() -> None:
    rc, err = _import_leaks(
        "modules.marking.page_segmenter", ["streamlit", "pdfplumber", "requests"]
    )
    assert rc == 0, err


def test_grader_import_does_not_need_streamlit() -> None:
    # grader still imports pdfplumber for rendering — that leaves in Phase 2B
    # when the Dart renderer replaces render_question_regions. For now, just
    # guard that grader never drags in streamlit.
    rc, err = _import_leaks("modules.marking.grader", ["streamlit"])
    assert rc == 0, err
