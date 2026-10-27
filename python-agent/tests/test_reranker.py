from app.knowledge.reranker import rerank
from app.core.config import settings
import pytest
from dataclasses import replace
import importlib

reranker_module = importlib.import_module("app.knowledge.reranker")


def test_reranker_has_deterministic_fallback_without_optional_model():
    candidates = [{"id": "first"}, {"id": "second"}]
    assert rerank("query", candidates, 1) == [{"id": "first"}]


def test_dashscope_reranker_orders_by_provider_scores(monkeypatch):
    import dashscope

    class Response:
        status_code = 200
        output = {"results": [{"index": 1, "relevance_score": 0.9}]}

    monkeypatch.setattr(dashscope.TextReRank, "call", lambda **kwargs: Response())
    old = (settings.reranker_enabled, settings.reranker_provider, settings.dashscope_api_key)
    object.__setattr__(settings, "reranker_enabled", True)
    object.__setattr__(settings, "reranker_provider", "dashscope")
    object.__setattr__(settings, "dashscope_api_key", "test-key")
    try:
        candidates = [{"id": "first", "content": "a"}, {"id": "second", "content": "b"}]
        assert rerank("query", candidates, 1)[0]["id"] == "second"
    finally:
        object.__setattr__(settings, "reranker_enabled", old[0])
        object.__setattr__(settings, "reranker_provider", old[1])
        object.__setattr__(settings, "dashscope_api_key", old[2])


def test_normalized_reranking_discards_weak_evidence_instead_of_restoring_candidates(monkeypatch):
    import dashscope
    from types import SimpleNamespace
    monkeypatch.setattr(reranker_module, "settings", replace(settings, reranker_enabled=True,
        reranker_provider="dashscope", reranker_min_score=0.25, dashscope_api_key="test-key"))
    response = SimpleNamespace(status_code=200, output={"results": [
        {"index": 0, "relevance_score": 0.17}, {"index": 1, "relevance_score": 0.11}]})
    monkeypatch.setattr(dashscope.TextReRank, "call", lambda **kwargs: response)
    candidates = [{"content": "same topic, absent requested fact"}, {"content": "another topic"}]
    assert rerank("missing fact", candidates, 2) == []
    response.output["results"][1]["relevance_score"] = 0.9
    assert rerank("present fact", candidates, 2) == [{**candidates[1], "rerank_score": 0.9}]


@pytest.mark.parametrize("index,score", [(-1, 0.9), (True, 0.9), (0, float("nan")), (0, 1.1), (0, True)])
def test_malformed_provider_ranking_falls_back_without_trusting_scores(monkeypatch, index, score):
    import dashscope
    from types import SimpleNamespace
    monkeypatch.setattr(reranker_module, "settings", replace(settings, reranker_enabled=True,
        reranker_provider="dashscope", dashscope_api_key="test-key"))
    monkeypatch.setattr(dashscope.TextReRank, "call", lambda **kwargs: SimpleNamespace(
        status_code=200, output={"results": [{"index": index, "relevance_score": score}]}))
    candidates = [{"content": "original"}]
    assert rerank("query", candidates, 1) == candidates
