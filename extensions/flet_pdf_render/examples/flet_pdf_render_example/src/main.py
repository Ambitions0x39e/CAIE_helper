"""Render round-trip harness for the PdfRenderer extension.

Points the native pdfrx-backed service at a real PDF, renders (1) a full page
and (2) a cropped vertical slice, shows both, and saves the PNGs to OUT_DIR for
inspection. Proves the Python<->Dart path round-trip and the point->pixel crop
mapping on desktop before iOS.
"""
import os

import flet as ft
from flet_pdf_render import PdfRenderer, RenderClip

PDF_PATH = r"D:/repos/CieHelperWin/test_papers/9702_s25_qp_21.pdf.pdf"
OUT_DIR = r"D:/repos/CieHelperWin/build/render_harness_out"


def main(page: ft.Page):
    page.title = "PdfRenderer round-trip test"
    page.scroll = ft.ScrollMode.AUTO

    renderer = PdfRenderer()
    page.services.append(renderer)

    status = ft.Text("Rendering…", size=14)
    images_col = ft.Column()
    page.add(status, images_col)

    async def do_render():
        try:
            # (1) full page 2 (0-indexed page 1); a4/letter height ~792pt
            # (2) a cropped top slice of page 2 (points, top-origin)
            clips = [
                RenderClip(page=1, y_top=0.0, y_bottom=792.0),
                RenderClip(page=1, y_top=60.0, y_bottom=300.0),
            ]
            pngs = await renderer.render_regions(PDF_PATH, clips, dpi=150)

            os.makedirs(OUT_DIR, exist_ok=True)
            status.value = f"OK — {len(pngs)} images rendered"
            for i, png in enumerate(pngs):
                out_path = os.path.join(OUT_DIR, f"img_{i}.png")
                with open(out_path, "wb") as of:
                    of.write(png)
                images_col.controls.append(
                    ft.Column([
                        ft.Text(f"image {i}: {len(png)} bytes -> {out_path}", size=12),
                        ft.Image(src=png, width=400, border_radius=4),
                    ])
                )
            page.update()
        except Exception as exc:
            status.value = f"FAIL: {type(exc).__name__}: {exc}"
            status.color = ft.Colors.RED
            page.update()

    page.run_task(do_render)


ft.run(main)
