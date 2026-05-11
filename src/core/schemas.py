"""Internal dataclass schemas shared across the service layer."""

from dataclasses import dataclass


@dataclass
class SearchResult:
    """A single result returned from a similarity search."""

    image_path: str  # MinIO object key (or URL)
    score: float
    caption: str | None = None
    filename: str | None = None


@dataclass
class ImageMeta:
    """Metadata for an image stored in MinIO."""

    object_key: str
    filename: str
    caption: str | None = None
    url: str | None = None


@dataclass
class CollectionInfo:
    """Summary of a Qdrant collection."""

    name: str
    vectors_count: int
    points_count: int
    status: str


@dataclass
class IndexingStats:
    """Counters produced by an indexing run."""

    scanned_count: int = 0
    indexed_count: int = 0
    updated_count: int = 0
    skipped_count: int = 0
    uploaded_only_count: int = 0
    failed_count: int = 0
