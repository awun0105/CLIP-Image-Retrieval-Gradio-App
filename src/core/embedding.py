"""CLIP embedding service with lazy model loading."""

from __future__ import annotations

import logging
from collections.abc import Callable
from threading import Condition, Lock
from typing import Any, TypeVar, cast

import numpy as np
import torch
from transformers import CLIPModel, CLIPProcessor, CLIPTokenizer

from config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _as_tensor(output) -> torch.Tensor:
    """Return the projected feature tensor regardless of transformers version.

    Older transformers releases returned a bare ``torch.Tensor`` from
    ``CLIPModel.get_text_features`` / ``get_image_features``. From v5.x onward
    these methods return a ``BaseModelOutputWithPooling`` whose
    ``pooler_output`` field holds the projected embedding.
    """
    if isinstance(output, torch.Tensor):
        return output
    pooled = getattr(output, "pooler_output", None)
    if pooled is not None:
        return pooled
    raise TypeError(
        f"Unexpected CLIP output type {type(output).__name__}; "
        "expected torch.Tensor or BaseModelOutputWithPooling."
    )


class EmbeddingService:
    """Wrap a HuggingFace CLIP model behind a lazy, side-effect-free API."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._model: CLIPModel | None = None
        self._tokenizer: CLIPTokenizer | None = None
        self._processor: CLIPProcessor | None = None
        self._init_lock = Lock()
        self._inference_gate = Condition()
        self._inference_active = False
        self._foreground_waiting = 0

    @property
    def device(self) -> str:
        return self.settings.device or ("cuda" if torch.cuda.is_available() else "cpu")

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._init_lock:
            if self._model is not None:
                return
            logger.info("Loading CLIP model %s on %s", self.settings.model_id, self.device)
            model_cls = cast(Any, CLIPModel)
            model = cast(Any, model_cls.from_pretrained(self.settings.model_id))
            model.to(self.device)
            model.eval()
            self._model = cast(CLIPModel, model)
            self._tokenizer = CLIPTokenizer.from_pretrained(self.settings.model_id)
            self._processor = CLIPProcessor.from_pretrained(self.settings.model_id)

    def _run_with_inference_gate(self, fn: Callable[[], T], *, foreground: bool) -> T:
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
        assert self._tokenizer is not None and self._model is not None
        tokenizer = self._tokenizer
        model = self._model

        def _infer():
            inputs = tokenizer(text, return_tensors="pt").to(self.device)
            return model.get_text_features(**inputs)

        output = self._run_with_inference_gate(_infer, foreground=True)
        return _as_tensor(output).cpu().numpy()

    @torch.no_grad()
    def get_image_features(self, image) -> np.ndarray:
        self._ensure_loaded()
        assert self._processor is not None and self._model is not None
        processor = self._processor
        model = self._model

        def _infer():
            inputs = processor(images=image, return_tensors="pt").to(self.device)
            return model.get_image_features(**inputs)

        output = self._run_with_inference_gate(_infer, foreground=True)
        return _as_tensor(output).cpu().numpy()

    @torch.no_grad()
    def get_image_batch_features(self, images: list) -> np.ndarray:
        """Encode multiple images in a single CLIP forward pass."""
        if not images:
            return np.empty((0, 512), dtype=np.float32)
        self._ensure_loaded()
        assert self._processor is not None and self._model is not None
        processor = self._processor
        model = self._model

        def _infer():
            inputs = processor(images=images, return_tensors="pt").to(self.device)
            return model.get_image_features(**inputs)

        output = self._run_with_inference_gate(_infer, foreground=False)
        return _as_tensor(output).cpu().numpy()
