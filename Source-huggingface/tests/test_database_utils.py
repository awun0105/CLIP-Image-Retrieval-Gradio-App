import hashlib
import json
from pathlib import Path

import database_utils
import pytest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_release(tmp_path: Path) -> Path:
    release = tmp_path / "release"
    files = {
        "index/keyframes.faiss": b"faiss",
        "index/embeddings.f16.npy": b"embeddings",
        "metadata/runtime.sqlite": b"sqlite",
    }
    artifacts = {}
    for relative_path, contents in files.items():
        path = release / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
        artifacts[relative_path] = {"size_bytes": len(contents), "sha256": _sha256(path)}
    manifest = {
        "schema_version": 1,
        "release_id": "test-v1",
        "artifacts": artifacts,
    }
    manifest_path = release / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (release / "READY.json").write_text(
        json.dumps(
            {
                "release_id": "test-v1",
                "manifest_sha256": _sha256(manifest_path),
            }
        ),
        encoding="utf-8",
    )
    return release


def test_prepare_runtime_copies_verified_artifacts(tmp_path, monkeypatch):
    release = _write_release(tmp_path)
    cache = tmp_path / "cache"
    monkeypatch.setenv("DATA_ROOT", str(release))
    monkeypatch.setenv("CACHE_ROOT", str(cache))
    runtime = database_utils.prepare_runtime(tmp_path / "missing.env")
    assert runtime.index_file.read_bytes() == b"faiss"
    assert runtime.embeddings_file.read_bytes() == b"embeddings"
    assert runtime.sqlite_file.read_bytes() == b"sqlite"


def test_prepare_runtime_repairs_corrupt_cached_file(tmp_path, monkeypatch):
    release = _write_release(tmp_path)
    monkeypatch.setenv("DATA_ROOT", str(release))
    monkeypatch.setenv("CACHE_ROOT", str(tmp_path / "cache"))
    runtime = database_utils.prepare_runtime(tmp_path / "missing.env")
    runtime.index_file.write_bytes(b"corrupt")
    repaired = database_utils.prepare_runtime(tmp_path / "missing.env")
    assert repaired.index_file.read_bytes() == b"faiss"


def test_prepare_runtime_rejects_incomplete_release(tmp_path, monkeypatch):
    release = _write_release(tmp_path)
    (release / "READY.json").unlink()
    monkeypatch.setenv("DATA_ROOT", str(release))
    monkeypatch.setenv("CACHE_ROOT", str(tmp_path / "cache"))
    with pytest.raises(FileNotFoundError, match="not ready"):
        database_utils.prepare_runtime(tmp_path / "missing.env")


def test_prepare_runtime_rejects_manifest_tampering(tmp_path, monkeypatch):
    release = _write_release(tmp_path)
    (release / "manifest.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DATA_ROOT", str(release))
    monkeypatch.setenv("CACHE_ROOT", str(tmp_path / "cache"))
    with pytest.raises(ValueError, match="checksum"):
        database_utils.prepare_runtime(tmp_path / "missing.env")
