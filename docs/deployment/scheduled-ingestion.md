# Scheduled Ingestion

Production ingestion should enqueue jobs through Redis/RQ instead of running
indexing inside the API process.

## One-shot CLI

Set production env vars first:

```bash
export INDEXING_JOB_BACKEND=redis
export REDIS_URL=redis://localhost:6379/0
```

Then enqueue:

```bash
uv run clip-index-enqueue --images-dir /path/to/images
```

The command prints:

- `job_id`
- `status`
- `images_dir`
- `status_url`

## Cron Example

Run every night at 02:00:

```cron
0 2 * * * cd /srv/clip-visual-search && /usr/bin/env bash -lc 'source .env.production && uv run clip-index-enqueue --images-dir "$LEGACY_IMAGES_PATH" >> logs/indexing.log 2>&1'
```

## systemd Timer

Use systemd when you need standard logs and service supervision.

`/etc/systemd/system/clip-index-enqueue.service`:

```ini
[Unit]
Description=Enqueue CLIP image indexing job

[Service]
Type=oneshot
WorkingDirectory=/srv/clip-visual-search
EnvironmentFile=/srv/clip-visual-search/.env.production
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

## Operational Notes

- Keep the RQ worker running before scheduling ingestion.
- The API rejects a second queued/running indexing job.
- If a job fails, inspect worker logs and re-enqueue after fixing the cause.
