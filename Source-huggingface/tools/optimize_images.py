"""Create space-efficient display keyframes without changing canonical metadata."""

from __future__ import annotations

import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps


def safe_destination(output_root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe image destination: {relative_path}")
    return output_root.joinpath(*relative.parts)


def _optimize_one(
    row: dict,
    output_root: Path,
    max_edge: int,
    quality: int,
) -> tuple[Path, str, int]:
    source = Path(str(row["local_path"]))
    remote_path = str(row["remote_path"])
    destination = safe_destination(output_root, remote_path)
    if not source.is_file():
        raise FileNotFoundError(f"Source image does not exist: {source}")
    if not destination.is_file() or destination.stat().st_size == 0:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_image = destination.with_suffix(destination.suffix + ".part")
        try:
            with Image.open(source) as opened:
                image = ImageOps.exif_transpose(opened).convert("RGB")
                image.thumbnail(
                    (max_edge, max_edge),
                    resample=Image.Resampling.LANCZOS,
                )
                image.save(
                    temporary_image,
                    format="JPEG",
                    quality=quality,
                    optimize=True,
                )
            temporary_image.replace(destination)
        finally:
            temporary_image.unlink(missing_ok=True)
    return destination, remote_path, destination.stat().st_size


def optimize_images(
    source_map: Path,
    output_root: Path,
    output_map: Path,
    *,
    max_edge: int,
    quality: int,
    workers: int | None = None,
) -> dict:
    if max_edge < 128:
        raise ValueError("max_edge must be at least 128 pixels")
    if quality < 1 or quality > 95:
        raise ValueError("quality must be in [1, 95]")
    output_root.mkdir(parents=True, exist_ok=True)
    output_map.parent.mkdir(parents=True, exist_ok=True)
    temporary_map = output_map.with_suffix(output_map.suffix + ".part")
    workers = workers or min(8, os.cpu_count() or 1)
    if workers < 1:
        raise ValueError("workers must be at least 1")
    count = 0
    total_bytes = 0
    with source_map.open("r", encoding="utf-8") as source_handle:
        with temporary_map.open("w", encoding="utf-8") as output_handle:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                while lines := [next(source_handle, None) for _ in range(1_000)]:
                    lines = [line for line in lines if line is not None and line.strip()]
                    if not lines:
                        break
                    rows = [json.loads(line) for line in lines]
                    results = executor.map(
                        lambda row: _optimize_one(
                            row,
                            output_root,
                            max_edge,
                            quality,
                        ),
                        rows,
                    )
                    for destination, remote_path, size_bytes in results:
                        total_bytes += size_bytes
                        output_handle.write(
                            json.dumps(
                                {
                                    "local_path": str(destination),
                                    "remote_path": remote_path,
                                }
                            )
                            + "\n"
                        )
                        count += 1
                    print(
                        f"Optimized {count} images | size={total_bytes / 1_000_000_000:.2f} GB",
                        flush=True,
                    )
    if count == 0:
        raise ValueError(f"Source upload map is empty: {source_map}")
    temporary_map.replace(output_map)
    report = {
        "image_count": count,
        "total_bytes": total_bytes,
        "max_edge": max_edge,
        "quality": quality,
        "workers": workers,
        "output_root": str(output_root),
        "output_map": str(output_map),
    }
    print(json.dumps(report, indent=2), flush=True)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-map", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output-map", type=Path, required=True)
    parser.add_argument("--max-edge", type=int, default=576)
    parser.add_argument("--quality", type=int, default=80)
    parser.add_argument("--workers", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    optimize_images(
        args.source_map,
        args.output_root,
        args.output_map,
        max_edge=args.max_edge,
        quality=args.quality,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
