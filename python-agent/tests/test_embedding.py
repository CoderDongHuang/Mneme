from types import SimpleNamespace

import pytest

from app.utils import embedding


def test_strict_real_embedding_does_not_fall_back(monkeypatch):
    monkeypatch.setenv("MNEME_REQUIRE_REAL_EMBEDDINGS", "true")
    monkeypatch.setattr(
        embedding,
        "settings",
        SimpleNamespace(dashscope_api_key="configured", embedding_model="test"),
    )
    client = embedding.DashScopeEmbeddingFunction()
    monkeypatch.setattr(
        client,
        "_call_dashscope",
        lambda _texts: (_ for _ in ()).throw(ConnectionError("offline")),
    )

    with pytest.raises(RuntimeError, match="真实 Embedding API 调用失败"):
        client(["sample"])


def test_strict_real_embedding_requires_credential(monkeypatch):
    monkeypatch.setenv("MNEME_REQUIRE_REAL_EMBEDDINGS", "true")
    monkeypatch.setattr(
        embedding,
        "settings",
        SimpleNamespace(dashscope_api_key="", embedding_model="test"),
    )

    with pytest.raises(RuntimeError, match="有效 DASHSCOPE_API_KEY"):
        embedding.DashScopeEmbeddingFunction()(["sample"])


def test_provider_outage_never_silently_changes_vector_space(monkeypatch):
    client = embedding.DashScopeEmbeddingFunction()
    monkeypatch.delenv("MNEME_REQUIRE_REAL_EMBEDDINGS", raising=False)
    monkeypatch.setattr(client, "_should_use_offline", lambda: False)
    monkeypatch.setattr(client, "_call_dashscope", lambda _: (_ for _ in ()).throw(ConnectionError("provider unavailable")))
    with pytest.raises(RuntimeError, match="原有索引保留"):
        client(["existing document"])
