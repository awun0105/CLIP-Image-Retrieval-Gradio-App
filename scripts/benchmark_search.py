"""Benchmark text search latency through the public API."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def request_search(base_url: str, query: str, top_k: int, api_key: str | None) -> float:
    body = json.dumps({"query": query, "top_k": top_k}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/search/text",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        request.add_header("X-API-Key", api_key)
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=60) as response:
        response.read()
    return time.perf_counter() - start


def percentile(values: list[float], rank: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((rank / 100) * (len(ordered) - 1))))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark text search API latency.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--query", default="red dress")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--requests", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    latencies: list[float] = []
    errors = 0
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(request_search, args.base_url, args.query, args.top_k, args.api_key)
            for _ in range(args.requests)
        ]
        for future in as_completed(futures):
            try:
                latencies.append(future.result())
            except Exception:
                errors += 1

    elapsed = time.perf_counter() - start
    report = {
        "requests": args.requests,
        "errors": errors,
        "throughput_rps": args.requests / elapsed if elapsed else 0.0,
        "p50_ms": percentile(latencies, 50) * 1000,
        "p95_ms": percentile(latencies, 95) * 1000,
        "p99_ms": percentile(latencies, 99) * 1000,
        "mean_ms": statistics.mean(latencies) * 1000 if latencies else 0.0,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
