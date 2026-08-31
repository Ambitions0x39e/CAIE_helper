"""Business-logic layer.

Two groups: paper acquisition/management (``downloader``, ``mailer``,
``manager``, ``updater``) at this level, and the marking pipeline in the
``marking`` subpackage — those five modules serve the Mark tab and nothing else.

Intentionally NO eager re-exports. Importing a single submodule (e.g.
``modules.marking.page_segmenter``) must not drag in a sibling's heavy
dependencies — a parser has no business pulling in the SMTP client or the
grading API just to be reachable.

Import what you need directly, e.g. ``from modules.marking.page_segmenter
import segment_questions_report``. Nothing in the codebase relies on package-level
re-exports (``from modules import X``), so this keeps each import minimal.
"""
