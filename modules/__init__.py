"""Business-logic layer.

Intentionally NO eager re-exports. Importing a single submodule (e.g.
``modules.page_segmenter``) must not drag in heavy, platform-specific
dependencies from sibling submodules — the Streamlit-based ``visualizer``
and the pdfplumber-based ``pdf_renderer`` have no iOS wheels and would make
every ``modules.*`` import fail on iOS (and require ``streamlit`` everywhere).

Import what you need directly, e.g. ``from modules.page_segmenter import
segment_questions``. Nothing in the codebase relies on package-level
re-exports (``from modules import X``), so this keeps each import minimal.
"""
