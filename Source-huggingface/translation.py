"""Local Vietnamese-to-English query preparation."""

from __future__ import annotations

import logging
from collections import OrderedDict
from threading import Lock
from typing import Any

import langid
import torch
from schemas import PreparedQuery
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

logger = logging.getLogger(__name__)

DEFAULT_TRANSLATION_MODEL = "Helsinki-NLP/opus-mt-vi-en"
DEFAULT_TRANSLATION_REVISION = "c8d2853e77f5fae31124d993e0b35176b1c8914e"
SUPPORTED_LANGUAGES = {"auto", "english", "vietnamese"}


class QueryTranslator:
    """Detect query language and translate Vietnamese locally when needed."""

    def __init__(
        self,
        model_id: str = DEFAULT_TRANSLATION_MODEL,
        revision: str = DEFAULT_TRANSLATION_REVISION,
        cache_size: int = 256,
    ) -> None:
        self.model_id = model_id
        self.revision = revision
        self.cache_size = max(1, int(cache_size))
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._load_lock = Lock()
        self._cache_lock = Lock()
        self._cache: OrderedDict[str, str] = OrderedDict()
        langid.set_languages(["en", "vi"])

    @staticmethod
    def normalize_query(query: str) -> str:
        normalized = " ".join(str(query).split())
        if not normalized:
            raise ValueError("Query text cannot be empty")
        return normalized

    def detect_language(self, query: str) -> str:
        language, _score = langid.classify(query)
        return "vietnamese" if language == "vi" else "english"

    def prepare(self, query: str, requested_language: str = "auto") -> PreparedQuery:
        normalized = self.normalize_query(query)
        requested = str(requested_language or "auto").strip().lower()
        if requested not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Unsupported query language: {requested_language}")
        detected = self.detect_language(normalized) if requested == "auto" else requested
        if detected == "english":
            return PreparedQuery(normalized, normalized, requested, detected)

        try:
            translated = self.translate(normalized)
        except Exception as exc:
            logger.exception("Vietnamese query translation failed")
            return PreparedQuery(
                normalized,
                normalized,
                requested,
                detected,
                warning=f"Translation unavailable: {exc}",
            )
        return PreparedQuery(normalized, translated, requested, detected, translated=True)

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            logger.info("Loading translation model %s on CPU", self.model_id)
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                revision=self.revision,
            )
            self._model = AutoModelForSeq2SeqLM.from_pretrained(
                self.model_id,
                revision=self.revision,
            ).to("cpu")
            self._model.eval()

    @torch.no_grad()
    def translate(self, query: str) -> str:
        with self._cache_lock:
            cached = self._cache.get(query)
            if cached is not None:
                self._cache.move_to_end(query)
                return cached

        self._ensure_loaded()
        assert self._tokenizer is not None and self._model is not None
        inputs = self._tokenizer(
            query,
            return_tensors="pt",
            truncation=True,
            max_length=128,
        )
        output = self._model.generate(**inputs, max_length=128, num_beams=4)
        translated = self._tokenizer.batch_decode(output, skip_special_tokens=True)[0].strip()
        if not translated:
            raise ValueError("Translation model returned an empty query")

        with self._cache_lock:
            self._cache[query] = translated
            self._cache.move_to_end(query)
            while len(self._cache) > self.cache_size:
                self._cache.popitem(last=False)
        return translated
