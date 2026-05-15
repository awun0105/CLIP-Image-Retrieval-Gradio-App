"""Tests for retrieval evaluation metrics."""

from __future__ import annotations

from scripts.evaluate_retrieval import (
    QueryCase,
    aggregate_metrics,
    average_precision_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)


def test_retrieval_metrics_at_k():
    results = ["a", "b", "c"]
    relevant = {"a", "c", "x"}

    assert recall_at_k(results, relevant, 3) == 2 / 3
    assert precision_at_k(results, relevant, 2) == 1 / 2
    assert average_precision_at_k(results, relevant, 3) == ((1 / 1) + (2 / 3)) / 3
    assert 0 < ndcg_at_k(results, relevant, 3) <= 1


def test_aggregate_metrics():
    case = QueryCase(id="q1", query="red dress", relevant={"a"})
    metrics = aggregate_metrics([(case, ["a", "b"])], 2)

    assert metrics["queries"] == 1
    assert metrics["recall_at_k"] == 1
    assert metrics["precision_at_k"] == 0.5
    assert metrics["map_at_k"] == 1
    assert metrics["ndcg_at_k"] == 1
