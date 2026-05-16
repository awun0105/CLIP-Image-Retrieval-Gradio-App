"""CLI entrypoint to enqueue an indexing job."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from api.dependencies import get_indexing_job_backend, get_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Enqueue an indexing job.")
    parser.add_argument("--images-dir", required=True, help="Directory containing images to index.")
    args = parser.parse_args()

    settings = get_settings()
    if settings.indexing_job_backend != "redis":
        raise SystemExit("clip-index-enqueue requires INDEXING_JOB_BACKEND=redis")

    job = get_indexing_job_backend().start_indexing_job(Path(args.images_dir))
    print(
        json.dumps(
            {
                "job_id": job.job_id,
                "status": job.status,
                "images_dir": job.images_dir,
                "status_url": f"/api/v1/index/{job.job_id}",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
