"""Application settings loaded from environment variables / .env file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Centralised configuration for the CLIP retrieval service.

    Values are loaded from environment variables; a local ``.env`` file is
    consulted automatically when present.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # CLIP model
    model_id: str = "anhquanlam/clip-finetuned-deepfashion"
    device: str | None = None

    # Qdrant
    qdrant_mode: str = "memory"  # "memory" | "local" | "remote"
    qdrant_path: str = "./qdrant_data"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    qdrant_collection: str = "fashion_images"
    qdrant_hnsw_ef: int = 128
    qdrant_indexing_threshold: int = 5000
    qdrant_full_scan_threshold: int = 5000
    qdrant_upsert_batch_size: int = 100
    search_mode_default: str = "ann"

    # Indexing performance
    ingest_batch_size: int = 32
    minio_upload_workers: int = 8
    index_fast_metadata_skip: bool = True
    index_repair_missing_objects: bool = True
    indexing_job_backend: str = "memory"  # "memory" | "redis"
    redis_url: str = "redis://localhost:6379/0"
    indexing_queue_name: str = "indexing"
    indexing_job_timeout_seconds: int = 3600
    indexing_job_result_ttl_seconds: int = 86400
    indexing_job_failure_ttl_seconds: int = 604800

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "fashion-images"
    minio_secure: bool = False
    minio_public_endpoint: str | None = None
    minio_region: str = "us-east-1"

    # Legacy (migrate)
    legacy_images_path: Path | None = Path("./DeepFashion/images")
    legacy_index_path: Path | None = Path("./DeepFashion/embed_data")
    captions_path: Path | None = Path("./DeepFashion/captions.json")

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    log_format: str = "text"  # "text" | "json"
    enable_metrics: bool = True
    enable_api_key_auth: bool = False
    api_key: str | None = None
    max_upload_bytes: int = 100 * 1024 * 1024
    max_image_pixels: int = 50_000_000
    allowed_image_content_types: str = "image/jpeg,image/png,image/webp"
