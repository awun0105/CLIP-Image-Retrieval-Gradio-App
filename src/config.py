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
    search_mode_default: str = "ann"

    # MinIO
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "fashion-images"
    minio_secure: bool = False

    # Legacy (migrate)
    legacy_images_path: Path | None = Path("./DeepFashion/images")
    legacy_index_path: Path | None = Path("./DeepFashion/embed_data")
    captions_path: Path | None = Path("./DeepFashion/captions.json")

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
