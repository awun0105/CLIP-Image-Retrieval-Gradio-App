"""CLIP embedding service used by the standalone Hugging Face Space."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Condition, Lock
from typing import Any, TypeVar, cast

import numpy as np
import torch
from transformers import CLIPModel, CLIPProcessor, CLIPTokenizer

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _as_tensor(output: Any) -> torch.Tensor:
    """Extract projected CLIP features across transformers versions."""
    if isinstance(output, torch.Tensor):
        return output
    pooled = getattr(output, "pooler_output", None)
    if isinstance(pooled, torch.Tensor):
        return pooled
    raise TypeError(
        f"Unexpected CLIP output type {type(output).__name__}; "
        "expected torch.Tensor or an object with pooler_output."
    )


def _tokenizer_max_length(tokenizer: CLIPTokenizer) -> int:
    max_length = getattr(tokenizer, "model_max_length", None)
    if isinstance(max_length, int) and 0 < max_length < 100_000:
        return max_length
    return 77


class CLIPSearcher:
    """Lazy, thread-safe CLIP feature extractor for search and reindexing."""

    def __init__(
        self,
        model_id: str = "anhquanlam/clip-finetuned-deepfashion",
        device: str | None = None,
    ) -> None:
        self.model_id = model_id
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model: CLIPModel | None = None
        self._tokenizer: CLIPTokenizer | None = None
        self._processor: CLIPProcessor | None = None
        self._init_lock = Lock()
        self._inference_gate = Condition()
        self._inference_active = False
        self._foreground_waiting = 0

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._init_lock:
            if self._model is not None:
                return
            logger.info("Loading CLIP model %s on %s", self.model_id, self.device)
            model_cls = cast(Any, CLIPModel)
            model = cast(Any, model_cls.from_pretrained(self.model_id))
            model.to(self.device)
            model.eval()
            self._model = cast(CLIPModel, model)
            self._tokenizer = CLIPTokenizer.from_pretrained(self.model_id)
            self._processor = CLIPProcessor.from_pretrained(self.model_id)

    def _run_inference(self, fn: Callable[[], T], *, foreground: bool) -> T:
        with self._inference_gate:
            if foreground:
                self._foreground_waiting += 1
            try:
                while self._inference_active or (not foreground and self._foreground_waiting > 0):
                    self._inference_gate.wait()
                self._inference_active = True
            finally:
                if foreground:
                    self._foreground_waiting -= 1
        try:
            return fn()
        finally:
            with self._inference_gate:
                self._inference_active = False
                self._inference_gate.notify_all()

    @torch.no_grad()
    def get_text_features(self, text: str) -> np.ndarray:
        self._ensure_loaded()
        assert self._model is not None and self._tokenizer is not None
        model = self._model
        tokenizer = self._tokenizer

        def infer():
            inputs = tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=_tokenizer_max_length(tokenizer),
            ).to(self.device)
            return model.get_text_features(**inputs)

        output = self._run_inference(infer, foreground=True)
        return _as_tensor(output).detach().cpu().numpy().astype(np.float32, copy=False)

    @torch.no_grad()
    def get_image_features(self, image: Any) -> np.ndarray:
        return self.get_image_batch_features([image], foreground=True)

    @torch.no_grad()
    def get_image_batch_features(
        self,
        images: list[Any],
        *,
        foreground: bool = False,
    ) -> np.ndarray:
        if not images:
            return np.empty((0, 512), dtype=np.float32)
        self._ensure_loaded()
        assert self._model is not None and self._processor is not None
        model = self._model
        processor = self._processor

        def infer():
            inputs = processor(images=images, return_tensors="pt").to(self.device)
            return model.get_image_features(**inputs)

        output = self._run_inference(infer, foreground=foreground)
        return _as_tensor(output).detach().cpu().numpy().astype(np.float32, copy=False)
