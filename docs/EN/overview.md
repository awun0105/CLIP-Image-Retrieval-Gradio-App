# Project Overview

CLIP Fashion-Products Image Retrieval Engine is a multimodal retrieval service
for fashion product catalogs. It lets clients search an indexed image
collection with either text or a reference image.

The service combines:

- a FastAPI HTTP API;
- a Gradio UI mounted at `/ui`;
- a fine-tuned CLIP embedding model;
- Qdrant for vector search;
- MinIO for image object storage;
- Redis/RQ for background indexing jobs;
- Prometheus metrics and structured logs.

## Where This Service Fits

This project is a retrieval service, not a complete commerce platform. In a
larger system, it would usually sit beside product catalog, inventory, user, and
recommendation services.

Typical integrations:

- an e-commerce catalog calls the search API to support visual discovery;
- an internal product tool indexes new product images nightly;
- a recommendation workflow uses image-to-image search to find similar items;
- a QA or merchandising workflow checks whether visually similar products are
  already present in the catalog.

## Capabilities

### Text-To-Image Search

The user sends a text query such as `red dress` or `black leather jacket`.
The system embeds that text using CLIP, searches Qdrant for nearby image
vectors, and returns ranked images with scores and presigned MinIO URLs.

### Image-To-Image Search

The user uploads an image. The system validates the upload, decodes it with
Pillow, embeds the image using CLIP, searches Qdrant, and returns visually
similar catalog images.

### Incremental Indexing

Indexing scans a local folder of images and ingests only files that are new or
changed. The system avoids repeated CLIP work by using:

- file metadata checks (`file_size`, `modified_at`);
- SHA256 content hashes;
- Qdrant payload lookup limited to the fields needed for indexing state;
- MinIO object existence checks.

If the vector already exists and the image object still exists in MinIO, the
file is skipped. If Qdrant has the vector but MinIO is missing the object, the
system repairs MinIO without re-encoding the image.

### Background Indexing Jobs

Indexing can take longer than a normal HTTP request timeout. The service starts
indexing as a job:

1. API receives an indexing request.
2. API creates a job and returns `202 Accepted` with `job_id`.
3. Redis/RQ stores the job in the production stack.
4. A worker process executes indexing in the background.
5. Client polls `GET /api/v1/index/{job_id}` for status and counters.

For local development, the same API can use an in-memory job backend.

### Runtime Operations

The service includes operational interfaces:

- API key authentication for API routes;
- configurable upload limits and image size guardrails;
- `/health` for service checks;
- `/metrics` for Prometheus;
- structured JSON logs;
- Docker production compose stack;
- backup/restore runbooks;
- scheduled ingestion guidance;
- retrieval evaluation and performance benchmark scripts.

## Scope And Boundaries

Included:

- image retrieval API;
- mounted demo/operator UI;
- local and production Docker Compose workflows;
- background indexing worker;
- Qdrant, MinIO, Redis, and Prometheus integration;
- evaluation and benchmark tooling.

Not included:

- user account management;
- product inventory management;
- billing or payments;
- multi-tenant authorization;
- Kubernetes/ECS manifests;
- managed secret storage;
- centralized log aggregation;
- alert rules;
- dedicated GPU model server.
