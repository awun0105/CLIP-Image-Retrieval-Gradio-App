"""Upload a built release to a Hugging Face Bucket with resumable batches."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath

from huggingface_hub import (
    BucketFile,
    HfApi,
    batch_bucket_files,
    get_bucket_paths_info,
    list_bucket_tree,
)
from huggingface_hub.utils import disable_progress_bars

DEFAULT_BUCKET_ID = "1thesudden/aiou-app-storage"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def remote_path(prefix: str, relative_path: str) -> str:
    prefix_path = PurePosixPath(prefix.strip("/"))
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe remote path: {relative_path}")
    return str(prefix_path / relative)


def load_upload_map(path: Path) -> list[tuple[Path, str]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            local_path = Path(str(row["local_path"]))
            destination = str(row["remote_path"])
            if not local_path.is_file():
                raise FileNotFoundError(
                    f"Upload source does not exist at line {line_number}: {local_path}"
                )
            rows.append((local_path, destination))
    if not rows:
        raise ValueError(f"Upload map is empty: {path}")
    return rows


def load_manifest(release_dir: Path) -> dict:
    manifest_path = release_dir / "manifest.json"
    ready_path = release_dir / "READY.json"
    if not manifest_path.is_file() or not ready_path.is_file():
        raise FileNotFoundError("Release must contain manifest.json and READY.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ready = json.loads(ready_path.read_text(encoding="utf-8"))
    if ready.get("release_id") != manifest.get("release_id"):
        raise ValueError("READY.json and manifest.json release IDs disagree")
    if ready.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("READY.json does not match manifest.json")
    return manifest


def _existing_paths(bucket_id: str, paths: list[str]) -> set[str]:
    return {item.path for item in get_bucket_paths_info(bucket_id, paths)}


def _load_state(
    state_path: Path,
    *,
    bucket_id: str,
    prefix: str,
    upload_map_sha256: str,
) -> dict:
    expected = {
        "bucket_id": bucket_id,
        "prefix": prefix,
        "upload_map_sha256": upload_map_sha256,
    }
    if state_path.is_file():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for key, value in expected.items():
            if state.get(key) != value:
                raise ValueError(f"Upload state {key} does not match the current command")
        if "completed_images" not in state:
            state["completed_images"] = int(state.get("completed_image_batches", 0)) * int(
                state.get("batch_size", 0)
            )
        if "completed_ranges" not in state:
            completed_images = int(state.get("completed_images", 0))
            state["completed_ranges"] = [[0, completed_images]] if completed_images else []
        state.pop("completed_image_batches", None)
        state.pop("completed_images", None)
        state.pop("batch_size", None)
        return state
    return {**expected, "completed_ranges": [], "artifacts_uploaded": False}


def _save_state(path: Path, state: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)


def _merge_ranges(ranges: list[list[int]]) -> list[list[int]]:
    merged: list[list[int]] = []
    for start, end in sorted(ranges):
        if start < 0 or end < start:
            raise ValueError(f"Invalid completed upload range: {[start, end]}")
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def _range_is_complete(ranges: list[list[int]], start: int, end: int) -> bool:
    return any(range_start <= start and range_end >= end for range_start, range_end in ranges)


def _upload_image_batch(
    bucket_id: str,
    prefix: str,
    batch: list[tuple[Path, str]],
) -> None:
    additions = [
        (local_path, remote_path(prefix, destination)) for local_path, destination in batch
    ]
    for attempt in range(6):
        try:
            HfApi().batch_bucket_files(bucket_id, add=additions)
            return
        except Exception as exc:
            if attempt == 5:
                raise
            delay = min(60, 5 * (2**attempt))
            print(
                f"Upload batch retry {attempt + 1}/5 in {delay}s: {exc}",
                flush=True,
            )
            time.sleep(delay)


def verify_release(
    bucket_id: str,
    prefix: str,
    manifest: dict,
    expected_image_count: int,
) -> None:
    control_paths = [
        remote_path(prefix, relative_path)
        for relative_path in [*manifest["artifacts"], "manifest.json", "READY.json"]
    ]
    existing = _existing_paths(bucket_id, control_paths)
    missing = sorted(set(control_paths) - existing)
    if missing:
        raise ValueError(f"Bucket release is missing control artifacts: {missing}")

    image_prefix = remote_path(prefix, "keyframes") + "/"
    image_count = sum(
        1
        for item in list_bucket_tree(bucket_id, prefix=image_prefix, recursive=True)
        if isinstance(item, BucketFile) and item.path.lower().endswith(".jpg")
    )
    if image_count != expected_image_count:
        raise ValueError(
            f"Bucket contains {image_count} release images, expected {expected_image_count}"
        )
    print(
        f"Verified bucket release {bucket_id}/{prefix}: "
        f"images={image_count}, artifacts={len(control_paths)}",
        flush=True,
    )


def upload_release(
    release_dir: Path,
    bucket_id: str,
    prefix: str | None,
    batch_size: int,
    upload_map_path: Path | None,
    state_path: Path | None,
    workers: int,
) -> None:
    disable_progress_bars()
    if batch_size < 1 or batch_size > 1_000:
        raise ValueError("batch_size must be in [1, 1000]")
    if workers < 1 or workers > 8:
        raise ValueError("workers must be in [1, 8]")
    release_dir = release_dir.resolve()
    manifest = load_manifest(release_dir)
    prefix = (prefix or f"releases/{manifest['release_id']}").strip("/")
    upload_map_path = (upload_map_path or release_dir / "upload-map.jsonl").resolve()
    uploads = load_upload_map(upload_map_path)
    expected_count = int(manifest["counts"]["keyframes"])
    if len(uploads) != expected_count:
        raise ValueError(f"Upload map has {len(uploads)} images, expected {expected_count}")

    ready_remote = remote_path(prefix, "READY.json")
    if ready_remote in _existing_paths(bucket_id, [ready_remote]):
        verify_release(bucket_id, prefix, manifest, expected_count)
        print("Release is already published; no files were changed.", flush=True)
        return

    if state_path is None:
        state_path = (
            release_dir / ".upload-state.json"
            if upload_map_path == release_dir / "upload-map.jsonl"
            else upload_map_path.with_suffix(".upload-state.json")
        )
    state = _load_state(
        state_path,
        bucket_id=bucket_id,
        prefix=prefix,
        upload_map_sha256=sha256_file(upload_map_path),
    )
    completed_ranges = _merge_ranges(state.get("completed_ranges", []))
    if completed_ranges and completed_ranges[-1][1] > len(uploads):
        raise ValueError("Upload state contains a range beyond the upload map")
    pending = []
    for start in range(0, len(uploads), batch_size):
        end = min(start + batch_size, len(uploads))
        if not _range_is_complete(completed_ranges, start, end):
            pending.append((start, end))

    completed_batch_count = 0
    executor = ThreadPoolExecutor(max_workers=workers)
    futures = {}
    try:
        futures = {
            executor.submit(
                _upload_image_batch,
                bucket_id,
                prefix,
                uploads[start:end],
            ): (start, end)
            for start, end in pending
        }
        for future in as_completed(futures):
            start, end = futures[future]
            future.result()
            completed_ranges = _merge_ranges([*completed_ranges, [start, end]])
            state["completed_ranges"] = completed_ranges
            _save_state(state_path, state)
            completed_batch_count += 1
            completed_images = sum(end - start for start, end in completed_ranges)
            print(
                f"Uploaded image batch {completed_batch_count}/{len(pending)} "
                f"({completed_images}/{len(uploads)} images)",
                flush=True,
            )
    finally:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)

    if not _range_is_complete(completed_ranges, 0, len(uploads)):
        raise ValueError("Image upload ranges are incomplete")

    if not state["artifacts_uploaded"]:
        artifact_paths = [release_dir / relative_path for relative_path in manifest["artifacts"]]
        missing_artifacts = [path for path in artifact_paths if not path.is_file()]
        if missing_artifacts:
            raise FileNotFoundError(f"Release artifacts are missing: {missing_artifacts}")
        batch_bucket_files(
            bucket_id,
            add=[
                (path, remote_path(prefix, str(path.relative_to(release_dir))))
                for path in artifact_paths
            ],
        )
        state["artifacts_uploaded"] = True
        _save_state(state_path, state)
        print(f"Uploaded {len(artifact_paths)} release artifacts", flush=True)

    batch_bucket_files(
        bucket_id,
        add=[(release_dir / "manifest.json", remote_path(prefix, "manifest.json"))],
    )
    manifest_remote = remote_path(prefix, "manifest.json")
    if manifest_remote not in _existing_paths(bucket_id, [manifest_remote]):
        raise ValueError("manifest.json is not visible after upload")
    batch_bucket_files(
        bucket_id,
        add=[(release_dir / "READY.json", ready_remote)],
    )
    verify_release(bucket_id, prefix, manifest, expected_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--bucket-id", default=DEFAULT_BUCKET_ID)
    parser.add_argument("--prefix")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--upload-map", type=Path)
    parser.add_argument("--state-path", type=Path)
    parser.add_argument("--verify-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = load_manifest(args.release_dir)
    prefix = (args.prefix or f"releases/{manifest['release_id']}").strip("/")
    if args.verify_only:
        verify_release(
            args.bucket_id,
            prefix,
            manifest,
            int(manifest["counts"]["keyframes"]),
        )
        return
    upload_release(
        args.release_dir,
        args.bucket_id,
        prefix,
        args.batch_size,
        args.upload_map,
        args.state_path,
        args.workers,
    )


if __name__ == "__main__":
    main()
