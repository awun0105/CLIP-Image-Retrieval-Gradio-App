"""Build a validated, immutable runtime release from the raw AIC keyframes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import faiss
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

SCHEMA_VERSION = 1
VECTOR_DIMENSION = 512
DEFAULT_MODEL_ID = "openai/clip-vit-base-patch32"
DEFAULT_MODEL_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
DEFAULT_DETECTION_THRESHOLD = 0.3
EXPECTED_VIDEO_COUNT = 873
EXPECTED_KEYFRAME_COUNT = 177_321

VIDEO_SCHEMA = pa.schema(
    [
        ("video_id", pa.string()),
        ("collection_id", pa.string()),
        ("title", pa.string()),
        ("author", pa.string()),
        ("channel_id", pa.string()),
        ("channel_url", pa.string()),
        ("description", pa.string()),
        ("keywords_json", pa.string()),
        ("duration_sec", pa.int64()),
        ("publish_date_raw", pa.string()),
        ("publish_date_iso", pa.string()),
        ("thumbnail_url", pa.string()),
        ("watch_url", pa.string()),
    ]
)

KEYFRAME_SCHEMA = pa.schema(
    [
        ("vector_id", pa.int64()),
        ("keyframe_id", pa.string()),
        ("video_id", pa.string()),
        ("collection_id", pa.string()),
        ("keyframe_no", pa.int32()),
        ("frame_idx", pa.int64()),
        ("pts_time_sec", pa.float64()),
        ("fps", pa.float64()),
        ("width", pa.int32()),
        ("height", pa.int32()),
        ("image_relpath", pa.string()),
    ]
)

DETECTION_SCHEMA = pa.schema(
    [
        ("keyframe_id", pa.string()),
        ("rank", pa.int32()),
        ("entity", pa.string()),
        ("class_mid", pa.string()),
        ("class_label", pa.int32()),
        ("score", pa.float32()),
        ("ymin", pa.float32()),
        ("xmin", pa.float32()),
        ("ymax", pa.float32()),
        ("xmax", pa.float32()),
    ]
)


@dataclass(frozen=True)
class RawVideo:
    video_id: str
    image_dir: Path
    map_file: Path
    media_file: Path
    feature_file: Path
    object_dir: Path

    @property
    def collection_id(self) -> str:
        return self.video_id.split("_", 1)[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_raw_videos(raw_root: Path) -> list[RawVideo]:
    locations: dict[str, Path] = {}
    for keyframe_root in sorted(raw_root.glob("Keyframes_*/keyframes")):
        for image_dir in sorted(path for path in keyframe_root.iterdir() if path.is_dir()):
            if image_dir.name in locations:
                raise ValueError(f"Duplicate keyframe directory for {image_dir.name}")
            locations[image_dir.name] = image_dir

    map_root = raw_root / "map-keyframes-aic25-b1/map-keyframes"
    media_root = raw_root / "media-info-aic25-b1/media-info"
    feature_root = raw_root / "clip-features-32-aic25-b1/clip-features-32"
    object_root = raw_root / "objects-aic25-b1/objects"
    videos = []
    for video_id, image_dir in sorted(locations.items()):
        video = RawVideo(
            video_id=video_id,
            image_dir=image_dir,
            map_file=map_root / f"{video_id}.csv",
            media_file=media_root / f"{video_id}.json",
            feature_file=feature_root / f"{video_id}.npy",
            object_dir=object_root / video_id,
        )
        missing = [
            path
            for path in (video.map_file, video.media_file, video.feature_file, video.object_dir)
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(f"Missing artifacts for {video_id}: {missing}")
        videos.append(video)

    expected_sets = {
        "maps": {path.stem for path in map_root.glob("*.csv")},
        "media": {path.stem for path in media_root.glob("*.json")},
        "features": {path.stem for path in feature_root.glob("*.npy")},
        "objects": {path.name for path in object_root.iterdir() if path.is_dir()},
    }
    image_ids = set(locations)
    for name, artifact_ids in expected_sets.items():
        if artifact_ids != image_ids:
            raise ValueError(
                f"Video IDs differ for {name}: missing={sorted(image_ids - artifact_ids)[:10]}, "
                f"extra={sorted(artifact_ids - image_ids)[:10]}"
            )
    if not videos:
        raise ValueError(f"No raw videos found under {raw_root}")
    return videos


def read_map(video: RawVideo) -> list[dict[str, str]]:
    with video.map_file.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    required = {"n", "pts_time", "fps", "frame_idx"}
    if not rows or not required <= set(rows[0]):
        raise ValueError(f"Invalid keyframe map: {video.map_file}")
    numbers = [int(row["n"]) for row in rows]
    if numbers != list(range(1, len(rows) + 1)):
        raise ValueError(f"Non-contiguous keyframe numbers: {video.map_file}")
    return rows


def normalize_publish_date(raw_value: str) -> str:
    value = str(raw_value or "").strip()
    if not value:
        return ""
    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date().isoformat()
        except ValueError:
            continue
    return ""


def parquet_write(writer: pq.ParquetWriter, rows: list[dict], schema: pa.Schema) -> None:
    if rows:
        writer.write_table(pa.Table.from_pylist(rows, schema=schema))


def create_runtime_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=OFF;
        CREATE TABLE videos (
            video_id TEXT PRIMARY KEY,
            collection_id TEXT NOT NULL,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            channel_url TEXT NOT NULL,
            description TEXT NOT NULL,
            keywords_json TEXT NOT NULL,
            duration_sec INTEGER NOT NULL,
            publish_date_raw TEXT NOT NULL,
            publish_date_iso TEXT NOT NULL,
            thumbnail_url TEXT NOT NULL,
            watch_url TEXT NOT NULL
        );
        CREATE TABLE keyframes (
            vector_id INTEGER PRIMARY KEY,
            keyframe_id TEXT NOT NULL UNIQUE,
            video_id TEXT NOT NULL,
            collection_id TEXT NOT NULL,
            keyframe_no INTEGER NOT NULL,
            frame_idx INTEGER NOT NULL,
            pts_time_sec REAL NOT NULL,
            fps REAL NOT NULL,
            width INTEGER NOT NULL,
            height INTEGER NOT NULL,
            image_relpath TEXT NOT NULL,
            FOREIGN KEY(video_id) REFERENCES videos(video_id)
        );
        CREATE TABLE detections (
            keyframe_id TEXT NOT NULL,
            rank INTEGER NOT NULL,
            entity TEXT NOT NULL,
            class_mid TEXT NOT NULL,
            class_label INTEGER NOT NULL,
            score REAL NOT NULL,
            ymin REAL NOT NULL,
            xmin REAL NOT NULL,
            ymax REAL NOT NULL,
            xmax REAL NOT NULL,
            FOREIGN KEY(keyframe_id) REFERENCES keyframes(keyframe_id)
        );
        """
    )
    return connection


def video_row(video: RawVideo) -> dict:
    with video.media_file.open("r", encoding="utf-8") as handle:
        media = json.load(handle)
    return {
        "video_id": video.video_id,
        "collection_id": video.collection_id,
        "title": str(media.get("title") or ""),
        "author": str(media.get("author") or ""),
        "channel_id": str(media.get("channel_id") or ""),
        "channel_url": str(media.get("channel_url") or ""),
        "description": str(media.get("description") or ""),
        "keywords_json": json.dumps(media.get("keywords") or [], ensure_ascii=False),
        "duration_sec": int(media.get("length") or 0),
        "publish_date_raw": str(media.get("publish_date") or ""),
        "publish_date_iso": normalize_publish_date(media.get("publish_date") or ""),
        "thumbnail_url": str(media.get("thumbnail_url") or ""),
        "watch_url": str(media.get("watch_url") or ""),
    }


def normalized_detections(
    path: Path,
    keyframe_id: str,
    threshold: float,
) -> tuple[list[dict], int]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    fields = (
        "detection_scores",
        "detection_class_names",
        "detection_class_entities",
        "detection_boxes",
        "detection_class_labels",
    )
    values = [data.get(field) for field in fields]
    if not all(isinstance(value, list) for value in values):
        return [], 1
    if len({len(value) for value in values}) != 1:
        return [], 1

    detections = []
    malformed = 0
    for index, (score, mid, entity, box, label) in enumerate(zip(*values, strict=True), start=1):
        try:
            numeric_score = float(score)
            if numeric_score < threshold:
                continue
            ymin, xmin, ymax, xmax = (float(component) for component in box)
            if not (
                0 <= ymin <= ymax <= 1
                and 0 <= xmin <= xmax <= 1
                and np.isfinite([numeric_score, ymin, xmin, ymax, xmax]).all()
            ):
                raise ValueError("invalid score or bounding box")
            detections.append(
                {
                    "keyframe_id": keyframe_id,
                    "rank": index,
                    "entity": str(entity),
                    "class_mid": str(mid),
                    "class_label": int(label),
                    "score": numeric_score,
                    "ymin": ymin,
                    "xmin": xmin,
                    "ymax": ymax,
                    "xmax": xmax,
                }
            )
        except (TypeError, ValueError):
            malformed += 1
    return detections, malformed


def insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    placeholders = ",".join("?" for _ in columns)
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
        [[row[column] for column in columns] for row in rows],
    )


def artifact_metadata(path: Path) -> dict:
    return {"size_bytes": path.stat().st_size, "sha256": sha256_file(path)}


def build_faiss_index(
    embeddings_path: Path,
    index_path: Path,
    *,
    nlist: int = 512,
    nprobe: int = 32,
) -> dict:
    embeddings = np.load(embeddings_path, mmap_mode="r", allow_pickle=False)
    count, dimension = embeddings.shape
    if dimension != VECTOR_DIMENSION:
        raise ValueError(f"Expected {VECTOR_DIMENSION} dimensions, got {dimension}")
    rng = np.random.default_rng(20260817)
    training_count = min(count, 100_000)
    training_ids = rng.choice(count, size=training_count, replace=False)
    training = np.ascontiguousarray(embeddings[training_ids], dtype=np.float32)
    quantizer = faiss.IndexFlatIP(dimension)
    index = faiss.IndexIVFFlat(quantizer, dimension, nlist, faiss.METRIC_INNER_PRODUCT)
    index.train(training)
    for start in range(0, count, 10_000):
        stop = min(count, start + 10_000)
        vectors = np.ascontiguousarray(embeddings[start:stop], dtype=np.float32)
        ids = np.arange(start, stop, dtype=np.int64)
        index.add_with_ids(vectors, ids)
    index.nprobe = min(nprobe, nlist)
    faiss.write_index(index, str(index_path))

    sample_count = min(count, 100)
    sample_ids = rng.choice(count, size=sample_count, replace=False)
    sample = np.ascontiguousarray(embeddings[sample_ids], dtype=np.float32)
    validation_k = min(100, count)
    ann_scores, ann_ids = index.search(sample, validation_k)
    exact = faiss.IndexFlatIP(dimension)
    for start in range(0, count, 10_000):
        stop = min(count, start + 10_000)
        exact.add(np.ascontiguousarray(embeddings[start:stop], dtype=np.float32))
    exact_scores, exact_ids = exact.search(sample, validation_k)
    recalls = np.asarray(
        [
            len(set(ann_row) & set(exact_row)) / validation_k
            for ann_row, exact_row in zip(ann_ids, exact_ids, strict=True)
        ]
    )
    exact_top1_agreement = float(np.mean(ann_ids[:, 0] == exact_ids[:, 0]))
    mean_recall = float(np.mean(recalls))
    if exact_top1_agreement < 0.99 or mean_recall < 0.98:
        raise ValueError(
            "FAISS validation failed: "
            f"exact_top1_agreement={exact_top1_agreement}, "
            f"mean_recall@{validation_k}={mean_recall}"
        )
    return {
        "index_type": "IndexIVFFlat",
        "metric": "inner_product_on_l2_normalized_vectors",
        "dimension": dimension,
        "vector_count": count,
        "nlist": nlist,
        "nprobe": nprobe,
        "training_count": training_count,
        "validation_query_count": sample_count,
        "exact_top1_agreement": exact_top1_agreement,
        f"mean_recall_at_{validation_k}": mean_recall,
        f"minimum_recall_at_{validation_k}": float(np.min(recalls)),
        "maximum_top1_score_error": float(np.max(np.abs(ann_scores[:, 0] - exact_scores[:, 0]))),
    }


def finalize_database(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE INDEX idx_keyframes_video ON keyframes(video_id);
        CREATE INDEX idx_keyframes_collection ON keyframes(collection_id);
        CREATE INDEX idx_detections_keyframe ON detections(keyframe_id);
        CREATE INDEX idx_detections_entity_score ON detections(entity, score);
        CREATE INDEX idx_videos_author ON videos(author);
        CREATE INDEX idx_videos_publish_date ON videos(publish_date_iso);
        ANALYZE;
        """
    )
    connection.commit()


def build_release(
    raw_root: Path,
    output_root: Path,
    *,
    release_id: str,
    detection_threshold: float,
    model_id: str,
    model_revision: str,
    model_validation_report: Path,
    expected_video_count: int,
    expected_keyframe_count: int,
) -> dict:
    if (output_root / "READY.json").exists():
        raise FileExistsError(f"Release is already complete: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    index_root = output_root / "index"
    metadata_root = output_root / "metadata"
    reports_root = output_root / "reports"
    for directory in (index_root, metadata_root, reports_root):
        directory.mkdir(parents=True, exist_ok=True)

    videos = discover_raw_videos(raw_root)
    maps = {video.video_id: read_map(video) for video in videos}
    total_keyframes = sum(len(rows) for rows in maps.values())
    if len(videos) != expected_video_count:
        raise ValueError(f"Found {len(videos)} videos, expected {expected_video_count}")
    if total_keyframes != expected_keyframe_count:
        raise ValueError(f"Found {total_keyframes} keyframes, expected {expected_keyframe_count}")
    with model_validation_report.open("r", encoding="utf-8") as handle:
        model_validation = json.load(handle)
    if not model_validation.get("compatible"):
        raise ValueError("Model validation report does not mark the embeddings compatible")
    if model_validation.get("model_id") != model_id:
        raise ValueError("Model validation report was generated for a different model ID")
    if model_validation.get("model_revision") != model_revision:
        raise ValueError("Model validation report was generated for a different model revision")
    embeddings_path = index_root / "embeddings.f16.npy"
    embeddings_out = np.lib.format.open_memmap(
        embeddings_path,
        mode="w+",
        dtype=np.float16,
        shape=(total_keyframes, VECTOR_DIMENSION),
    )

    sqlite_path = metadata_root / "runtime.sqlite"
    sqlite_path.unlink(missing_ok=True)
    connection = create_runtime_database(sqlite_path)
    video_writer = pq.ParquetWriter(
        metadata_root / "videos.parquet", VIDEO_SCHEMA, compression="zstd"
    )
    keyframe_writer = pq.ParquetWriter(
        metadata_root / "keyframes.parquet", KEYFRAME_SCHEMA, compression="zstd"
    )
    detection_writer = pq.ParquetWriter(
        metadata_root / "detections.parquet", DETECTION_SCHEMA, compression="zstd"
    )
    upload_map_path = output_root / "upload-map.jsonl"
    vector_id = 0
    detection_count = 0
    malformed_detection_count = 0
    max_time_error = 0.0
    minimum_vector_norm = float("inf")
    maximum_vector_norm = 0.0
    try:
        with upload_map_path.open("w", encoding="utf-8") as upload_map:
            for video_index, video in enumerate(videos, start=1):
                current_video = video_row(video)
                parquet_write(video_writer, [current_video], VIDEO_SCHEMA)
                insert_rows(connection, "videos", [current_video])
                rows = maps[video.video_id]
                vectors = np.load(video.feature_file, mmap_mode="r", allow_pickle=False)
                if vectors.shape != (len(rows), VECTOR_DIMENSION):
                    raise ValueError(
                        f"Embedding shape mismatch for {video.video_id}: {vectors.shape}"
                    )
                float_vectors = np.asarray(vectors, dtype=np.float32)
                if not np.isfinite(float_vectors).all():
                    raise ValueError(f"Non-finite embeddings for {video.video_id}")
                vector_norms = np.linalg.norm(float_vectors, axis=1)
                minimum_vector_norm = min(minimum_vector_norm, float(vector_norms.min()))
                maximum_vector_norm = max(maximum_vector_norm, float(vector_norms.max()))
                if not np.allclose(vector_norms, 1.0, atol=2e-3):
                    raise ValueError(f"Embeddings are not L2-normalized for {video.video_id}")
                image_names = sorted(path.name for path in video.image_dir.glob("*.jpg"))
                expected_names = [f"{int(row['n']):03d}.jpg" for row in rows]
                object_names = sorted(
                    path.stem + ".jpg" for path in video.object_dir.glob("*.json")
                )
                if image_names != expected_names or object_names != expected_names:
                    raise ValueError(f"Image/map/object names disagree for {video.video_id}")

                keyframe_rows = []
                detection_rows = []
                for local_index, row in enumerate(rows):
                    keyframe_no = int(row["n"])
                    image_name = f"{keyframe_no:03d}.jpg"
                    image_path = video.image_dir / image_name
                    with Image.open(image_path) as image:
                        width, height = image.size
                    keyframe_id = f"{video.video_id}_{keyframe_no:03d}"
                    image_relpath = f"keyframes/{video.collection_id}/{video.video_id}/{image_name}"
                    pts_time = float(row["pts_time"])
                    fps = float(row["fps"])
                    frame_idx = int(row["frame_idx"])
                    if fps:
                        max_time_error = max(max_time_error, abs(pts_time - frame_idx / fps))
                    keyframe_rows.append(
                        {
                            "vector_id": vector_id,
                            "keyframe_id": keyframe_id,
                            "video_id": video.video_id,
                            "collection_id": video.collection_id,
                            "keyframe_no": keyframe_no,
                            "frame_idx": frame_idx,
                            "pts_time_sec": pts_time,
                            "fps": fps,
                            "width": width,
                            "height": height,
                            "image_relpath": image_relpath,
                        }
                    )
                    current_detections, malformed = normalized_detections(
                        video.object_dir / f"{keyframe_no:03d}.json",
                        keyframe_id,
                        detection_threshold,
                    )
                    detection_rows.extend(current_detections)
                    detection_count += len(current_detections)
                    malformed_detection_count += malformed
                    embeddings_out[vector_id] = vectors[local_index]
                    upload_map.write(
                        json.dumps(
                            {
                                "local_path": str(image_path),
                                "remote_path": image_relpath,
                            }
                        )
                        + "\n"
                    )
                    vector_id += 1

                parquet_write(keyframe_writer, keyframe_rows, KEYFRAME_SCHEMA)
                parquet_write(detection_writer, detection_rows, DETECTION_SCHEMA)
                insert_rows(connection, "keyframes", keyframe_rows)
                insert_rows(connection, "detections", detection_rows)
                connection.commit()
                print(
                    f"Prepared {video_index}/{len(videos)} videos | "
                    f"keyframes={vector_id} detections={detection_count}",
                    flush=True,
                )
    except Exception:
        connection.close()
        raise
    finally:
        video_writer.close()
        keyframe_writer.close()
        detection_writer.close()
        embeddings_out.flush()

    if vector_id != total_keyframes:
        connection.close()
        raise ValueError(f"Built {vector_id} keyframes, expected {total_keyframes}")
    finalize_database(connection)
    connection.close()

    index_path = index_root / "keyframes.faiss"
    faiss_metadata = build_faiss_index(embeddings_path, index_path)
    (index_root / "faiss.meta.json").write_text(
        json.dumps(faiss_metadata, indent=2), encoding="utf-8"
    )
    validation = {
        "video_count": len(videos),
        "keyframe_count": vector_id,
        "vector_count": total_keyframes,
        "detection_count": detection_count,
        "malformed_detection_count": malformed_detection_count,
        "max_abs_pts_vs_frame_over_fps": max_time_error,
        "minimum_vector_norm": minimum_vector_norm,
        "maximum_vector_norm": maximum_vector_norm,
        "model_validation": model_validation,
        "faiss": faiss_metadata,
    }
    validation_path = reports_root / "validation.json"
    validation_path.write_text(json.dumps(validation, indent=2), encoding="utf-8")

    artifact_paths = [
        index_path,
        embeddings_path,
        index_root / "faiss.meta.json",
        metadata_root / "videos.parquet",
        metadata_root / "keyframes.parquet",
        metadata_root / "detections.parquet",
        sqlite_path,
        validation_path,
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "release_id": release_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "id": model_id,
            "revision": model_revision,
            "dimension": VECTOR_DIMENSION,
            "normalized": True,
            "storage_dtype": "float16",
        },
        "detection_threshold": detection_threshold,
        "counts": {
            "videos": len(videos),
            "keyframes": vector_id,
            "vectors": total_keyframes,
            "detections": detection_count,
        },
        "artifacts": {
            str(path.relative_to(output_root)): artifact_metadata(path) for path in artifact_paths
        },
    }
    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_root / "READY.json").write_text(
        json.dumps(
            {
                "release_id": release_id,
                "manifest_sha256": sha256_file(manifest_path),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


def iter_sample_images(videos: list[RawVideo], count: int) -> Iterable[tuple[Path, np.ndarray]]:
    positions = np.linspace(0, len(videos) - 1, num=min(count, len(videos)), dtype=int)
    for video_index in positions:
        video = videos[int(video_index)]
        rows = read_map(video)
        local_index = len(rows) // 2
        image_path = video.image_dir / f"{int(rows[local_index]['n']):03d}.jpg"
        vectors = np.load(video.feature_file, mmap_mode="r", allow_pickle=False)
        yield image_path, np.asarray(vectors[local_index], dtype=np.float32)


def validate_model(
    raw_root: Path,
    output_path: Path,
    model_id: str,
    model_revision: str,
    sample_count: int,
) -> dict:
    from clip import CLIPSearcher

    videos = discover_raw_videos(raw_root)
    searcher = CLIPSearcher(model_id=model_id, revision=model_revision)
    similarities = []
    samples = list(iter_sample_images(videos, sample_count))
    for start in range(0, len(samples), 4):
        batch = samples[start : start + 4]
        images = []
        for image_path, _vector in batch:
            with Image.open(image_path) as image:
                images.append(image.convert("RGB").copy())
        generated = searcher.get_image_batch_features(images)
        for generated_vector, (image_path, existing_vector) in zip(generated, batch, strict=True):
            existing_vector /= np.linalg.norm(existing_vector)
            similarity = float(generated_vector @ existing_vector)
            similarities.append({"image": str(image_path), "cosine": similarity})
    values = np.asarray([item["cosine"] for item in similarities])
    report = {
        "model_id": model_id,
        "model_revision": model_revision,
        "sample_count": len(similarities),
        "median_cosine": float(np.median(values)),
        "minimum_cosine": float(np.min(values)),
        "compatible": bool(np.median(values) >= 0.995 and np.min(values) >= 0.98),
        "samples": similarities,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not report["compatible"]:
        raise ValueError(
            "Existing embeddings are not compatible with the requested model: "
            f"median={report['median_cosine']:.6f}, min={report['minimum_cosine']:.6f}"
        )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate-model")
    validate.add_argument("--raw-root", type=Path, required=True)
    validate.add_argument("--output", type=Path, required=True)
    validate.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    validate.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    validate.add_argument("--sample-count", type=int, default=32)
    build = subparsers.add_parser("build")
    build.add_argument("--raw-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--release-id", default="aic25-b1-v1")
    build.add_argument("--detection-threshold", type=float, default=DEFAULT_DETECTION_THRESHOLD)
    build.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    build.add_argument("--model-revision", default=DEFAULT_MODEL_REVISION)
    build.add_argument("--model-validation-report", type=Path, required=True)
    build.add_argument("--expected-video-count", type=int, default=EXPECTED_VIDEO_COUNT)
    build.add_argument("--expected-keyframe-count", type=int, default=EXPECTED_KEYFRAME_COUNT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "validate-model":
        report = validate_model(
            args.raw_root,
            args.output,
            args.model_id,
            args.model_revision,
            args.sample_count,
        )
        print(json.dumps(report, indent=2))
        return
    manifest = build_release(
        args.raw_root,
        args.output,
        release_id=args.release_id,
        detection_threshold=args.detection_threshold,
        model_id=args.model_id,
        model_revision=args.model_revision,
        model_validation_report=args.model_validation_report,
        expected_video_count=args.expected_video_count,
        expected_keyframe_count=args.expected_keyframe_count,
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
