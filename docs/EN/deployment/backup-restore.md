# Backup And Restore Runbook

The service has four state groups:

| State | Source of truth? | Notes |
|---|---:|---|
| Qdrant vectors and payloads | Yes | Search index and metadata. |
| MinIO image objects | Yes | Actual image files. |
| Redis queue/job metadata | No | Operational job state only. |
| `.env.production` | Yes | Secrets and deployment configuration. |

Back up Qdrant, MinIO, and `.env.production`. Redis is useful to preserve
queued/running job state, but it is not the source of truth for retrieval.

## Qdrant

Production compose stores Qdrant data in the `qdrant_data` volume.

Minimum backup options:

- snapshot the Docker volume at host/storage level;
- use Qdrant snapshots if exposed in your deployment;
- back up before migrations or large indexing changes.

Restore validation:

```bash
curl http://localhost:8000/health
```

Check:

- collection exists;
- `points_count` is close to expected;
- search returns results for known queries.

## MinIO

Production compose stores MinIO data in the `minio_data` volume.

Minimum backup options:

- snapshot the Docker volume;
- use `mc mirror` to copy the bucket to disk or another object store;
- back up bucket configuration and credentials.

Restore validation:

1. Open MinIO Console.
2. Verify the bucket exists.
3. Verify expected object keys exist, for example `images/example.jpg`.
4. Run one search request.
5. Open returned `image_url` and confirm the image loads.

## Redis

Redis stores queue and job metadata. In `docker-compose.prod.yml`, Redis uses
AOF persistence.

If Redis is lost:

- queued/running job status is lost;
- completed vectors remain in Qdrant;
- image objects remain in MinIO;
- re-enqueue indexing to reconcile state.

This is recoverable because indexing is idempotent and incremental.

## Secrets And Env

Back up `.env.production` securely outside Git.

Important values:

- `API_KEY`
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `QDRANT_API_KEY` if secured remote Qdrant is used
- data paths and volume locations

Do not store production secrets in the repository.

## Backup Frequency

Suggested minimum:

- Qdrant: after large ingestion jobs and before deployment changes.
- MinIO: daily or aligned with product image update frequency.
- `.env.production`: after every secret/config change.
- Redis: optional unless preserving queued job state matters.

## Restore Checklist

1. Stop the stack.
2. Restore `.env.production`.
3. Restore Qdrant volume/snapshot.
4. Restore MinIO volume/bucket.
5. Restore Redis only if preserving queued job state matters.
6. Start stack with `make prod-up`.
7. Verify `/health`.
8. Verify `/metrics`.
9. Run one text search.
10. Open one returned image URL.
11. Enqueue one small indexing job and verify completion.

## Recovery From Partial Ingestion

If the service crashes during indexing:

- images already uploaded to MinIO remain there;
- vectors already upserted to Qdrant remain there;
- the next indexing run checks metadata/hash and skips or repairs as needed.

This is why indexing flushes in batches and uses deterministic object keys and
Qdrant point ids.
