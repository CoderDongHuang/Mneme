from types import SimpleNamespace

from app.knowledge import vector_store as module


def test_http_shards_receive_qdrant_urls_and_credentials(monkeypatch):
    created = []

    def fake_client(**kwargs):
        created.append(kwargs)
        return object()

    monkeypatch.setattr(module, "VectorClient", fake_client)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            vector_shard_urls="http://qdrant-1:6333,http://qdrant-2:6333",
            vector_shard_count=2,
            qdrant_api_key="test-key",
        ),
    )

    clients = module.VectorStore().clients

    assert len(clients) == 2
    assert [item["url"] for item in created] == ["http://qdrant-1:6333", "http://qdrant-2:6333"]
    assert all(item["api_key"] == "test-key" for item in created)
