"""Infrastructure layer.

Intentionally NO eager re-exports, for the same reason as ``modules``:
``from core.models import PaperType`` must not drag in ``storage`` and
``settings`` just to reach an enum. Import what you need directly.
"""
