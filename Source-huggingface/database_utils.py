"""Validate a mounted data release and prepare local runtime artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

DEFAULTS = {
    "DATA_ROOT": "/data/releases/aic25-b1-v1",
    "CACHE_ROOT": "/tmp/aiou-cache",
    "MODEL_ID": "openai/clip-vit-base-patch32",
    "MODEL_REVISION": "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268",
    "FAISS_NPROBE": "32",
    "RESULTS_PER_PAGE": "20",
    "TRANSLATION_MODEL_ID": "Helsinki-NLP/opus-mt-vi-en",
    "TRANSLATION_MODEL_REVISION": "c8d2853e77f5fae31124d993e0b35176b1c8914e",
}

RUNTIME_ARTIFACTS = {
    "index/keyframes.faiss": "keyframes.faiss",
    "index/embeddings.f16.npy": "embeddings.f16.npy",
    "metadata/runtime.sqlite": "runtime.sqlite",
}


@dataclass(frozen=True)
class RuntimePaths:
    data_root: Path
    cache_root: Path
    index_file: Path
    embeddings_file: Path
    sqlite_file: Path
    manifest: dict
    environment: dict[str, str]


def load_environment(dotenv_path: str | Path = ".env") -> dict[str, str]:
    """Load defaults, optional dotenv values, then real environment variables."""
    values = dict(DEFAULTS)
    path = Path(dotenv_path)
    if path.exists():
        values.update({key: value for key, value in dotenv_values(path).items() if value})
    for key in DEFAULTS:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(data_root: Path) -> dict:
    ready_path = data_root / "READY.json"
    manifest_path = data_root / "manifest.json"
    if not ready_path.is_file():
        raise FileNotFoundError(f"Release is not ready: {ready_path}")
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Release manifest not found: {manifest_path}")
    with ready_path.open("r", encoding="utf-8") as handle:
        ready = json.load(handle)
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    expected_manifest_sha256 = str(ready.get("manifest_sha256") or "")
    if not expected_manifest_sha256:
        raise ValueError("READY.json does not contain manifest_sha256")
    actual_manifest_sha256 = sha256_file(manifest_path)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise ValueError(
            "Release manifest checksum does not match READY.json: "
            f"expected {expected_manifest_sha256}, got {actual_manifest_sha256}"
        )
    if ready.get("release_id") != manifest.get("release_id"):
        raise ValueError("READY.json and manifest.json release IDs disagree")
    if manifest.get("schema_version") != 1:
        raise ValueError(f"Unsupported release schema: {manifest.get('schema_version')}")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ValueError("Release manifest does not contain an artifacts map")
    return manifest


def _copy_verified(source: Path, target: Path, expected_sha256: str) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Required release artifact not found: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        actual = sha256_file(temporary)
        if actual != expected_sha256:
            raise ValueError(
                f"Checksum mismatch for {source}: expected {expected_sha256}, got {actual}"
            )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_runtime(dotenv_path: str | Path = ".env") -> RuntimePaths:
    """Copy immutable runtime files from the mounted release into ephemeral cache."""
    environment = load_environment(dotenv_path)
    data_root = Path(environment["DATA_ROOT"])
    manifest = _load_manifest(data_root)
    release_id = str(manifest.get("release_id") or data_root.name)
    cache_root = Path(environment["CACHE_ROOT"]) / release_id
    cache_root.mkdir(parents=True, exist_ok=True)

    cached_manifest_path = cache_root / "manifest.json"
    cached_manifest = None
    if cached_manifest_path.is_file():
        try:
            cached_manifest = json.loads(cached_manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            cached_manifest = None

    cache_matches = cached_manifest == manifest
    artifacts = manifest["artifacts"]
    local_files: dict[str, Path] = {}
    for relative_path, local_name in RUNTIME_ARTIFACTS.items():
        metadata = artifacts.get(relative_path)
        if not isinstance(metadata, dict) or not metadata.get("sha256"):
            raise ValueError(f"Manifest is missing checksum for {relative_path}")
        target = cache_root / local_name
        expected_sha256 = str(metadata["sha256"])
        cached_file_matches = (
            cache_matches and target.is_file() and sha256_file(target) == expected_sha256
        )
        if not cached_file_matches:
            _copy_verified(data_root / relative_path, target, expected_sha256)
        local_files[relative_path] = target

    cached_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return RuntimePaths(
        data_root=data_root,
        cache_root=cache_root,
        index_file=local_files["index/keyframes.faiss"],
        embeddings_file=local_files["index/embeddings.f16.npy"],
        sqlite_file=local_files["metadata/runtime.sqlite"],
        manifest=manifest,
        environment=environment,
    )
