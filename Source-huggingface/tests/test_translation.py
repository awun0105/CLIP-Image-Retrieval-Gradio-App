from unittest.mock import MagicMock

from translation import QueryTranslator


def test_english_query_passes_through_without_loading_model(monkeypatch):
    translator = QueryTranslator()
    monkeypatch.setattr(translator, "detect_language", lambda _query: "english")
    prepared = translator.prepare("  a   red car  ")
    assert prepared.clip_query == "a red car"
    assert not prepared.translated
    assert translator._model is None


def test_vietnamese_query_is_translated(monkeypatch):
    translator = QueryTranslator()
    monkeypatch.setattr(translator, "detect_language", lambda _query: "vietnamese")
    monkeypatch.setattr(translator, "translate", lambda _query: "a red car")
    prepared = translator.prepare("một chiếc xe màu đỏ")
    assert prepared.clip_query == "a red car"
    assert prepared.translated
    assert prepared.detected_language == "vietnamese"


def test_translation_failure_keeps_original_query(monkeypatch):
    translator = QueryTranslator()

    def fail(_query):
        raise RuntimeError("offline")

    monkeypatch.setattr(translator, "translate", fail)
    prepared = translator.prepare("xin chao", requested_language="vietnamese")
    assert prepared.clip_query == "xin chao"
    assert not prepared.translated
    assert "offline" in prepared.warning


def test_translation_result_is_cached():
    translator = QueryTranslator(cache_size=2)
    tokenizer = MagicMock()
    tokenizer.return_value = {"input_ids": MagicMock()}
    tokenizer.batch_decode.return_value = ["a person"]
    model = MagicMock()
    model.generate.return_value = MagicMock()
    translator._tokenizer = tokenizer
    translator._model = model
    assert translator.translate("một người") == "a person"
    assert translator.translate("một người") == "a person"
    model.generate.assert_called_once()
