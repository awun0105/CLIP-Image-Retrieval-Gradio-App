"""Read-only FAISS index used by the Space runtime."""

from __future__ import annotations

from pathlib import Path
from threading import RLock

import faiss
import numpy as np


class ImageIndexer:
    """Load a prebuilt FAISS index and execute cosine-compatible ANN search."""

    def __init__(self, index_file: str | Path, nprobe: int = 32) -> None:
        self.index_file = Path(index_file)
        if not self.index_file.is_file():
            raise FileNotFoundError(f"FAISS index not found: {self.index_file}")
        self.index = faiss.read_index(str(self.index_file))
        self.nprobe = max(1, int(nprobe))
        self._lock = RLock()
        self._configure_nprobe()

    @property
    def count(self) -> int:
        return int(self.index.ntotal)

    @property
    def dimension(self) -> int:
        return int(self.index.d)

    def _configure_nprobe(self) -> None:
        if hasattr(self.index, "nprobe"):
            nlist = int(getattr(self.index, "nlist", self.nprobe))
            self.index.nprobe = min(self.nprobe, nlist)

    def search(self, query: np.ndarray, top_k: int) -> tuple[np.ndarray, np.ndarray]:
        matrix = np.ascontiguousarray(np.asarray(query, dtype=np.float32).reshape(1, -1))
        if matrix.shape[1] != self.dimension:
            raise ValueError(
                f"Query dimension {matrix.shape[1]} does not match index {self.dimension}"
            )
        top_k = max(1, min(int(top_k), self.count))
        with self._lock:
            scores, ids = self.index.search(matrix, top_k)
        valid = ids[0] >= 0
        return scores[0][valid], ids[0][valid].astype(np.int64, copy=False)
