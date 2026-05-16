"""Evaluate retrieval quality against a JSONL query set.

Input JSONL format:
{"id": "q1", "query": "red dress", "relevant": ["images/red_dress.jpg"]}
"""

from __future__ import annotations

import argparse
import json
import math
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


@dataclass
class QueryCase:
    id: str
    query: str
    relevant: set[str]


def recall_at_k(results: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(results[:k]) & relevant) / len(relevant)


def precision_at_k(results: list[str], relevant: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    return len(set(results[:k]) & relevant) / k


def average_precision_at_k(results: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    score = 0.0
    hits = 0
    for index, image_path in enumerate(results[:k], start=1):
        if image_path in relevant:
            hits += 1
            score += hits / index
    return score / min(len(relevant), k)


def ndcg_at_k(results: list[str], relevant: set[str], k: int) -> float:
    dcg = 0.0
    for index, image_path in enumerate(results[:k], start=1):
        if image_path in relevant:
            dcg += 1.0 / math.log2(index + 1)
    ideal_hits = min(len(relevant), k)
    if ideal_hits == 0:
        return 0.0
    ideal = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / ideal


def aggregate_metrics(cases: Iterable[tuple[QueryCase, list[str]]], k: int) -> dict[str, float]:
    rows = list(cases)
    if not rows:
        return {"queries": 0, "recall_at_k": 0.0, "precision_at_k": 0.0, "map_at_k": 0.0, "ndcg_at_k": 0.0}
    return {
        "queries": float(len(rows)),
        "recall_at_k": sum(recall_at_k(results, case.relevant, k) for case, results in rows)
        / len(rows),
        "precision_at_k": sum(precision_at_k(results, case.relevant, k) for case, results in rows)
        / len(rows),
        "map_at_k": sum(average_precision_at_k(results, case.relevant, k) for case, results in rows)
        / len(rows),
        "ndcg_at_k": sum(ndcg_at_k(results, case.relevant, k) for case, results in rows)
        / len(rows),
    }


def load_query_cases(path: str) -> list[QueryCase]:
    cases: list[QueryCase] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            data = json.loads(line)
            cases.append(
                QueryCase(
                    id=str(data["id"]),
                    query=str(data["query"]),
                    relevant={str(item) for item in data["relevant"]},
                )
            )
    return cases


def search_text(
    base_url: str,
    query: str,
    top_k: int,
    search_mode: str,
    hnsw_ef: int | None,
    api_key: str | None,
) -> list[str]:
    payload: dict[str, Any] = {"query": query, "top_k": top_k, "search_mode": search_mode}
    if hnsw_ef is not None:
        payload["hnsw_ef"] = hnsw_ef
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/v1/search/text",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Search failed for query={query!r}: HTTP {exc.code}") from exc
    return [item["image_path"] for item in data["results"]]


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate text-to-image retrieval quality.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--queries", required=True, help="JSONL query set path.")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--search-mode", choices=["ann", "exact", "ann_indexed_only"], default="ann")
    parser.add_argument("--hnsw-ef", type=int, default=None)
    parser.add_argument("--api-key", default=None)
    args = parser.parse_args()

    cases = load_query_cases(args.queries)
    evaluated = [
        (
            case,
            search_text(
                args.base_url,
                case.query,
                args.top_k,
                args.search_mode,
                args.hnsw_ef,
                args.api_key,
            ),
        )
        for case in cases
    ]
    print(json.dumps(aggregate_metrics(evaluated, args.top_k), indent=2))


if __name__ == "__main__":
    main()
