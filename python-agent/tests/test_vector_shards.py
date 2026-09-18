from types import SimpleNamespace

from app.knowledge import vector_store as module


def test_http_shards_receive_independent_chroma_settings(monkeypatch):
    created = []

    def fake_client(**kwargs):
        created.append(kwargs)
        return object()

    monkeypatch.setattr(module.chromadb, "HttpClient", fake_client)
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(
            vector_shard_urls="http://chroma-1:8000,http://chroma-2:8000",
            vector_shard_count=2,
            chroma_mode="http",
            chroma_host="unused",
            chroma_port=8000,
            chroma_path="unused",
        ),
    )

    clients = module.VectorStore().clients

    assert len(clients) == 2
    assert [item["host"] for item in created] == ["chroma-1", "chroma-2"]
    assert created[0]["settings"] is not created[1]["settings"]
