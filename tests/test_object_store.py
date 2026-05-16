"""Tests for MinIO object-store helpers."""

from db.object_store import _parse_minio_endpoint


def test_parse_minio_endpoint_with_explicit_https_scheme():
    endpoint, secure = _parse_minio_endpoint("https://cdn.example.com", default_secure=False)

    assert endpoint == "cdn.example.com"
    assert secure is True


def test_parse_minio_endpoint_without_scheme_uses_default_secure():
    endpoint, secure = _parse_minio_endpoint("localhost:9000", default_secure=False)

    assert endpoint == "localhost:9000"
    assert secure is False
