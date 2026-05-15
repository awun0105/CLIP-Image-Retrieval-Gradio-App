"""Benchmark background indexing job duration through the public API."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request


def request_json(url: str, method: str = "GET", body: dict | None = None, api_key: str | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    if api_key:
        headers["X-API-Key"] = api_key
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark indexing job duration.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    start = time.perf_counter()
    created = request_json(
        f"{base}/api/v1/index/",
        method="POST",
        body={"images_dir": args.images_dir},
        api_key=args.api_key,
    )
    status_url = f"{base}{created['status_url']}"

    while True:
        status = request_json(status_url, api_key=args.api_key)
        if status["status"] in {"completed", "failed"}:
            break
        time.sleep(args.poll_interval)

    elapsed = time.perf_counter() - start
    status["duration_seconds"] = elapsed
    if status["scanned_count"]:
        status["images_per_minute"] = status["scanned_count"] / elapsed * 60
    else:
        status["images_per_minute"] = 0.0
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
