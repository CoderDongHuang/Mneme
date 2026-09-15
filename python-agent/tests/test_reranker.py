from app.knowledge.reranker import rerank


def test_reranker_has_deterministic_fallback_without_optional_model():
    candidates = [{"id": "first"}, {"id": "second"}]
    assert rerank("query", candidates, 1) == [{"id": "first"}]
