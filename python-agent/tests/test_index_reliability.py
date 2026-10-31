from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.knowledge.qdrant_store import InvalidCollectionException
import sqlite3
from langchain_core.documents import Document

from app.knowledge import vector_store as module
from app.knowledge import ingestion


def store_with(client):
    if isinstance(client, Mock) and not isinstance(client.list_collections.return_value, list):
        client.list_collections.return_value = []
    store = object.__new__(module.VectorStore)
    store.clients = [client]
    return store


def test_vector_outage_is_not_reported_as_empty_knowledge():
    store = store_with(Mock(get_collection=Mock(side_effect=ConnectionError("down"))))
    with pytest.raises(ConnectionError):
        store.get_collection("alice", "kb")


def test_delete_retry_cleans_lexical_index_when_vectors_already_gone(monkeypatch):
    store = store_with(Mock(get_collection=Mock(side_effect=InvalidCollectionException("missing"))))
    cleanup = Mock()
    monkeypatch.setattr(module.lexical_index, "delete_collection", cleanup)
    monkeypatch.setattr(module.lexical_index, "count_scope", lambda *_: 0)
    assert store.delete_collection("alice", "kb")
    cleanup.assert_called_once_with("alice", "kb")


@pytest.mark.parametrize("operation", ["delete_document", "delete_collection", "delete_user_collections"])
def test_vector_cleanup_does_not_hide_lexical_failure(monkeypatch, operation):
    client = Mock(get_collection=Mock(side_effect=InvalidCollectionException("missing")), list_collections=Mock(return_value=[]))
    store = store_with(client)
    lexical_method = {"delete_document": "delete_document", "delete_collection": "delete_collection",
                      "delete_user_collections": "delete_user"}[operation]
    cleanup = Mock(side_effect=sqlite3.OperationalError("readonly database"))
    monkeypatch.setattr(module.lexical_index, lexical_method, cleanup)
    monkeypatch.setattr(module.lexical_index, "count_scope", lambda *_: 0)
    args = ("alice", "kb", "doc") if operation == "delete_document" else ("alice", "kb") if operation == "delete_collection" else ("alice",)
    with pytest.raises(sqlite3.OperationalError):
        getattr(store, operation)(*args)
    cleanup.side_effect = None
    cleanup.return_value = 0
    getattr(store, operation)(*args)


def test_ingestion_does_not_report_success_after_lexical_write_failure(tmp_path, monkeypatch):
    path = tmp_path / "document.txt"
    path.write_text("new evidence", encoding="utf-8")
    collection = Mock(get=Mock(return_value={"ids": []}))
    monkeypatch.setattr(ingestion, "require_cloud_processing", lambda _: None)
    monkeypatch.setattr(ingestion, "vector_store", SimpleNamespace(get_or_create_collection=lambda *_: collection))
    monkeypatch.setattr(ingestion, "parse_document", lambda *_: [Document(page_content="new evidence")])
    monkeypatch.setattr(ingestion.lexical_index, "replace_document", Mock(side_effect=sqlite3.OperationalError("readonly database")))
    with pytest.raises(sqlite3.OperationalError):
        ingestion.ingest_document("alice", "kb", str(path), document_id="doc")


@pytest.mark.parametrize("scope", ["documents/doc", "collections/kb", "user/alice"])
def test_http_cleanup_failure_and_retry_with_real_stores(tmp_path, monkeypatch, scope):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import knowledge
    from app.knowledge.lexical_index import LexicalIndex
    from app.knowledge.qdrant_store import VectorClient

    client = VectorClient(path=str(tmp_path / "vectors"), dimension=2)
    store = store_with(client)
    lexical = LexicalIndex(str(tmp_path / "lexical.sqlite3"))
    monkeypatch.setattr(module, "lexical_index", lexical)
    monkeypatch.setattr(knowledge, "vector_store", store)
    for user in ["alice", "bob"]:
        collection = store.get_or_create_collection(user, "kb")
        collection.add(ids=["chunk"], documents=["private evidence"],
                       embeddings=[[1., 0.]], metadatas=[{"document_id": "doc"}])
        lexical.replace_document(user, "kb", "doc", [{"id": "chunk", "content": "private evidence"}])
    app = FastAPI()
    app.include_router(knowledge.router)
    http = TestClient(app, raise_server_exceptions=False)
    connect = lexical._connect
    monkeypatch.setattr(lexical, "_connect", lambda: sqlite3.connect(lexical.path.as_uri() + "?mode=ro", uri=True))
    url = f"/api/v1/knowledge/admin/{scope}?user_id=alice&kb_id=kb"
    assert http.delete(url).status_code == 500
    # Dense data is already gone; an idempotent retry must still remove FTS data.
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM lexical_chunks WHERE user_id='alice'").fetchone()[0] == 1
    monkeypatch.setattr(lexical, "_connect", connect)
    assert http.delete(url).status_code == 200
    assert lexical.search("alice", "kb", "private evidence", 5) == []
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM lexical_chunks WHERE user_id='alice'").fetchone()[0] == 0
    assert store.get_collection("bob", "kb").count() == 1
    assert lexical.search("bob", "kb", "private evidence", 5)


def test_colliding_identifiers_do_not_share_collection():
    assert module._get_collection_name("a/b", "kb") != module._get_collection_name("a_b", "kb")
    assert module._get_collection_name("x" * 80, "kb") != module._get_collection_name("x" * 81, "kb")


def test_owner_and_embedding_profile_are_enforced():
    profile = module.embeddings.profile()
    collection = Mock(metadata={"user_id": "alice", "kb_id": "kb", "embedding_profile": profile})
    store = store_with(Mock(get_collection=Mock(return_value=collection)))
    with pytest.raises(PermissionError):
        store.get_collection("bob", "kb")
    collection.metadata["embedding_profile"] = "another-model"
    collection.count.return_value = 3
    with pytest.raises(ValueError, match="Embedding 配置"):
        store.get_collection("alice", "kb")


def test_failed_replacement_preserves_previous_chunks(tmp_path, monkeypatch):
    path = tmp_path / "document.txt"
    path.write_text("new evidence", encoding="utf-8")
    collection = Mock()
    collection.get.return_value = {"ids": ["doc_00000", "doc_00001"]}
    collection.upsert.side_effect = RuntimeError("embedding offline")
    monkeypatch.setattr(ingestion, "require_cloud_processing", lambda _: None)
    monkeypatch.setattr(ingestion, "vector_store", SimpleNamespace(get_or_create_collection=lambda *_: collection))
    monkeypatch.setattr(ingestion, "parse_document", lambda *_: [Document(page_content="new evidence")])
    lexical = Mock()
    monkeypatch.setattr(ingestion.lexical_index, "replace_document", lexical)
    with pytest.raises(RuntimeError):
        ingestion.ingest_document("alice", "kb", str(path), document_id="doc")
    collection.delete.assert_not_called()
    lexical.assert_not_called()


def test_document_deletion_remains_possible_after_provider_change(monkeypatch):
    collection = Mock(metadata={"user_id": "alice", "kb_id": "kb", "embedding_profile": "old"})
    collection.get.side_effect = [{"ids": ["doc_0"]}, {"ids": []}]
    store = store_with(Mock(get_collection=Mock(return_value=collection)))
    monkeypatch.setattr(module.lexical_index, "delete_document", Mock())
    monkeypatch.setattr(module.lexical_index, "count_scope", lambda *_: 0)
    assert store.delete_document("alice", "kb", "doc") == 1
    collection.delete.assert_called_once_with(ids=["doc_0"])
    with pytest.raises(PermissionError):
        store.delete_document("bob", "kb", "doc")


def test_memory_profile_mismatch_blocks_semantic_ops_but_allows_export():
    from app.memory.memory_store import MemoryVectorStore
    store = object.__new__(MemoryVectorStore)
    store._collection = Mock(metadata={"embedding_profile": "old"})
    store._collection.count.return_value = 2
    with pytest.raises(ValueError, match="迁移指南"):
        store._require_embedding_profile()
    store._collection.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    assert store.list_all("alice") == []
    store._collection.query.assert_not_called()


def test_partial_parse_report_keeps_page_diagnostics(tmp_path, monkeypatch):
    path = tmp_path / "document.txt"
    path.write_text("evidence", encoding="utf-8")
    collection = Mock(get=Mock(return_value={"ids": []}))
    monkeypatch.setattr(ingestion, "require_cloud_processing", lambda _: None)
    monkeypatch.setattr(ingestion, "vector_store", SimpleNamespace(get_or_create_collection=lambda *_: collection))
    monkeypatch.setattr(ingestion, "parse_document", lambda *_: [Document(page_content="evidence"), Document(page_content="", metadata={"parse_warning": {"page": 2, "code": "no_text"}})])
    monkeypatch.setattr(ingestion.lexical_index, "replace_document", Mock())
    report = {}
    ingestion.ingest_document("alice", "kb", str(path), document_id="doc", report=report)
    assert report["status"] == "partial"
    assert report["warnings"] == [{"page": 2, "code": "no_text"}]
    assert len(report["content_sha256"]) == 64
    assert collection.upsert.call_args.kwargs["metadatas"][0]["parser_version"]
