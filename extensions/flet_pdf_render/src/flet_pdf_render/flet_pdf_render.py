from __future__ import annotations

from dataclasses import dataclass

import flet as ft


@dataclass
class RenderClip:
    """A full-width vertical slice of one PDF page, in PDF points (top-origin).

    Mirrors modules.marking.page_segmenter.PageClip; y coordinates are measured from
    the top of the page (pdfplumber convention). A clip covering the whole
    page (y_top=0, y_bottom=page_height) renders the full page.
    """

    page: int  # 0-indexed page number
    y_top: float
    y_bottom: float


@ft.control("PdfRenderer")
class PdfRenderer(ft.Service):
    """Headless native PDF renderer backed by pdfrx (PDFium/PDFKit).

    Replaces the pdfplumber-based rendering so the Mark tab works on iOS.
    Add it to ``page.services`` once, then call :meth:`render_regions`.
    """

    async def render_regions(
        self,
        pdf: bytes,
        clips: list[RenderClip],
        dpi: int = 200,
    ) -> list[bytes]:
        """Render each clip to a PNG. Returns one PNG (bytes) per clip."""
        result = await self._invoke_method(
            "render_regions",
            {
                "pdf": pdf,
                "clips": [
                    {"page": c.page, "y_top": c.y_top, "y_bottom": c.y_bottom}
                    for c in clips
                ],
                "dpi": dpi,
            },
            timeout=120,
        )
        return [bytes(png) for png in result]
