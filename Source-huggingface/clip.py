"""CLIP ViT-B/32 feature extraction for the standalone Space."""

from __future__ import annotations

import logging
from threading import Lock
from typing import Any, cast

import numpy as np
import torch
from transformers import CLIPModel, CLIPProcessor, CLIPTokenizer

logger = logging.getLogger(__name__)

DEFAULT_MODEL_ID = "openai/clip-vit-base-patch32"
DEFAULT_MODEL_REVISION = "3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268"


def _as_tensor(output: Any) -> torch.Tensor:
    if isinstance(output, torch.Tensor):
        return output
    pooled = getattr(output, "pooler_output", None)
    if isinstance(pooled, torch.Tensor):
        return pooled
    raise TypeError(
        f"Unexpected CLIP output type {type(output).__name__}; "
        "expected torch.Tensor or an object with pooler_output."
    )


def _normalize(vectors: np.ndarray) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0):
        raise ValueError("CLIP returned a zero-magnitude embedding")
    return np.ascontiguousarray(matrix / norms, dtype=np.float32)


def _tokenizer_max_length(tokenizer: CLIPTokenizer) -> int:
    max_length = getattr(tokenizer, "model_max_length", None)
    return max_length if isinstance(max_length, int) and 0 < max_length < 100_000 else 77


class CLIPSearcher:
    """Lazy CLIP text and image encoder using one compatible model."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        revision: str = DEFAULT_MODEL_REVISION,
        device: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self._device = device
        self._model: CLIPModel | None = None
        self._tokenizer: CLIPTokenizer | None = None
        self._processor: CLIPProcessor | None = None
        self._load_lock = Lock()

    @property
    def device(self) -> str:
        return self._device or ("cuda" if torch.cuda.is_available() else "cpu")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        """Place the model on its target device before ZeroGPU callbacks run."""
        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            logger.info("Loading CLIP model %s on %s", self.model_id, self.device)
            model_cls = cast(Any, CLIPModel)
            model = cast(
                Any,
                model_cls.from_pretrained(self.model_id, revision=self.revision),
            )
            model.to(self.device)
            model.eval()
            self._model = cast(CLIPModel, model)
            self._tokenizer = CLIPTokenizer.from_pretrained(
                self.model_id,
                revision=self.revision,
            )
            self._processor = CLIPProcessor.from_pretrained(
                self.model_id,
                revision=self.revision,
            )

    @torch.no_grad()
    def get_text_features(self, text: str) -> np.ndarray:
        self._ensure_loaded()
        assert self._tokenizer is not None and self._model is not None
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=_tokenizer_max_length(self._tokenizer),
        ).to(self.device)
        output = _as_tensor(self._model.get_text_features(**inputs)).detach().cpu().numpy()
        return _normalize(output)

    @torch.no_grad()
    def get_image_batch_features(self, images: list[Any]) -> np.ndarray:
        if not images:
            return np.empty((0, 512), dtype=np.float32)
        self._ensure_loaded()
        assert self._processor is not None and self._model is not None
        inputs = self._processor(images=images, return_tensors="pt").to(self.device)
        output = _as_tensor(self._model.get_image_features(**inputs)).detach().cpu().numpy()
        return _normalize(output)

    def get_image_features(self, image: Any) -> np.ndarray:
        return self.get_image_batch_features([image])
