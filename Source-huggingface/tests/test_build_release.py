import json
from pathlib import Path

import pytest
from PIL import Image
from tools.build_release import normalize_publish_date, normalized_detections
from tools.optimize_images import optimize_images
from tools.upload_release import _load_state, _merge_ranges, load_manifest, remote_path


def test_normalize_publish_date_supports_raw_formats():
    assert normalize_publish_date("17/08/2026") == "2026-08-17"
    assert normalize_publish_date("2026-08-17") == "2026-08-17"
    assert normalize_publish_date("invalid") == ""


def test_normalized_detections_filters_threshold_and_malformed_rows(tmp_path):
    path = tmp_path / "objects.json"
    path.write_text(
        json.dumps(
            {
                "detection_scores": [0.9, 0.2, 0.8],
                "detection_class_names": ["/m/person", "/m/car", "/m/bad"],
                "detection_class_entities": ["Person", "Car", "Bad"],
                "detection_boxes": [
                    [0.1, 0.2, 0.8, 0.9],
                    [0.1, 0.2, 0.8, 0.9],
                    [0.9, 0.2, 0.1, 0.9],
                ],
                "detection_class_labels": [1, 2, 3],
            }
        ),
        encoding="utf-8",
    )
    rows, malformed = normalized_detections(path, "V01_001", 0.3)
    assert [row["entity"] for row in rows] == ["Person"]
    assert malformed == 1


def test_remote_path_rejects_traversal():
    assert remote_path("releases/v1", "keyframes/C01/001.jpg") == (
        "releases/v1/keyframes/C01/001.jpg"
    )
    with pytest.raises(ValueError, match="Unsafe"):
        remote_path("releases/v1", "../READY.json")


def test_load_manifest_requires_ready_checksum(tmp_path: Path):
    manifest = {"schema_version": 1, "release_id": "v1", "artifacts": {}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (tmp_path / "READY.json").write_text(
        json.dumps({"release_id": "v1", "manifest_sha256": "wrong"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        load_manifest(tmp_path)


def test_upload_state_migrates_from_batch_count(tmp_path: Path):
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "bucket_id": "owner/bucket",
                "prefix": "releases/v1",
                "upload_map_sha256": "abc",
                "batch_size": 128,
                "completed_image_batches": 12,
                "artifacts_uploaded": False,
            }
        ),
        encoding="utf-8",
    )
    state = _load_state(
        state_path,
        bucket_id="owner/bucket",
        prefix="releases/v1",
        upload_map_sha256="abc",
    )
    assert state["completed_ranges"] == [[0, 1536]]
    assert "batch_size" not in state


def test_completed_upload_ranges_are_merged():
    assert _merge_ranges([[2000, 3000], [0, 1000], [1000, 2000]]) == [[0, 3000]]


def test_optimize_images_resizes_display_copy_and_writes_map(tmp_path: Path):
    source = tmp_path / "source.jpg"
    Image.new("RGB", (1280, 720), "red").save(source, quality=95)
    source_map = tmp_path / "source-map.jsonl"
    source_map.write_text(
        json.dumps(
            {
                "local_path": str(source),
                "remote_path": "keyframes/C01/V01/001.jpg",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_root = tmp_path / "optimized"
    output_map = tmp_path / "optimized-map.jsonl"
    report = optimize_images(
        source_map,
        output_root,
        output_map,
        max_edge=576,
        quality=80,
    )
    optimized = output_root / "keyframes/C01/V01/001.jpg"
    with Image.open(optimized) as image:
        assert image.size == (576, 324)
    assert json.loads(output_map.read_text())["local_path"] == str(optimized)
    assert report["image_count"] == 1
