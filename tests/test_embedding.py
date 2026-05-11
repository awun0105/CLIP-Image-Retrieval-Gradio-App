"""Tests for ``EmbeddingService`` lazy-loading semantics."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch
from transformers.modeling_outputs import BaseModelOutputWithPooling

from config import Settings
from core.embedding import EmbeddingService, _as_tensor


def test_embedding_service_not_loaded_at_init():
    service = EmbeddingService(Settings())
    assert service.is_loaded is False


def test_embedding_service_device_resolution_cpu():
    settings = Settings(device="cpu")
    service = EmbeddingService(settings)
    assert service.device == "cpu"


def test_ensure_loaded_calls_transformers_factories():
    settings = Settings(device="cpu")
    service = EmbeddingService(settings)
    with (
        patch("core.embedding.CLIPModel") as MockModel,
        patch("core.embedding.CLIPTokenizer") as MockTok,
        patch("core.embedding.CLIPProcessor") as MockProc,
    ):
        MockModel.from_pretrained.return_value.to.return_value = (
            MockModel.from_pretrained.return_value
        )
        service._ensure_loaded()

        MockModel.from_pretrained.assert_called_once_with(settings.model_id)
        MockTok.from_pretrained.assert_called_once_with(settings.model_id)
        MockProc.from_pretrained.assert_called_once_with(settings.model_id)

    assert service.is_loaded is True


def test_ensure_loaded_is_thread_safe():
    settings = Settings(device="cpu")
    service = EmbeddingService(settings)
    with (
        patch("core.embedding.CLIPModel") as MockModel,
        patch("core.embedding.CLIPTokenizer") as MockTok,
        patch("core.embedding.CLIPProcessor") as MockProc,
    ):
        MockModel.from_pretrained.return_value.to.return_value = (
            MockModel.from_pretrained.return_value
        )

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(lambda _i: service._ensure_loaded(), range(16)))

        MockModel.from_pretrained.assert_called_once_with(settings.model_id)
        MockTok.from_pretrained.assert_called_once_with(settings.model_id)
        MockProc.from_pretrained.assert_called_once_with(settings.model_id)

    assert service.is_loaded is True


def test_as_tensor_with_plain_tensor():
    """Older transformers releases returned a bare tensor; pass-through."""
    t = torch.zeros(1, 512)
    assert _as_tensor(t) is t


def test_as_tensor_with_base_model_output_with_pooling():
    """Transformers >=5 returns BaseModelOutputWithPooling; extract pooler_output."""
    pooled = torch.zeros(1, 512)
    out = BaseModelOutputWithPooling(pooler_output=pooled, last_hidden_state=None)
    assert _as_tensor(out) is pooled


def test_as_tensor_rejects_unknown_type():
    with pytest.raises(TypeError, match="Unexpected CLIP output type"):
        _as_tensor(object())


def _make_loaded_service(features_obj) -> EmbeddingService:
    """Return an EmbeddingService whose CLIP model is a mock returning ``features_obj``."""
    service = EmbeddingService(Settings(device="cpu"))
    model = MagicMock()
    model.get_text_features.return_value = features_obj
    model.get_image_features.return_value = features_obj
    service._model = model
    tokenizer = MagicMock()
    tokenizer.return_value.to.return_value = {}
    service._tokenizer = tokenizer
    processor = MagicMock()
    processor.return_value.to.return_value = {}
    service._processor = processor
    return service


def test_get_text_features_handles_base_model_output_with_pooling():
    """Regression: transformers >=5 returns BaseModelOutputWithPooling, not a tensor."""
    pooled = torch.arange(512, dtype=torch.float32).unsqueeze(0)
    out = BaseModelOutputWithPooling(pooler_output=pooled, last_hidden_state=None)
    service = _make_loaded_service(out)

    result = service.get_text_features("a red dress")

    assert isinstance(result, np.ndarray)
    assert result.shape == (1, 512)
    np.testing.assert_array_equal(result, pooled.numpy())


def test_get_image_features_handles_base_model_output_with_pooling():
    """Regression: image branch must also extract pooler_output."""
    pooled = torch.ones(1, 512, dtype=torch.float32)
    out = BaseModelOutputWithPooling(pooler_output=pooled, last_hidden_state=None)
    service = _make_loaded_service(out)

    result = service.get_image_features(image=MagicMock())

    assert isinstance(result, np.ndarray)
    assert result.shape == (1, 512)
    np.testing.assert_array_equal(result, pooled.numpy())


def test_get_text_features_handles_legacy_tensor_return():
    """Backward compatibility with older transformers (bare tensor)."""
    tensor = torch.full((1, 512), 0.5)
    service = _make_loaded_service(tensor)

    result = service.get_text_features("query")

    assert isinstance(result, np.ndarray)
    np.testing.assert_array_equal(result, tensor.numpy())
