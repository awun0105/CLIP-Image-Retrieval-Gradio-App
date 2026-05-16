# English Documentation

This is the current complete documentation set for the V3 codebase.

Read in this order if you are new to the project:

1. [Overview](overview.md)
2. [Architecture](architecture.md)
3. [Data flows](data-flow.md)
4. [Configuration](configuration.md)
5. [Local development](local-development.md)
6. [Production deployment](deployment/production.md)
7. [API reference](api.md)
8. [Evaluation](evaluation.md)
9. [Operations](operations.md)
10. [Scheduled ingestion](deployment/scheduled-ingestion.md)
11. [Backup and restore](deployment/backup-restore.md)

## Files

| File | Purpose |
|---|---|
| [overview.md](overview.md) | Explains what the service does, where it fits, and what is in or out of scope. |
| [architecture.md](architecture.md) | Explains components, responsibilities, storage choices, queue design, and implementation concepts. |
| [data-flow.md](data-flow.md) | Shows end-to-end flows for startup, search, indexing, health, metrics, and storage shape. |
| [configuration.md](configuration.md) | Explains `.env`, `.env.production`, all important settings, and where credentials come from. |
| [local-development.md](local-development.md) | Step-by-step local setup for coding and debugging. |
| [deployment/production.md](deployment/production.md) | Step-by-step production Docker Compose setup for local production simulation or a VPS. |
| [api.md](api.md) | API endpoints, request/response examples, status codes, and auth behavior. |
| [evaluation.md](evaluation.md) | Included weak-label query set, retrieval quality criteria, benchmark tools, and result template. |
| [operations.md](operations.md) | Health, metrics, logs, job status, and common operational checks. |
| [deployment/scheduled-ingestion.md](deployment/scheduled-ingestion.md) | CLI, cron, and systemd examples for automated indexing. |
| [deployment/backup-restore.md](deployment/backup-restore.md) | What state must be backed up and how to validate restore. |
