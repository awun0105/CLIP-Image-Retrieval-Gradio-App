from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch
from clip import CLIPSearcher, _as_tensor, _tokenizer_max_length


def _loaded_searcher(output):
    searcher = CLIPSearcher(device="cpu")
    model = MagicMock()
    model.get_text_features.return_value = output
    model.get_image_features.return_value = output
    searcher._model = model
    tokenizer = MagicMock()
    tokenizer.return_value.to.return_value = {}
    tokenizer.model_max_length = 77
    searcher._tokenizer = tokenizer
    processor = MagicMock()
    processor.return_value.to.return_value = {}
    searcher._processor = processor
    return searcher


def test_as_tensor_supports_legacy_and_wrapped_outputs():
    tensor = torch.ones(1, 4)
    assert _as_tensor(tensor) is tensor
    assert _as_tensor(SimpleNamespace(pooler_output=tensor)) is tensor
    with pytest.raises(TypeError, match="Unexpected CLIP output type"):
        _as_tensor(object())


def test_tokenizer_max_length_rejects_sentinel():
    tokenizer = MagicMock(model_max_length=10**30)
    assert _tokenizer_max_length(tokenizer) == 77


def test_model_load_uses_resolved_device_and_eval():
    searcher = CLIPSearcher(device="cpu")
    with (
        patch("clip.CLIPModel") as model_class,
        patch("clip.CLIPTokenizer"),
        patch("clip.CLIPProcessor"),
    ):
        model = model_class.from_pretrained.return_value
        searcher._ensure_loaded()
    model.to.assert_called_once_with("cpu")
    model.eval.assert_called_once_with()
    model_class.from_pretrained.assert_called_once_with(
        "openai/clip-vit-base-patch32",
        revision="3d74acf9a28c67741b2f4f2ea7635f0aaf6f0268",
    )
    assert searcher.is_loaded


def test_text_features_are_truncated_and_return_float32():
    output = SimpleNamespace(pooler_output=torch.arange(4).reshape(1, 4))
    searcher = _loaded_searcher(output)
    result = searcher.get_text_features("a red dress")
    searcher._tokenizer.assert_called_once_with(
        "a red dress",
        return_tensors="pt",
        truncation=True,
        max_length=77,
    )
    assert result.dtype == np.float32
    assert result.shape == (1, 4)
    assert np.linalg.norm(result[0]) == pytest.approx(1.0)


def test_empty_image_batch_does_not_load_model():
    searcher = CLIPSearcher(device="cpu")
    result = searcher.get_image_batch_features([])
    assert result.shape == (0, 512)
    assert not searcher.is_loaded
