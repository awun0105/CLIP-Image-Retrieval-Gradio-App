import inspect

from app import (
    SearchController,
    _detail_markdown,
    _keyframe_directory,
    _timestamp,
    build_app,
    search_keyframes_gpu,
)
from schemas import KeyframeDetails, SearchResult


class FakeSearchMechanism:
    def filter_options(self):
        return {
            "collections": ["C01"],
            "videos": ["V01"],
            "objects": ["Person"],
            "authors": ["Alice"],
        }

    def get_keyframe_details(self, _keyframe_id):
        return KeyframeDetails({}, {})


def test_build_app_exposes_keyframe_endpoints_and_filters():
    app = build_app(FakeSearchMechanism())
    endpoints = app.get_api_info()["named_endpoints"]
    assert "/search_keyframes" in endpoints
    assert "/get_keyframe_details" in endpoints
    assert len(endpoints["/search_keyframes"]["parameters"]) == 11

    config = app.get_config_file()
    labels = {
        component["props"].get("label")
        for component in config["components"]
        if component.get("props", {}).get("label")
    }
    assert {
        "Query",
        "Language",
        "Top K",
        "Collections",
        "Video ID",
        "Objects",
        "Detected objects",
    } <= labels

    components_by_label = {
        component["props"].get("label"): component["props"]
        for component in config["components"]
        if component.get("props", {}).get("label")
    }
    assert components_by_label["Video ID"]["value"] == ""
    assert components_by_label["Author / Channel"]["value"] == ""
    assert any(
        component["props"].get("elem_id") == "app-title" for component in config["components"]
    )
    assert "@media (max-width: 600px)" in config["css"]


def test_zerogpu_entrypoint_does_not_serialize_controller_instance():
    assert next(iter(inspect.signature(search_keyframes_gpu).parameters)) == "query"
    assert "@spaces.GPU" not in inspect.getsource(SearchController.search_keyframes)
    assert "@spaces.GPU" in inspect.getsource(search_keyframes_gpu)


def test_click_and_enter_use_the_same_zerogpu_entrypoint():
    app = build_app(FakeSearchMechanism())
    callback_names = [
        getattr(block_function.fn, "__name__", "") for block_function in app.fns.values()
    ]

    assert callback_names.count("search_keyframes_gpu") == 2
    assert "search_keyframes" not in callback_names


def test_allowed_file_directory_is_limited_to_keyframes(tmp_path):
    assert _keyframe_directory(tmp_path) == (tmp_path / "keyframes").resolve()


def test_detail_markdown_contains_required_metadata():
    details = KeyframeDetails(
        keyframe={
            "keyframe_id": "V01_001",
            "video_id": "V01",
            "collection_id": "C01",
            "keyframe_no": 1,
            "frame_idx": 90,
            "pts_time_sec": 3.0,
            "fps": 30.0,
            "width": 1280,
            "height": 720,
        },
        video={
            "title": "Title",
            "author": "Alice",
            "channel_id": "channel",
            "publish_date_iso": "2024-01-01",
            "watch_url": "https://example.com/watch?v=1",
        },
    )
    markdown = _detail_markdown(details)
    for expected in ["V01_001", "Frame index", "00:00:03.000", "30", "1280 x 720"]:
        assert expected in markdown
    assert "t=3s" in markdown
    assert 'target="_blank"' in markdown
    assert 'rel="noopener noreferrer"' in markdown


def test_timestamp_and_search_result_serialization():
    assert _timestamp(3661.125) == "01:01:01.125"
    result = SearchResult(
        0,
        "V01_001",
        "V01",
        "C01",
        1,
        "/data/keyframes/C01/V01/001.jpg",
        "keyframes/C01/V01/001.jpg",
        0.75,
        3.0,
        90,
        30.0,
        1280,
        720,
        "Title",
    )
    assert result.to_dict()["keyframe_id"] == "V01_001"
