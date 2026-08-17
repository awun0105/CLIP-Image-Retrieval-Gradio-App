"""Standalone Gradio entrypoint for the Hugging Face Space."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Event, Lock

try:
    import spaces
except ImportError:

    class _LocalSpaces:
        """Keep the app runnable outside Hugging Face ZeroGPU."""

        @staticmethod
        def GPU(function=None, **_kwargs):
            if function is not None:
                return function

            def decorator(callback):
                return callback

            return decorator

    spaces = _LocalSpaces()  # type: ignore[assignment]

import gradio as gr
from clip import CLIPSearcher
from clusterer import ImageIndexer
from database_utils import download_and_prepare_dataset

from db import ScanCancelled, SearchMechanism

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

logger = logging.getLogger(__name__)
DEFAULT_PROGRESS = gr.Progress()
DEFAULT_FAISS_NPROBE = 8


def _use_faiss(search_mode: str) -> bool:
    normalized = str(search_mode).strip().lower()
    if normalized == "faiss":
        return True
    if normalized == "exact":
        return False
    raise ValueError(f"Unsupported search mode: {search_mode}")


class _ScanController:
    def __init__(self) -> None:
        self.cancel_event = Event()
        self._lock = Lock()
        self._running = False

    def begin(self) -> None:
        with self._lock:
            if self._running:
                raise RuntimeError("A reindex operation is already running")
            self.cancel_event.clear()
            self._running = True

    def finish(self) -> None:
        with self._lock:
            self._running = False

    def cancel(self) -> bool:
        with self._lock:
            if not self._running:
                return False
            self.cancel_event.set()
            return True


def build_app(
    search_mechanism: SearchMechanism,
    images_path: str,
    *,
    scan_batch_size: int = 16,
) -> gr.Blocks:
    """Build the UI while retaining the V1 public Gradio endpoint names."""
    scan_controller = _ScanController()

    def _resolve_results(results) -> tuple[list[tuple[str, str]], list[dict], str]:
        gallery_items: list[tuple[str, str]] = []
        rows: list[dict] = []
        for result in results:
            if not Path(result.image_path).is_file():
                logger.warning("Search result image does not exist: %s", result.image_path)
                continue
            gallery_items.append((result.image_path, result.caption or result.filename or ""))
            rows.append(result.to_dict())
        return gallery_items, rows, f"Found {len(gallery_items)} results"

    def search_by_text(text: str, top_k: int, search_mode: str, faiss_nprobe: int):
        if not text or not text.strip():
            return [], [], "Error: please enter a text query"
        try:
            use_cluster_search = _use_faiss(search_mode)
            results = search_mechanism.query_by_text(
                text,
                int(top_k),
                use_cluster_search,
                int(faiss_nprobe) if use_cluster_search else None,
            )
            return _resolve_results(results)
        except Exception as exc:
            logger.exception("Text search failed")
            return [], [], f"Error: {exc}"

    def search_by_image(image, top_k: int, search_mode: str, faiss_nprobe: int):
        if image is None:
            return [], [], "Error: please upload an image"
        try:
            use_cluster_search = _use_faiss(search_mode)
            results = search_mechanism.query_by_image(
                image,
                int(top_k),
                use_cluster_search,
                int(faiss_nprobe) if use_cluster_search else None,
            )
            return _resolve_results(results)
        except Exception as exc:
            logger.exception("Image search failed")
            return [], [], f"Error: {exc}"

    @spaces.GPU(duration=120)
    def combined_search(search_type, text, image, top_k, search_mode, faiss_nprobe):
        if search_type == "Text":
            return search_by_text(text, top_k, search_mode, faiss_nprobe)
        return search_by_image(image, top_k, search_mode, faiss_nprobe)

    @spaces.GPU(duration=120)
    def legacy_combined_search(search_type, text, image, top_k, use_cluster_search):
        search_mode = "faiss" if use_cluster_search else "exact"
        if search_type == "Text":
            return search_by_text(text, top_k, search_mode, DEFAULT_FAISS_NPROBE)
        return search_by_image(image, top_k, search_mode, DEFAULT_FAISS_NPROBE)

    def get_image_info(evt: gr.SelectData, rows):
        if not rows or evt.index is None:
            return "Select an image to view details", ""
        index = int(evt.index)
        if index < 0 or index >= len(rows):
            return "Select an image to view details", ""
        row = rows[index]
        score = row.get("score")
        score_text = f"{float(score):.6f}" if score is not None else "N/A"
        return score_text, row.get("caption") or "No caption available"

    @spaces.GPU(duration=300)
    def scan_dir(path: str, progress=DEFAULT_PROGRESS):
        try:
            scan_controller.begin()
        except RuntimeError as exc:
            gr.Warning(str(exc))
            return images_path

        try:
            count = search_mechanism.scan_directory(
                Path(path),
                batch_size=scan_batch_size,
                cancel_event=scan_controller.cancel_event,
                progress=lambda completed, total: progress(
                    completed / total,
                    desc=f"Indexed {completed}/{total} images",
                ),
            )
        except ScanCancelled:
            gr.Info("Scan cancelled. The previous index is still active.")
            return images_path
        except Exception as exc:
            logger.exception("Directory scan failed")
            gr.Warning(f"Scan failed: {exc}")
            return images_path
        finally:
            scan_controller.finish()

        gr.Info(f"Indexed {count} images successfully.")
        return images_path

    def cancel_scan():
        if scan_controller.cancel():
            return "Cancellation requested. Finishing the current batch..."
        return "No scan is currently running"

    def toggle_inputs(search_type):
        return (
            gr.update(visible=search_type == "Text"),
            gr.update(visible=search_type == "Image"),
        )

    def toggle_faiss_controls(search_mode):
        return gr.update(interactive=_use_faiss(search_mode))

    with gr.Blocks(css="body { overflow-y: auto !important; }") as webui:
        gr.Markdown("## CLIP Image Search App (v2 - FAISS + HF Dataset)")
        results_state = gr.State([])

        with gr.Column():
            with gr.Row(equal_height=True):
                search_type = gr.Radio(
                    choices=["Text", "Image"],
                    label="Search by",
                    value="Text",
                )
                top_k_slider = gr.Slider(
                    label="Top K",
                    minimum=1,
                    maximum=50,
                    step=1,
                    value=5,
                )
                search_mode = gr.Dropdown(
                    choices=[
                        ("FAISS ANN", "faiss"),
                        ("Exact", "exact"),
                    ],
                    label="Search mode",
                    value="faiss",
                )
                faiss_nprobe = gr.Slider(
                    label="FAISS nprobe",
                    minimum=1,
                    maximum=64,
                    step=1,
                    value=DEFAULT_FAISS_NPROBE,
                )

            with gr.Column(visible=True) as text_input:
                text = gr.Textbox(label="Text", placeholder="Enter text to search")
            with gr.Column(visible=False) as image_input:
                image = gr.Image(label="Image", type="pil")

            search_type.change(
                toggle_inputs,
                inputs=[search_type],
                outputs=[text_input, image_input],
                api_name="toggle_inputs",
            )
            search_mode.change(
                toggle_faiss_controls,
                inputs=[search_mode],
                outputs=[faiss_nprobe],
                queue=False,
                api_name=False,
            )

            search_btn = gr.Button("Search", variant="primary")
            status = gr.Textbox(label="Status", value="Ready")
            gallery = gr.Gallery(
                label="Results",
                show_label=True,
                columns=5,
                rows=2,
                height="auto",
                preview=False,
            )
            image_info_score = gr.Textbox(
                label="Similarity Score",
                value="Select an image to view details",
            )
            image_info_caption = gr.Textbox(
                label="Caption",
                value="Select an image to view details",
            )

        with gr.Accordion("Index maintenance", open=False):
            path_input = gr.Textbox(
                label="Path",
                info="Dataset image directory",
                value=images_path,
            )
            with gr.Row():
                scan_dir_btn = gr.Button("Scan Directory", variant="primary")
                cancel_scan_btn = gr.Button("Cancel", variant="stop")

        with gr.Column(visible=False):
            legacy_use_cluster_search = gr.Checkbox(
                label="Use FAISS cluster search",
                value=False,
            )
            legacy_search_btn = gr.Button("Legacy search")

        search_btn.click(
            fn=combined_search,
            inputs=[
                search_type,
                text,
                image,
                top_k_slider,
                search_mode,
                faiss_nprobe,
            ],
            outputs=[gallery, results_state, status],
            api_name="combined_search_v2",
        )
        legacy_search_btn.click(
            fn=legacy_combined_search,
            inputs=[
                search_type,
                text,
                image,
                top_k_slider,
                legacy_use_cluster_search,
            ],
            outputs=[gallery, results_state, status],
            api_name="combined_search",
        )
        gallery.select(
            fn=get_image_info,
            inputs=[results_state],
            outputs=[image_info_score, image_info_caption],
            api_name="get_image_info",
        )
        scan_event = scan_dir_btn.click(
            fn=scan_dir,
            inputs=[path_input],
            outputs=[path_input],
            api_name="scan_dir",
            concurrency_limit=1,
            concurrency_id="dataset-reindex",
        )
        cancel_scan_btn.click(
            fn=cancel_scan,
            outputs=[status],
            cancels=[scan_event],
            queue=False,
            api_name=False,
        )

    return webui


def create_app() -> gr.Blocks:
    env = download_and_prepare_dataset()
    clip_searcher = CLIPSearcher(model_id=env["MODEL_ID"])
    image_indexer = ImageIndexer(env["INDEX_PATH"])
    search_mechanism = SearchMechanism(
        clip_searcher=clip_searcher,
        image_indexer=image_indexer,
        default_images_path=env["DEFAULT_IMAGES_PATH"],
        captions_path=env["CAPTIONS_PATH"],
    )
    return build_app(
        search_mechanism,
        env["DEFAULT_IMAGES_PATH"],
        scan_batch_size=int(env["SCAN_BATCH_SIZE"]),
    )


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    webui = create_app()
    webui.queue()
    webui.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", "7860")),
    )


if __name__ == "__main__":
    main()
