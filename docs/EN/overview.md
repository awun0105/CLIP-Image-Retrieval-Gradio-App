# Project Overview

CLIP Fashion-Products Image Retrieval Engine is a multimodal retrieval service
for fashion product catalogs. It lets users search a collection by text
description or by reference image.

The project is best described as:

> A production-oriented MVP visual search engine module for fashion products,
> built with CLIP, FastAPI, Gradio, Qdrant, MinIO, Redis/RQ, and Prometheus.

It can be integrated into a larger system such as:

- an e-commerce catalog;
- a fashion discovery application;
- an internal product search tool;
- a recommendation or visual similarity service.

It is not a full platform by itself. It does not include customer accounts,
admin panels, billing, product inventory management, or multi-tenant access
control.

## Core Capabilities

### Text-To-Image Search

The user sends a text query such as `red dress` or `black leather jacket`.
The system embeds that text using a fine-tuned CLIP model, searches Qdrant for
nearby image vectors, and returns ranked images with scores and presigned MinIO
URLs.

### Image-To-Image Search

The user uploads an image. The system validates the upload, decodes it with
Pillow, embeds the image using CLIP, searches Qdrant, and returns visually
similar catalog images.

### Incremental Indexing

Indexing scans a local folder of images and ingests only files that are new or
changed. The system avoids repeated CLIP work by using:

- file metadata checks (`file_size`, `modified_at`);
- SHA256 content hashes;
- Qdrant payload lookup;
- MinIO object existence checks.

If the vector already exists and the image object still exists in MinIO, the
file is skipped. If Qdrant has the vector but MinIO is missing the object, the
system repairs MinIO without re-encoding the image.

### Background Indexing Jobs

Indexing can take a long time for large catalogs. The production path avoids
long-running HTTP requests:

1. API receives an indexing request.
2. API creates a job and returns `202 Accepted` with `job_id`.
3. Redis/RQ stores the job.
4. A worker process executes indexing in the background.
5. Client polls `GET /api/v1/index/{job_id}` for status and counters.

For local development, the same API can use an in-memory job backend.

### Operability

The service includes minimum production operations features:

- API key authentication for API routes;
- configurable upload limits and image size guardrails;
- `/health` for readiness-style checks;
- `/metrics` for Prometheus;
- structured JSON logs in production;
- Docker production compose stack;
- backup/restore runbooks;
- scheduled ingestion guidance;
- retrieval evaluation and performance benchmark scripts.

## Production-Oriented MVP Meaning

This project is stronger than a simple proof of concept because it includes the
core serving, indexing, storage, background job, monitoring, testing, and
deployment pieces needed to run as a small production service.

It is still an MVP because some enterprise-grade topics are intentionally out of
scope:

- Kubernetes/ECS deployment manifests;
- managed secret storage such as Vault or cloud secret managers;
- centralized log storage such as Loki, ELK, or CloudWatch;
- alert rules and incident escalation;
- GPU-specific production model serving such as Triton/TorchServe;
- multi-tenant authorization;
- a large labeled benchmark dataset with release gates.

For a portfolio project or a single-service MVP, the current implementation is
complete enough to demonstrate production engineering maturity.
