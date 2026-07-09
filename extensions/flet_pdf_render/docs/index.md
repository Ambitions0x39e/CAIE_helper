# Introduction

FletPdfRender for Flet.

## Examples

```
import flet as ft

from flet_pdf_render import FletPdfRender


def main(page: ft.Page):
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    page.add(

                ft.Container(height=150, width=300, alignment = ft.Alignment.CENTER, bgcolor=ft.Colors.PURPLE_200, content=FletPdfRender(
                    tooltip="My new FletPdfRender Control tooltip",
                    value = "My new FletPdfRender Flet Control",
                ),),

    )


ft.run(main)
```

## Classes

[FletPdfRender](FletPdfRender.md)
