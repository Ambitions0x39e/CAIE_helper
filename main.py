import flet as ft


def _main(page: ft.Page) -> None:
    from app_flet.main import main

    main(page)


ft.app(_main)
