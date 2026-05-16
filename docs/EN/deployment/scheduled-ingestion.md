# Scheduled Ingestion

Scheduled ingestion means automatically enqueueing indexing jobs when your image
catalog changes.

Use this when:

- new product images are copied into a folder periodically;
- a nightly ingestion job is enough;
- you want to avoid manually clicking the UI or calling the API every time.

The scheduled path should enqueue jobs through Redis/RQ. It should not run
long indexing directly inside an HTTP request or cron process.

## Requirement

Scheduled ingestion requires:

```env
INDEXING_JOB_BACKEND=redis
REDIS_URL=redis://redis:6379/0
```

The RQ worker must be running:

```bash
make prod-up
```

or, outside compose:

```bash
uv run clip-index-worker
```

## One-Shot CLI

From an environment that can reach Redis:

```bash
uv run clip-index-enqueue --images-dir /path/to/images
```

The CLI prints JSON:

```json
{
  "job_id": "...",
  "status": "queued",
  "images_dir": "/path/to/images",
  "status_url": "/api/v1/index/..."
}
```

The CLI intentionally requires `INDEXING_JOB_BACKEND=redis`. If the backend is
`memory`, there is no separate durable queue for a scheduler to use.

If you run the CLI from the host, make sure the environment is exported and
`REDIS_URL` points to a host-reachable Redis endpoint:

```bash
set -a
source .env.production
set +a
REDIS_URL=redis://localhost:6379/0 uv run clip-index-enqueue --images-dir "$LEGACY_IMAGES_PATH"
```

Inside Docker Compose, `REDIS_URL=redis://redis:6379/0` is correct because
`redis` is the service name on the compose network.

## Cron Example

Run every night at 02:00:

```cron
0 2 * * * cd /srv/clip-fashion-product-retrieval && /usr/bin/env bash -lc 'set -a; source .env.production; set +a; uv run clip-index-enqueue --images-dir "$LEGACY_IMAGES_PATH" >> logs/indexing.log 2>&1'
```

Notes:

- Make sure `logs/` exists.
- Make sure the path in `LEGACY_IMAGES_PATH` exists from the scheduler's
  perspective.
- Use `set -a` when sourcing `.env.production`; otherwise the variables may not
  be exported to the `uv run` child process.
- In Docker-only production, prefer running the CLI inside the app image or
  call the API endpoint instead.

## systemd Timer

Use systemd when you want standard service supervision and logs.

`/etc/systemd/system/clip-index-enqueue.service`:

```ini
[Unit]
Description=Enqueue CLIP image indexing job

[Service]
Type=oneshot
WorkingDirectory=/srv/clip-fashion-product-retrieval
EnvironmentFile=/srv/clip-fashion-product-retrieval/.env.production
ExecStart=/usr/bin/uv run clip-index-enqueue --images-dir ${LEGACY_IMAGES_PATH}
```

`/etc/systemd/system/clip-index-enqueue.timer`:

```ini
[Unit]
Description=Nightly CLIP image indexing

[Timer]
OnCalendar=*-*-* 02:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now clip-index-enqueue.timer
```

## API-Based Scheduling Alternative

If the scheduler cannot run Python/uv but can call HTTP:

```bash
curl -X POST http://localhost:8000/api/v1/index/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"images_dir": "/data/images"}'
```

This still enqueues a Redis/RQ job when production config is used.

The API-based path requires the image directory to exist from the API
container's perspective. For bind-mounted deployments, that usually means the
container path, not the host-only path.

## Failure Handling

### Job Already Running

The API/backend rejects a second queued/running job. This protects the system
from concurrent ingestion overload.

Action: wait for the current job to complete, or inspect the failed/running job
before re-enqueueing.

### Job Failed

Inspect:

- worker logs;
- `GET /api/v1/index/{job_id}`;
- MinIO availability;
- Qdrant availability;
- image folder path from the worker/container perspective.

After fixing the cause, re-enqueue the job. Incremental indexing will skip
unchanged files and repair missing MinIO objects when possible.
