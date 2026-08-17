---
title: Test Text Image Retrieval System With Finetune CLIP
emoji: 🐢
colorFrom: indigo
colorTo: pink
sdk: gradio
sdk_version: 5.35.0
python_version: 3.10.13
app_file: app.py
startup_duration_timeout: 3h
pinned: false
license: mit
models:
  - anhquanlam/clip-finetuned-deepfashion
datasets:
  - anhquanlam/clip-deepfashion-multimodal
---

# CLIP DeepFashion Image Search

Standalone Gradio Space for text-to-image and image-to-image retrieval. It uses
the fine-tuned CLIP model from Hugging Face and keeps the original local artifact
storage from `DeepFashion.zip`.

## Runtime data flow

At startup, `database_utils.py` checks for these artifacts:

```text
DeepFashion/
├── images/
├── captions.json
└── embed_data/
    ├── df.csv
    └── df_image_embeds.npy
```

If they are missing, the app downloads `DeepFashion.zip` from the configured
Hugging Face Dataset, safely extracts it, validates the files, and removes the
ZIP. The archive is approximately 7 GB, so a cold Space start can take several
minutes and temporarily needs space for both the ZIP and extracted files.

Exact search uses vectorized cosine similarity. Optional FAISS search creates a
normalized, versioned local index lazily. The legacy `faiss_clusters.index` is not
used because it does not record whether vectors were normalized.

The main search UI follows the local V2 layout. `Search mode` maps the local
backend to either exact NumPy cosine search or FAISS ANN. `FAISS nprobe` controls
how many IVF clusters are searched and is ignored for Exact mode and flat FAISS
indexes. Dataset reindex controls are available under the collapsed
`Index maintenance` section.

The search callbacks use `@spaces.GPU`, so this repository can run on Hugging
Face ZeroGPU. The decorator is an identity fallback outside Spaces. Search is
allocated up to 120 seconds to cover the first lazy model load. Reindexing is
allocated up to 300 seconds; a full large-dataset rebuild may exceed a free
ZeroGPU quota, so the precomputed dataset index remains the normal deployment
path.

## Configuration

All settings have defaults. A local `.env` file is optional, and real environment
variables or Hugging Face Space Variables override it. See `.env.example` for the
available keys.

`Scan Directory` is restricted to `DEFAULT_IMAGES_PATH`. Reindexing processes
images in batches and commits new artifacts only after a complete successful run.
The Cancel button stops after the current CLIP batch and leaves the previous index
active.

The Space keeps the legacy `/combined_search` Gradio endpoint for existing
clients. The V2 UI uses `/combined_search_v2`, which accepts `search_mode` and
`faiss_nprobe` instead of the legacy FAISS checkbox.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
pytest
python app.py
```

The app listens on `0.0.0.0:7860` unless `PORT` is set.

## Deploy

Treat this directory as the root of the Hugging Face Space repository. Push its
contents with `README.md`, `app.py`, the Python modules, and `requirements.txt` at
repository root. No Qdrant, MinIO, Redis, FastAPI service, or external database is
required.

Select ZeroGPU hardware for a free-tier deployment. The Space imports the
platform-provided `spaces` package before Gradio/Torch and requests a GPU only
while a CLIP search or reindex callback is running.
