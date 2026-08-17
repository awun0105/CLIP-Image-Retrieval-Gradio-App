"""Standalone Gradio application for filtered keyframe retrieval."""

from __future__ import annotations

import html
import logging
import os
from pathlib import Path

try:
    import spaces
except ImportError:

    class _LocalSpaces:
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
from database_utils import RuntimePaths, prepare_runtime
from schemas import SearchFilters
from translation import QueryTranslator

from db import SearchMechanism

logger = logging.getLogger(__name__)

APP_CSS = """
body { overflow-y: auto !important; }
@media (max-width: 600px) {
    #app-title { margin-top: 3.5rem; }
}
"""


def _timestamp(seconds: float) -> str:
    total_milliseconds = max(0, round(float(seconds) * 1000))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


def _watch_at(url: str, seconds: float) -> str:
    if not url:
        return ""
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}t={max(0, int(seconds))}s"


def _keyframe_directory(data_root: Path) -> Path:
    return (data_root / "keyframes").resolve()


def _detail_markdown(details) -> str:
    keyframe = details.keyframe
    video = details.video
    watch_url = _watch_at(str(video.get("watch_url") or ""), keyframe["pts_time_sec"])
    watch_link = (
        f'<a href="{html.escape(watch_url, quote=True)}" target="_blank" '
        'rel="noopener noreferrer">Open video</a>'
        if watch_url
        else "N/A"
    )
    values = {
        "Keyframe ID": keyframe["keyframe_id"],
        "Video ID": keyframe["video_id"],
        "Collection": keyframe["collection_id"],
        "Keyframe no.": keyframe["keyframe_no"],
        "Frame index": keyframe["frame_idx"],
        "Timestamp": _timestamp(keyframe["pts_time_sec"]),
        "FPS": f"{float(keyframe['fps']):.4g}",
        "Resolution": f"{keyframe['width']} x {keyframe['height']}",
        "Title": video.get("title") or "N/A",
        "Author": video.get("author") or "N/A",
        "Channel": video.get("channel_id") or "N/A",
        "Published": video.get("publish_date_iso") or video.get("publish_date_raw") or "N/A",
    }
    rows = [f"| {label} | {html.escape(str(value))} |" for label, value in values.items()]
    return "\n".join(["| Field | Value |", "|---|---|", *rows, f"| Source | {watch_link} |"])


def _detection_rows(details) -> list[list]:
    return [
        [
            row["entity"],
            round(float(row["score"]), 4),
            row["class_mid"],
            row["class_label"],
            round(float(row["ymin"]), 4),
            round(float(row["xmin"]), 4),
            round(float(row["ymax"]), 4),
            round(float(row["xmax"]), 4),
        ]
        for row in details.detections
    ]


class SearchController:
    """UI callbacks bound to one immutable runtime release."""

    def __init__(self, search_mechanism: SearchMechanism, page_size: int) -> None:
        self.search_mechanism = search_mechanism
        self.page_size = page_size

    def page_payload(self, rows: list[dict], page: int):
        rows = rows or []
        total_pages = max(1, (len(rows) + self.page_size - 1) // self.page_size)
        page = max(0, min(int(page), total_pages - 1))
        start = page * self.page_size
        page_rows = rows[start : start + self.page_size]
        gallery = [
            (
                row["image_path"],
                f"{row['keyframe_id']} | {_timestamp(row['pts_time_sec'])} | {row['score']:.4f}",
            )
            for row in page_rows
            if Path(row["image_path"]).is_file()
        ]
        label = f"Page {page + 1} / {total_pages} | {len(rows)} results"
        return (
            gallery,
            page,
            label,
            gr.update(interactive=page > 0),
            gr.update(interactive=page + 1 < total_pages),
        )

    def search_keyframes(
        self,
        query,
        top_k,
        query_language,
        collections,
        video_id,
        object_entities,
        object_match_mode,
        minimum_object_confidence,
        author,
        publish_date_from,
        publish_date_to,
    ):
        try:
            filters = SearchFilters(
                collections=tuple(collections or ()),
                video_id=video_id or None,
                object_entities=tuple(object_entities or ()),
                object_match_mode=str(object_match_mode).lower(),
                minimum_object_confidence=float(minimum_object_confidence),
                author=author or None,
                publish_date_from=publish_date_from or None,
                publish_date_to=publish_date_to or None,
            )
            outcome = self.search_mechanism.search_by_text(
                query,
                int(top_k),
                str(query_language).lower(),
                filters,
            )
            rows = [result.to_dict() for result in outcome.results]
            gallery, page, label, previous_update, next_update = self.page_payload(rows, 0)
            query_info = f"CLIP query: {outcome.query.clip_query}"
            if outcome.query.translated:
                query_info = f"Translated query: {outcome.query.clip_query}"
            if outcome.query.warning:
                query_info = f"{query_info} | {outcome.query.warning}"
            status = f"Found {len(rows)} results | {query_info}"
            return (
                gallery,
                rows,
                page,
                status,
                label,
                previous_update,
                next_update,
                None,
                "Select a keyframe to view metadata",
                [],
            )
        except Exception as exc:
            logger.exception("Keyframe search failed")
            return (
                [],
                [],
                0,
                f"Error: {exc}",
                "Page 1 / 1 | 0 results",
                gr.update(interactive=False),
                gr.update(interactive=False),
                None,
                "Select a keyframe to view metadata",
                [],
            )

    def previous_page(self, rows, page):
        return self.page_payload(rows, int(page) - 1)

    def next_page(self, rows, page):
        return self.page_payload(rows, int(page) + 1)

    def select_keyframe(self, rows, page, evt: gr.SelectData):
        if not rows or evt.index is None:
            return None, "Select a keyframe to view metadata", []
        local_index = int(evt.index[0] if isinstance(evt.index, tuple) else evt.index)
        global_index = int(page) * self.page_size + local_index
        if global_index < 0 or global_index >= len(rows):
            return None, "Selected result is no longer available", []
        row = rows[global_index]
        details = self.search_mechanism.get_keyframe_details(row["keyframe_id"])
        return row["image_path"], _detail_markdown(details), _detection_rows(details)

    def details_api(self, keyframe_id: str):
        details = self.search_mechanism.get_keyframe_details(keyframe_id)
        return {
            "keyframe": details.keyframe,
            "video": details.video,
            "detections": list(details.detections),
        }


_search_controller: SearchController | None = None
_keyframes_root: Path | None = None


@spaces.GPU(duration=120)
def search_keyframes_gpu(
    query,
    top_k,
    query_language,
    collections,
    video_id,
    object_entities,
    object_match_mode,
    minimum_object_confidence,
    author,
    publish_date_from,
    publish_date_to,
):
    """Run CLIP retrieval without passing unpicklable runtime state to ZeroGPU."""
    if _search_controller is None:
        raise RuntimeError("Search controller has not been initialized")
    return _search_controller.search_keyframes(
        query,
        top_k,
        query_language,
        collections,
        video_id,
        object_entities,
        object_match_mode,
        minimum_object_confidence,
        author,
        publish_date_from,
        publish_date_to,
    )


def build_app(search_mechanism: SearchMechanism, *, page_size: int = 20) -> gr.Blocks:
    """Construct the Gradio UI and bind it to a prepared search mechanism."""
    global _search_controller

    options = search_mechanism.filter_options()
    controller = SearchController(search_mechanism, page_size)
    _search_controller = controller

    with gr.Blocks(css=APP_CSS) as webui:
        gr.Markdown("## AIoU Keyframe Retrieval", elem_id="app-title")
        results_state = gr.State([])
        page_state = gr.State(0)

        with gr.Row(equal_height=True):
            query = gr.Textbox(
                label="Query",
                placeholder="Describe the keyframe you want to find",
                scale=5,
            )
            query_language = gr.Dropdown(
                label="Language",
                choices=[("Auto", "auto"), ("English", "english"), ("Vietnamese", "vietnamese")],
                value="auto",
                scale=1,
            )
            top_k = gr.Slider(label="Top K", minimum=1, maximum=100, step=1, value=20, scale=2)

        with gr.Accordion("Filters", open=False):
            with gr.Row():
                collections = gr.Dropdown(
                    label="Collections",
                    choices=options["collections"],
                    multiselect=True,
                )
                video_id = gr.Dropdown(
                    label="Video ID",
                    choices=[("All videos", ""), *options["videos"]],
                    value="",
                    filterable=True,
                )
                author = gr.Dropdown(
                    label="Author / Channel",
                    choices=[("All authors", ""), *options["authors"]],
                    value="",
                    filterable=True,
                )
            with gr.Row():
                object_entities = gr.Dropdown(
                    label="Objects",
                    choices=options["objects"],
                    multiselect=True,
                    filterable=True,
                    scale=4,
                )
                object_match_mode = gr.Radio(
                    label="Object match",
                    choices=[("Any", "any"), ("All", "all")],
                    value="any",
                    scale=1,
                )
                minimum_object_confidence = gr.Slider(
                    label="Minimum confidence",
                    minimum=0.3,
                    maximum=1.0,
                    step=0.05,
                    value=0.3,
                    scale=2,
                )
            with gr.Row():
                publish_date_from = gr.Textbox(label="Published from", placeholder="YYYY-MM-DD")
                publish_date_to = gr.Textbox(label="Published to", placeholder="YYYY-MM-DD")

        search_button = gr.Button("Search", variant="primary")
        status = gr.Textbox(label="Status", value="Ready", interactive=False)
        gallery = gr.Gallery(
            label="Keyframes",
            show_label=True,
            columns=5,
            rows=4,
            height="auto",
            preview=False,
        )
        with gr.Row():
            previous_button = gr.Button("Previous", interactive=False)
            page_label = gr.Textbox(
                value="Page 1 / 1 | 0 results",
                show_label=False,
                interactive=False,
            )
            next_button = gr.Button("Next", interactive=False)

        with gr.Row(equal_height=False):
            with gr.Column(scale=2):
                detail_image = gr.Image(label="Selected keyframe", interactive=False)
            with gr.Column(scale=3):
                detail_metadata = gr.Markdown("Select a keyframe to view metadata")
        detections = gr.Dataframe(
            headers=["Object", "Score", "MID", "Label", "ymin", "xmin", "ymax", "xmax"],
            datatype=["str", "number", "str", "number", "number", "number", "number", "number"],
            label="Detected objects",
            interactive=False,
        )

        with gr.Column(visible=False):
            api_keyframe_id = gr.Textbox()
            api_details = gr.JSON()
            api_details_button = gr.Button("Metadata API")

        search_outputs = [
            gallery,
            results_state,
            page_state,
            status,
            page_label,
            previous_button,
            next_button,
            detail_image,
            detail_metadata,
            detections,
        ]
        search_inputs = [
            query,
            top_k,
            query_language,
            collections,
            video_id,
            object_entities,
            object_match_mode,
            minimum_object_confidence,
            author,
            publish_date_from,
            publish_date_to,
        ]
        search_button.click(
            fn=search_keyframes_gpu,
            inputs=search_inputs,
            outputs=search_outputs,
            api_name="search_keyframes",
        )
        query.submit(
            fn=search_keyframes_gpu,
            inputs=search_inputs,
            outputs=search_outputs,
            api_name=False,
        )
        previous_button.click(
            controller.previous_page,
            inputs=[results_state, page_state],
            outputs=[gallery, page_state, page_label, previous_button, next_button],
            queue=False,
            api_name=False,
        )
        next_button.click(
            controller.next_page,
            inputs=[results_state, page_state],
            outputs=[gallery, page_state, page_label, previous_button, next_button],
            queue=False,
            api_name=False,
        )
        gallery.select(
            controller.select_keyframe,
            inputs=[results_state, page_state],
            outputs=[detail_image, detail_metadata, detections],
            api_name=False,
        )
        api_details_button.click(
            controller.details_api,
            inputs=[api_keyframe_id],
            outputs=[api_details],
            api_name="get_keyframe_details",
        )

    return webui


def create_search_mechanism(runtime: RuntimePaths) -> SearchMechanism:
    environment = runtime.environment
    clip_searcher = CLIPSearcher(
        model_id=environment["MODEL_ID"],
        revision=environment["MODEL_REVISION"],
    )
    if os.environ.get("SPACE_ID"):
        clip_searcher.load()
    return SearchMechanism(
        clip_searcher=clip_searcher,
        translator=QueryTranslator(
            model_id=environment["TRANSLATION_MODEL_ID"],
            revision=environment["TRANSLATION_MODEL_REVISION"],
        ),
        image_indexer=ImageIndexer(
            runtime.index_file,
            nprobe=int(environment["FAISS_NPROBE"]),
        ),
        sqlite_file=runtime.sqlite_file,
        embeddings_file=runtime.embeddings_file,
        data_root=runtime.data_root,
    )


def create_app() -> gr.Blocks:
    global _keyframes_root

    runtime = prepare_runtime()
    _keyframes_root = _keyframe_directory(runtime.data_root)
    search_mechanism = create_search_mechanism(runtime)
    return build_app(
        search_mechanism,
        page_size=int(runtime.environment["RESULTS_PER_PAGE"]),
    )


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    webui = create_app()
    if _keyframes_root is None:
        raise RuntimeError("Keyframe data root has not been initialized")
    webui.queue(default_concurrency_limit=2)
    webui.launch(
        server_name="0.0.0.0",
        server_port=int(os.environ.get("PORT", "7860")),
        ssr_mode=False,
        allowed_paths=[str(_keyframes_root)],
    )


if __name__ == "__main__":
    main()
