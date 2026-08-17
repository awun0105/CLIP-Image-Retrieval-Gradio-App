"""Shared schemas for keyframe retrieval and metadata filtering."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class SearchFilters:
    """Optional metadata constraints applied before similarity ranking."""

    collections: tuple[str, ...] = ()
    video_id: str | None = None
    object_entities: tuple[str, ...] = ()
    object_match_mode: str = "any"
    minimum_object_confidence: float = 0.3
    author: str | None = None
    publish_date_from: str | None = None
    publish_date_to: str | None = None

    @property
    def active(self) -> bool:
        return bool(
            self.collections
            or self.video_id
            or self.object_entities
            or self.author
            or self.publish_date_from
            or self.publish_date_to
        )


@dataclass(frozen=True)
class SearchResult:
    """A ranked keyframe returned by embedding similarity search."""

    vector_id: int
    keyframe_id: str
    video_id: str
    collection_id: str
    keyframe_no: int
    image_path: str
    image_relpath: str
    score: float
    pts_time_sec: float
    frame_idx: int
    fps: float
    width: int
    height: int
    title: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PreparedQuery:
    """Original and model-ready forms of a user query."""

    original_query: str
    clip_query: str
    requested_language: str
    detected_language: str
    translated: bool = False
    warning: str | None = None


@dataclass(frozen=True)
class SearchOutcome:
    """Search results together with query diagnostics."""

    results: tuple[SearchResult, ...]
    query: PreparedQuery


@dataclass(frozen=True)
class KeyframeDetails:
    """Complete metadata displayed after selecting a keyframe."""

    keyframe: dict
    video: dict
    detections: tuple[dict, ...] = field(default_factory=tuple)
