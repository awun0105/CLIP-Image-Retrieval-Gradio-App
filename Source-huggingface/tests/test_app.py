from pathlib import Path

import pytest
from app import DEFAULT_FAISS_NPROBE, _ScanController, _use_faiss, build_app
from schemas import SearchResult


class FakeSearchMechanism:
    def query_by_text(self, _text, _top_k, _use_faiss, _nprobe=None):
        return []

    def query_by_image(self, _image, _top_k, _use_faiss, _nprobe=None):
        return []

    def scan_directory(self, _path, **_kwargs):
        return 0


def test_scan_controller_supports_cooperative_cancel():
    controller = _ScanController()
    assert not controller.cancel()
    controller.begin()
    assert controller.cancel()
    assert controller.cancel_event.is_set()
    controller.finish()


def test_search_mode_maps_to_local_backends():
    assert _use_faiss("faiss") is True
    assert _use_faiss("exact") is False
    with pytest.raises(ValueError, match="Unsupported search mode"):
        _use_faiss("ann_indexed_only")


def test_build_app_preserves_public_endpoint_names(tmp_path):
    app = build_app(FakeSearchMechanism(), str(Path(tmp_path)))
    config = app.get_config_file()
    api_names = {dependency.get("api_name") for dependency in config["dependencies"]}
    assert {
        "toggle_inputs",
        "combined_search",
        "combined_search_v2",
        "get_image_info",
        "scan_dir",
    } <= api_names
    assert "cancel_scan" not in api_names

    endpoints = app.get_api_info()["named_endpoints"]
    assert [item["parameter_name"] for item in endpoints["/toggle_inputs"]["parameters"]] == [
        "search_type"
    ]
    assert [item["parameter_name"] for item in endpoints["/scan_dir"]["parameters"]] == ["path"]
    assert len(endpoints["/combined_search"]["parameters"]) == 5
    assert len(endpoints["/combined_search"]["returns"]) == 2
    assert [item["parameter_name"] for item in endpoints["/combined_search_v2"]["parameters"]] == [
        "search_type",
        "text",
        "image",
        "top_k",
        "search_mode",
        "faiss_nprobe",
    ]
    assert len(endpoints["/combined_search_v2"]["returns"]) == 2


def test_build_app_uses_localhost_layout_with_faiss_controls(tmp_path):
    app = build_app(FakeSearchMechanism(), str(Path(tmp_path)))
    config = app.get_config_file()
    components_by_label = {
        component["props"].get("label"): component
        for component in config["components"]
        if component.get("props", {}).get("label")
    }

    mode = components_by_label["Search mode"]["props"]
    assert mode["choices"] == [("FAISS ANN", "faiss"), ("Exact", "exact")]
    assert mode["value"] == "faiss"
    nprobe = components_by_label["FAISS nprobe"]["props"]
    assert (nprobe["minimum"], nprobe["maximum"], nprobe["value"]) == (
        1,
        64,
        DEFAULT_FAISS_NPROBE,
    )
    accordion = next(
        component for component in config["components"] if component["type"] == "accordion"
    )
    assert accordion["props"]["label"] == "Index maintenance"
    assert accordion["props"]["open"] is False


def test_search_result_state_is_serializable():
    result = SearchResult("images/a.jpg", 0.75, "caption", "a.jpg")
    assert result.to_dict() == {
        "image_path": "images/a.jpg",
        "score": 0.75,
        "caption": "caption",
        "filename": "a.jpg",
    }
