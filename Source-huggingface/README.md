---
title: AIoU Keyframe Retrieval
emoji: 🔎
colorFrom: gray
colorTo: green
sdk: gradio
sdk_version: 5.35.0
python_version: 3.10.13
app_file: app.py
startup_duration_timeout: 30m
pinned: false
license: mit
models:
  - openai/clip-vit-base-patch32
  - Helsinki-NLP/opus-mt-vi-en
preload_from_hub:
  - "openai/clip-vit-base-patch32 config.json,merges.txt,preprocessor_config.json,pytorch_model.bin,special_tokens_map.json,tokenizer.json,tokenizer_config.json,vocab.json 3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"
  - "Helsinki-NLP/opus-mt-vi-en config.json,generation_config.json,pytorch_model.bin,source.spm,target.spm,tokenizer_config.json,vocab.json c8d2853e77f5fae31124d993e0b35176b1c8914e"
---

# AIoU Keyframe Retrieval

Standalone Hugging Face Space for text-to-keyframe retrieval over AIC 2025 Batch 1.
English queries go directly to CLIP ViT-B/32. Vietnamese queries are translated
locally with MarianMT before CLIP embedding. Metadata and detected objects are strict
pre-search filters; they never alter similarity scores or rerank results.

## Runtime architecture

The Space has no Qdrant, MinIO, Redis, or indexing worker. A Hugging Face Bucket is
mounted read-only at `/data`, and startup validates an immutable release before loading:

```text
/data/releases/aic25-b1-v1/
├── keyframes/<collection>/<video_id>/<keyframe_no>.jpg
├── index/
│   ├── embeddings.f16.npy
│   ├── keyframes.faiss
│   └── faiss.meta.json
├── metadata/
│   ├── videos.parquet
│   ├── keyframes.parquet
│   ├── detections.parquet
│   └── runtime.sqlite
├── reports/validation.json
├── manifest.json
└── READY.json
```

FAISS IVF-Flat performs the default ANN search using inner product over normalized CLIP
vectors, which is cosine similarity. When filters are active, SQLite selects eligible
vector IDs first and NumPy computes exact cosine similarity only over that subset. The UI
returns at most 100 results and displays 20 per page. Selecting a keyframe shows video ID,
keyframe ID, frame index, timestamp, FPS, resolution, source metadata, and detections.

At startup the FAISS index, float16 embedding matrix, and SQLite database are copied from
the read-only mount to `/tmp/aiou-cache` after SHA-256 verification. Images stay in the
mounted Bucket and are not duplicated.

## Configuration

Defaults target the production release. Hugging Face Space Variables or a local `.env`
can override them; see `.env.example`.

The pinned model revisions are part of the release contract. Do not change `MODEL_ID` or
`MODEL_REVISION` without rebuilding or explicitly validating the stored embeddings.

## Run locally from Hugging Face

Use this flow when sharing the app with a teammate. They need the Space source and the
processed release from the Hugging Face Bucket. They do not need the raw dataset.

Install the Hugging Face CLI and sign in if the Space or Bucket is private:

```bash
curl -LsSf https://hf.co/cli/install.sh | bash -s
hf auth login
```

Download the Space source:

```bash
mkdir -p ~/aiou-local
cd ~/aiou-local

hf download 1thesudden/aiou-app \
  --type space \
  --local-dir aiou-app
```

Download the processed release data from the Bucket:

```bash
hf buckets sync \
  hf://buckets/1thesudden/aiou-app-storage/releases/aic25-b1-v1 \
  ./data/aic25-b1-v1
```

The local data directory must contain the complete runtime release:

```text
~/aiou-local/data/aic25-b1-v1/
├── keyframes/
├── index/
│   ├── embeddings.f16.npy
│   ├── keyframes.faiss
│   └── faiss.meta.json
├── metadata/
│   ├── videos.parquet
│   ├── keyframes.parquet
│   ├── detections.parquet
│   └── runtime.sqlite
├── reports/
├── manifest.json
└── READY.json
```

Create a virtual environment and install runtime dependencies:

```bash
cd ~/aiou-local/aiou-app

python3.10 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
```

Configure the local data path in `.env`:

```bash
cp .env.example .env
```

Edit `.env` and set `DATA_ROOT` to the processed release directory:

```env
DATA_ROOT=/home/<your-user>/aiou-local/data/aic25-b1-v1
```

Use an absolute path. Do not leave `~` in `.env`.

Launch Gradio:

```bash
python app.py
```

Open `http://localhost:7860` in the browser. To use another port, either set `PORT`
when launching or add it to `.env`:

```bash
PORT=7861 python app.py
```

The raw dataset is only required for rebuilding a release. Local app runtime only needs
the processed release directory with `keyframes/`, `index/`, `metadata/`, `manifest.json`,
and `READY.json`.

## Build a release

Install build dependencies, validate that the raw vectors came from the configured CLIP
model, then build canonical Parquet, runtime SQLite, and FAISS artifacts:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt

python -m tools.build_release validate-model \
  --raw-root /path/to/raw-dataset \
  --output /path/to/build/model-validation.json

python -m tools.build_release build \
  --raw-root /path/to/raw-dataset \
  --output /path/to/build/aic25-b1-v1 \
  --release-id aic25-b1-v1 \
  --model-validation-report /path/to/build/model-validation.json
```

The builder does not copy images. `upload-map.jsonl` maps each existing raw image to its
release path, so local disk usage is limited to metadata and index artifacts. It validates
the 873-video, 177,321-keyframe contract by default and writes `READY.json` only after all
local checks pass.

Create 576-pixel JPEG display copies before upload. The canonical metadata keeps the
original resolution, while the smaller files are sufficient for the gallery and selected
keyframe panel:

```bash
python -m tools.optimize_images \
  --source-map /path/to/build/aic25-b1-v1/upload-map.jsonl \
  --output-root /path/to/optimized-images \
  --output-map /path/to/optimized-images/upload-map.jsonl
```

## Upload the Bucket

Authenticate with `hf auth login`, then run the resumable uploader. Its local journal is
updated only after each successful batch. It uploads `manifest.json` and then `READY.json`
last, so an interrupted upload cannot look like a complete release.

```bash
python -m tools.upload_release \
  --release-dir /path/to/build/aic25-b1-v1 \
  --bucket-id 1thesudden/aiou-app-storage \
  --upload-map /path/to/optimized-images/upload-map.jsonl \
  --batch-size 1000 \
  --workers 4
```

Mount the Bucket read-only in the Space:

```bash
hf spaces volumes set 1thesudden/aiou-app \
  -v hf://buckets/1thesudden/aiou-app-storage:/data:ro
```

## Local validation

Set `DATA_ROOT` to the built release directory and launch the same monolithic app:

```bash
pytest
DATA_ROOT=/path/to/build/aic25-b1-v1 python app.py
```

The app listens on `0.0.0.0:7860` unless `PORT` is set. The public Gradio API endpoints
are `/search_keyframes` and `/get_keyframe_details`.

## Space deployment

Treat this directory as the Space repository root. Deploy only these source files and the
runtime requirements. ZeroGPU is required by the current Space hardware: `spaces` is
imported before Gradio/Torch and the search callback is decorated with `@spaces.GPU`, while
startup metadata validation remains on CPU.
