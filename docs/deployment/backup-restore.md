# Backup and Restore Runbook

This service has four important state groups:

- Qdrant vectors and payloads
- MinIO image objects
- Redis queue/job metadata
- Environment secrets and deployment config

## Qdrant

The production compose stack stores Qdrant data in the `qdrant_data` volume.

Minimum backup options:

- snapshot the Docker volume at the host/storage layer;
- or use Qdrant snapshots if exposed in the deployment environment.

Restore validation:

```bash
curl http://localhost:8000/health
```

Check that `points_count` and `indexed_vectors_count` match the expected
collection state.

## MinIO

The production compose stack stores MinIO data in the `minio_data` volume.

Minimum backup options:

- snapshot the Docker volume;
- or use `mc mirror` to copy the bucket to another object store or disk path.

Restore validation:

- open MinIO console;
- verify bucket exists;
- run one search request and confirm returned presigned URLs load images.

## Redis

Redis stores queued/running/completed job metadata. It is configured with AOF in
`docker-compose.prod.yml`.

Redis is operational state, not the source of truth for vectors/images. If Redis
is lost:

- queued/running job status is lost;
- completed vectors/images remain in Qdrant and MinIO;
- re-enqueue indexing to reconcile state.

## Secrets and Env

Back up `.env.production` securely outside Git.

Required secrets/config:

- `API_KEY`
- MinIO root and app credentials
- Qdrant URL/API key if remote secured Qdrant is used
- deployment host paths and volume locations

## Restore Checklist

1. Restore `.env.production`.
2. Restore Qdrant volume/snapshot.
3. Restore MinIO volume/bucket.
4. Restore Redis only if preserving queued job state matters.
5. Start stack with `make prod-up`.
6. Verify `/health`.
7. Verify `/metrics`.
8. Run one text search.
9. Enqueue one small indexing job and verify completion.
