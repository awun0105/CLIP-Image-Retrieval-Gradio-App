"""Small shared schemas for the standalone Space."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class SearchResult:
    image_path: str
    score: float
    caption: str | None = None
    filename: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
