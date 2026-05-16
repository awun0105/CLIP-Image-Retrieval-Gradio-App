"""Service entry point — mount Gradio onto FastAPI and run uvicorn."""

from __future__ import annotations

import gradio as gr
import uvicorn

from api.app import create_app
from api.dependencies import (
    get_image_service,
    get_search_service,
    get_settings,
)
from core.logging import configure_logging
from ui.gradio_app import build_ui


def main() -> None:
    settings = get_settings()
    configure_logging(settings)

    app = create_app()
    ui = build_ui(get_search_service(), get_image_service())
    gr.mount_gradio_app(app, ui, path="/ui")

    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
