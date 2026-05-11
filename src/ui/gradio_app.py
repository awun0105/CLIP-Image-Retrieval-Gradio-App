"""Gradio UI — mounted into the FastAPI app under ``/ui``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import gradio as gr

if TYPE_CHECKING:
    from core.image_service import ImageService
    from core.search import SearchService

logger = logging.getLogger(__name__)


def build_ui(
    search_service: "SearchService",
    image_service: "ImageService",
) -> gr.Blocks:
    """Construct the Gradio Blocks UI bound to the provided services."""

    def _resolve_results(results) -> tuple[list[tuple[str, str]], list[dict], str]:
        urls: list[tuple[str, str]] = []
        rows: list[dict] = []
        for r in results:
            try:
                url = image_service.get_image_url(r.image_path)
            except Exception as exc:
                logger.warning("Failed to presign %s: %s", r.image_path, exc)
                url = r.image_path
            caption = r.caption or r.filename or ""
            urls.append((url, caption))
            rows.append(
                {
                    "image_path": r.image_path,
                    "score": r.score,
                    "caption": r.caption,
                    "filename": r.filename,
                }
            )
        return urls, rows, f"Found {len(urls)} results"

    def search_by_text(text: str, top_k: int):
        if not text or not text.strip():
            return [], [], "Error: please enter a text query"
        try:
            results = search_service.search_by_text(text, int(top_k))
        except Exception as exc:
            logger.exception("search_by_text failed")
            return [], [], f"Error: {exc}"
        return _resolve_results(results)

    def search_by_image(image, top_k: int):
        if image is None:
            return [], [], "Error: please upload an image"
        try:
            results = search_service.search_by_image(image, int(top_k))
        except Exception as exc:
            logger.exception("search_by_image failed")
            return [], [], f"Error: {exc}"
        return _resolve_results(results)

    def combined_search(search_type: str, text, image, top_k):
        if search_type == "Text":
            return search_by_text(text, top_k)
        return search_by_image(image, top_k)

    def on_select(evt: gr.SelectData, rows):
        if not rows or evt.index is None or evt.index >= len(rows):
            return "Select an image to view details", ""
        row = rows[evt.index]
        return f"{row.get('score', 'N/A')}", row.get("caption") or "No caption available"

    with gr.Blocks(css="body { overflow-y: auto !important; }") as webui:
        gr.Markdown("## CLIP Image Search App (v2 — Qdrant + MinIO)")

        results_state = gr.State([])

        with gr.Column():
            with gr.Row(equal_height=True):
                search_type = gr.Radio(choices=["Text", "Image"], label="Search by", value="Text")
                top_k_slider = gr.Slider(label="Top K", minimum=1, maximum=50, step=1, value=5)
            with gr.Column(visible=True) as text_input:
                text = gr.Textbox(label="Text", placeholder="Enter text to search")
            with gr.Column(visible=False) as image_input:
                image = gr.Image(label="Image", type="pil")

            def toggle_inputs(search_type_value):
                return (
                    gr.update(visible=search_type_value == "Text"),
                    gr.update(visible=search_type_value == "Image"),
                )

            search_type.change(
                toggle_inputs, inputs=[search_type], outputs=[text_input, image_input]
            )

            search_btn = gr.Button("Search", variant="primary")
            status = gr.Textbox(label="Status", value="Ready")

            gallery = gr.Gallery(
                label="Results", show_label=True, columns=5, rows=2, height="auto", preview=False
            )
            image_info_score = gr.Textbox(
                label="Similarity Score", value="Select an image to view details"
            )
            image_info_caption = gr.Textbox(
                label="Caption", value="Select an image to view details"
            )

        search_btn.click(
            fn=combined_search,
            inputs=[search_type, text, image, top_k_slider],
            outputs=[gallery, results_state, status],
        )

        gallery.select(
            fn=on_select,
            inputs=[results_state],
            outputs=[image_info_score, image_info_caption],
        )

    return webui
