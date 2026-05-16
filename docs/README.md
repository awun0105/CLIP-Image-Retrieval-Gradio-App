# Documentation Map

This folder is organized by language.

```text
docs/
├── README.md        # You are here
├── EN/              # Current complete documentation
├── VN/              # Vietnamese documentation placeholder for a later pass
└── plans/           # Planning/internal notes, not the main user docs
```

## Language Notice

- **English**: use [EN/README.md](EN/README.md). This is the current
  authoritative documentation set for the V3 codebase.
- **Vietnamese**: use [VN/README.md](VN/README.md). The Vietnamese version is
  intentionally not completed yet.
- **Plans**: `docs/plans/` contains implementation planning notes. They may be
  useful for project history, but they are not the source of truth for how to
  run or operate the current system.

## Recommended Reading Paths

### New User / Recruiter

1. [Project overview](EN/overview.md)
2. [Architecture](EN/architecture.md)
3. [Data flows](EN/data-flow.md)
4. [Evaluation](EN/evaluation.md)

### Developer

1. [Local development](EN/local-development.md)
2. [Configuration](EN/configuration.md)
3. [API reference](EN/api.md)
4. [Maintenance scripts](EN/scripts.md)
5. [Architecture](EN/architecture.md)
6. [Data flows](EN/data-flow.md)

### Operator / Deployment

1. [Configuration](EN/configuration.md)
2. [Production deployment](EN/deployment/production.md)
3. [Operations](EN/operations.md)
4. [Scheduled ingestion](EN/deployment/scheduled-ingestion.md)
5. [Backup and restore](EN/deployment/backup-restore.md)

### Evaluation / Benchmarking

1. [Evaluation](EN/evaluation.md)
2. [API reference](EN/api.md)
3. [Operations](EN/operations.md)

## Question Index

| Question | Read |
|---|---|
| What is this project? | [EN/overview.md](EN/overview.md) |
| Is this a complete product or a service/module? | [EN/overview.md](EN/overview.md) |
| How does the architecture work? | [EN/architecture.md](EN/architecture.md) |
| Why Qdrant and MinIO? | [EN/architecture.md](EN/architecture.md) |
| Why Redis/RQ jobs? | [EN/architecture.md](EN/architecture.md), [EN/data-flow.md](EN/data-flow.md) |
| How does text search work? | [EN/data-flow.md](EN/data-flow.md), [EN/api.md](EN/api.md) |
| How does image search work? | [EN/data-flow.md](EN/data-flow.md), [EN/api.md](EN/api.md) |
| How does incremental indexing work? | [EN/architecture.md](EN/architecture.md), [EN/data-flow.md](EN/data-flow.md) |
| What are the scripts in `scripts/` for? | [EN/scripts.md](EN/scripts.md) |
| Which `.env` file should I use? | [EN/configuration.md](EN/configuration.md) |
| Where do API keys and MinIO keys come from? | [EN/configuration.md](EN/configuration.md) |
| How do I run locally? | [EN/local-development.md](EN/local-development.md) |
| How do I run like production or on a VPS? | [EN/deployment/production.md](EN/deployment/production.md) |
| How do I automate ingestion? | [EN/deployment/scheduled-ingestion.md](EN/deployment/scheduled-ingestion.md) |
| How do I evaluate retrieval quality? | [EN/evaluation.md](EN/evaluation.md) |
| How do I monitor the service? | [EN/operations.md](EN/operations.md) |
| How do I back up and restore state? | [EN/deployment/backup-restore.md](EN/deployment/backup-restore.md) |
