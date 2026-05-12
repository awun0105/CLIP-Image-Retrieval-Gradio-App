# CLIP Image Retrieval

Multimodal fashion retrieval service. A fine-tuned CLIP model
(`anhquanlam/clip-finetuned-deepfashion`) is exposed through:

- A **FastAPI** REST API (`/api/v1/...`, Swagger at `/docs`).
- A **Gradio** web UI mounted at `/ui`.
- A **Qdrant** vector database for exact cosine and HNSW/ANN similarity search.
- A **MinIO** S3-compatible object store for the image catalogue.

Search by free-text caption ("vintage floral dress with puff sleeves") or by
uploading a reference image — both query types share the same CLIP embedding
space.

## Demo & resources

[![YouTube Project Demo Video](https://img.shields.io/badge/YouTube-Demo_Video-ff0000?logo=youtube)](https://www.youtube.com/watch?v=6h3SuES8a-M)

[![Hugging Face Space](https://img.shields.io/badge/HuggingFace-Space-yellow?logo=huggingface)](https://huggingface.co/spaces/anhquanlam/clip-image-search-app-deepfashion-multimodal)
[![Finetuned Model](https://img.shields.io/badge/HuggingFace-Finetuned_Model-blue?logo=huggingface)](https://huggingface.co/anhquanlam/clip-finetuned-deepfashion)
[![Dataset ZIP](https://img.shields.io/badge/HuggingFace-Dataset-green?logo=huggingface)](https://huggingface.co/datasets/anhquanlam/clip-deepfashion-multimodal/resolve/main/DeepFashion.zip)

## Screenshots

<img width="1919" height="990" alt="image" src="https://github.com/user-attachments/assets/b294222b-1bd7-4b10-bd02-81bee6f878cd" />
<img width="1919" height="989" alt="image" src="https://github.com/user-attachments/assets/39b60ae5-08fb-4797-86f3-23871d39dad7" />
<img width="1917" height="996" alt="image" src="https://github.com/user-attachments/assets/80ebfe3b-0aaf-4a24-919e-e77d90042f36" />

---

## Setup & Run

> The default path uses **Docker Desktop** — one command starts the whole
> stack (CLIP model server + Qdrant + MinIO). No Python, no `uv`, no other
> setup needed. Estimated time: 10–15 minutes including the first-time
> ~3–5 GB download of the model.
>
> Each step also has a **👩‍💻 Developer mode** call-out that shows the
> equivalent native workflow with [`uv`](https://docs.astral.sh/uv/) for
> contributors who want to edit `src/`, run `pytest`, or attach a debugger.

### Step 1 — Install prerequisites

Install these two free programs:

1. **Docker Desktop** — runs the application containers.
   - Download: <https://www.docker.com/products/docker-desktop/>
   - Pick the installer for your operating system (Windows / macOS / Linux),
     run it, and follow the prompts. On Windows it will ask to enable WSL 2;
     accept.
   - After installation, **open Docker Desktop once** so it finishes setup,
     and leave it running in the background. You should see a small whale
     icon in your menu bar / system tray when it is ready.

2. **Git** — downloads the project's source code.
   - Download: <https://git-scm.com/downloads>
   - Run the installer with the default options.

> **👩‍💻 Developer mode** — also install Python ≥ 3.10 and
> [`uv`](https://docs.astral.sh/uv/) (Astral's fast Python package manager).
> Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`
> (macOS / Linux) or `pipx install uv` (any platform).

### Step 2 — Open a terminal

- **Windows:** press the Windows key, type `PowerShell`, press Enter.
- **macOS:** press `Cmd + Space`, type `Terminal`, press Enter.
- **Linux:** open your usual terminal (GNOME Terminal, Konsole, ...).

You will run all the commands below in this window.

### Step 3 — Download the project

Copy / paste these two lines (press Enter after each):

```bash
git clone https://github.com/percylam0105/CLIP-Image-Retrieval-Gradio-App.git
cd CLIP-Image-Retrieval-Gradio-App
```

This creates a folder named `CLIP-Image-Retrieval-Gradio-App` and moves you
inside it.

> **👩‍💻 Developer mode** — same step. Optionally copy the env template
> with `cp .env.example .env` if you want to override defaults (model id,
> Qdrant mode, etc.) — see [Configuration](#configuration).

### Step 4 — Start the application

One command. The first run builds the application image and downloads the
CLIP model (~3–5 GB, ~5 minutes); subsequent runs start in seconds.

```bash
docker compose up -d --build
```

While you wait, you'll see lines like `=> [internal] load build context` and
`Pulling qdrant`. When the prompt comes back the stack is up.

Check that everything is running:

```bash
docker compose ps
```

You should see three lines: `app`, `qdrant`, `minio`, all with status `Up`.

> **Tip:** if you have `make` installed (macOS / Linux usually do; on Windows
> install via [Chocolatey](https://chocolatey.org/) or skip it), you can use
> the shorter `make docker-up`.

> **👩‍💻 Developer mode** — run the app natively on your host so code edits
> take effect on restart without rebuilding the image. You still need Qdrant
> + MinIO running for the full feature set:
> ```bash
> docker compose up -d qdrant minio   # sidecar services only
> uv sync                              # creates .venv, installs deps + dev tools
> uv run clip-retrieval                # starts FastAPI on :8000 with Gradio at /ui
> ```
> Or with the in-memory Qdrant (no MinIO upload / persistence):
> set `QDRANT_MODE=memory` in `.env`, skip the `docker compose` line.

### Step 5 — Open the app

Open your web browser and visit:

| What you'll see | URL |
|---|---|
| 🖼 The search interface (Gradio) | <http://localhost:8000/ui> |
| 📖 The API documentation (Swagger) | <http://localhost:8000/docs> |
| ❤️ Is everything healthy? | <http://localhost:8000/health> |
| 📂 The image storage admin panel (MinIO console) | <http://localhost:9001> *(login `minioadmin` / `minioadmin`)* |

The first time you open `/ui`, the AI model is loaded into memory — this can
take a minute. After that, searches are instant.

> **What if the page doesn't load?** Wait ~30 seconds and refresh. If it
> still doesn't work, see [Troubleshooting](#troubleshooting) below.

### Step 6 — Add your own images (optional)

Out of the box the app has no images indexed yet. To add some:

1. Put your `.jpg` / `.jpeg` / `.png` files into a folder on your computer
   (e.g. `~/my-images`).
2. Tell the app to index them. Replace the path with your actual folder:

   **macOS / Linux:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/index/ \
     -H 'Content-Type: application/json' \
     -d '{"images_dir": "/full/path/to/my-images"}'
   ```

   **Windows PowerShell:**
   ```powershell
   Invoke-RestMethod -Uri http://localhost:8000/api/v1/index/ `
     -Method POST -ContentType 'application/json' `
     -Body '{"images_dir": "C:/full/path/to/my-images"}'
   ```

   **No-terminal alternative:** open <http://localhost:8000/docs>, expand
   `POST /api/v1/index/`, click **Try it out**, edit the JSON, click
   **Execute**.

   The endpoint starts a background indexing job and returns a `job_id`.
   Check progress with:

   ```bash
   curl http://localhost:8000/api/v1/index/<job_id>
   ```

3. Go back to <http://localhost:8000/ui> and search. Your images will now
   appear as results after the job status becomes `completed`.

> **👩‍💻 Developer mode** — if you have a pre-computed embedding dataset
> (`df.csv` + `df_image_embeds.npy` + `captions.json`), use the migration
> scripts instead of re-encoding:
> ```bash
> uv run python scripts/upload_images_to_minio.py   # upload raw images to MinIO
> uv run python scripts/migrate_to_qdrant.py        # upsert precomputed embeddings
> ```
> The scripts read `LEGACY_IMAGES_PATH`, `LEGACY_INDEX_PATH`, and
> `CAPTIONS_PATH` from `.env`.

### Step 7 — Stop the application

```bash
docker compose down
```

Indexed images and embeddings are preserved in Docker volumes — the next
`docker compose up -d` brings everything back.

To **completely wipe** the data (drops volumes):

```bash
docker compose down -v
```

> **👩‍💻 Developer mode** — press `Ctrl + C` in the terminal running
> `uv run clip-retrieval`. Run `docker compose down` separately to stop the
> Qdrant + MinIO sidecars.

### Troubleshooting

| Symptom | Fix |
|---|---|
| `docker: command not found` | Docker Desktop is not installed or not started. Open it from your Applications / Start menu. |
| `Cannot connect to the Docker daemon` | Docker Desktop is installed but not running. Click its icon and wait until it says "Engine running". |
| `port is already allocated` | Another program is using port 8000, 9000, 9001, 6333, or 6334. Either stop the other program or edit `docker-compose.yml` and change the host port (the number on the **left** of `:`). |
| Browser shows "Site can't be reached" | Wait 30 seconds and refresh. The first start has to download the model. Check progress with `docker compose logs -f app`. |
| `out of disk space` / build fails | The model is ~3 GB. Free up ~10 GB of disk space, then re-run the build. |
| Searches return no results | You haven't indexed any images yet. See [Step 6](#step-6--add-your-own-images-optional), or use the Hugging Face dataset (link at the top). |
| `uv: command not found` (developer mode) | `uv` is not installed or not on `PATH`. Reinstall via `curl -LsSf https://astral.sh/uv/install.sh \| sh` and restart your terminal. |

---

## Developer reference

Common commands for contributors. All assume `uv sync` has been run once
to create the `.venv`.

| `make` target | Equivalent | Purpose |
|---|---|---|
| `make dev` | `uv sync` | Install runtime + dev deps into `.venv` |
| `make run` | `uv run clip-retrieval` | Start FastAPI + Gradio on :8000 |
| `make test` | `uv run pytest tests/ -v` | Run the unit-test suite (~3s) |
| `make lint` | `uv run ruff check src/ tests/` | Static lint |
| `make format` | `uv run ruff format src/ tests/` | Auto-format |
| `make lock` | `uv lock` | Regenerate `uv.lock` after editing `pyproject.toml` |
| `make docker-up` / `make docker-down` | `docker compose up -d` / `down` | Full stack via Docker |
| `make migrate` | `uv run python scripts/migrate_to_qdrant.py` | Upsert legacy embeddings |
| `make qdrant-index-config` | `uv run python scripts/update_qdrant_index_config.py` | Apply HNSW/optimizer thresholds |

To apply the configured Qdrant HNSW/optimizer thresholds to an existing
collection without recreating it:

```bash
make qdrant-index-config
```

The test suite uses Qdrant in-memory mode and a MinIO mock, so it requires
no external services.

---

## Repository layout

```
src/
├── api/           # FastAPI factory, dependencies, routes, request/response schemas
├── core/          # EmbeddingService, SearchService, IndexingService, ImageService
├── db/            # Qdrant VectorStore, MinIO ObjectStore, MigrationService
├── ui/            # Gradio Blocks UI factory
├── config.py      # Pydantic Settings (loads from env / .env)
└── server.py      # Entry point — builds app, mounts Gradio, starts uvicorn
docs/
├── architecture.md
├── data-flow.md
└── plans/
scripts/           # Standalone CLIs for one-off migrations
tests/             # pytest suite (Qdrant in-memory, MinIO mock, FastAPI TestClient)
docker-compose.yml # qdrant + minio + app
Dockerfile         # uv-based, multi-layer for fast rebuilds
pyproject.toml     # PEP-621 + uv lockfile (uv.lock)
```

## REST API

| Method | Path | Body | Description |
|---|---|---|---|
| `POST` | `/api/v1/search/text` | `{ "query": str, "top_k": int, "search_mode"?: "ann" \| "exact" \| "ann_indexed_only", "hnsw_ef"?: int }` | Text → top-K image hits with presigned URLs |
| `POST` | `/api/v1/search/image` | multipart `file=@...` + `?top_k=N&search_mode=ann&hnsw_ef=128` | Image → top-K similar images |
| `POST` | `/api/v1/index/` | `{ "images_dir": str? }` | Start a background image indexing job and return `job_id` |
| `GET` | `/api/v1/index/{job_id}` | — | Read indexing job status, counters, errors, and final collection info |
| `GET` | `/health` | — | Model + Qdrant + MinIO health |

Full schemas live in [`docs/architecture.md`](docs/architecture.md) and the
Swagger UI at `/docs`.

## Configuration

All settings come from environment variables (and an optional `.env`). See
[`.env.example`](.env.example) for the full list. Important ones:

| Variable | Default | Notes |
|---|---|---|
| `MODEL_ID` | `anhquanlam/clip-finetuned-deepfashion` | Hugging Face model id |
| `QDRANT_MODE` | `memory` | `memory` / `local` / `remote` |
| `QDRANT_URL` | `http://localhost:6333` | Used when `QDRANT_MODE=remote` |
| `QDRANT_COLLECTION` | `fashion_images` | Qdrant collection name |
| `QDRANT_HNSW_EF` | `128` | ANN search breadth; higher improves recall but costs latency |
| `QDRANT_INDEXING_THRESHOLD` | `5000` | Build vector indexes for smaller Qdrant segments than the default |
| `QDRANT_FULL_SCAN_THRESHOLD` | `5000` | Prefer HNSW over full-scan for more segment searches |
| `SEARCH_MODE_DEFAULT` | `ann` | Default mode: `ann`, `exact`, or `ann_indexed_only` |
| `INGEST_BATCH_SIZE` | `32` | Images encoded/upserted per indexing batch |
| `MINIO_UPLOAD_WORKERS` | `8` | Max concurrent MinIO uploads during indexing |
| `INDEX_FAST_METADATA_SKIP` | `true` | Skip unchanged files using size/mtime before hashing |
| `INDEX_REPAIR_MISSING_OBJECTS` | `true` | Stat MinIO objects for unchanged payloads and re-upload missing files |
| `MINIO_ENDPOINT` | `localhost:9000` | host:port |
| `MINIO_BUCKET` | `fashion-images` | Bucket; auto-created on startup |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | uvicorn bind |
| `LOG_LEVEL` | `INFO` | Logging level |

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for a description of the
service boundaries and module responsibilities, and
[`docs/data-flow.md`](docs/data-flow.md) for Mermaid diagrams of every flow
(startup, text search, image search, indexing, health, migration, UI,
storage shape).
