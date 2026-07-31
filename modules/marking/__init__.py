"""Marking pipeline: MS parsing → question segmentation → rendering → grading.

Every module in here exists to serve the Mark tab; nothing else imports them.
They were split out of the flat ``modules/`` package because five of its ten
files belonged to this one flow.

Same rule as ``modules/__init__.py``: **no eager re-exports**. Importing
``modules.marking.page_segmenter`` must not drag in its siblings' heavy,
platform-specific dependencies — see ``tests/test_modules_import.py``, which
guards that line in a subprocess. Import what you need directly, e.g.
``from modules.marking.ms_parser import PaperConfig``.
"""
