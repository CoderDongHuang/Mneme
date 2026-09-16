from app.knowledge.reranker import rerank
from app.core.config import settings


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
