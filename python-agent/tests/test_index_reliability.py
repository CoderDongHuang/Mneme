from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from chromadb.errors import InvalidCollectionException
from langchain_core.documents import Document

from app.knowledge import vector_store as module
from app.knowledge import ingestion


def store_with(client):
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
    assert store.delete_collection("alice", "kb")
    cleanup.assert_called_once_with("alice", "kb")


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
    collection.get.return_value = {"ids": ["doc_0"]}
    store = store_with(Mock(get_collection=Mock(return_value=collection)))
    monkeypatch.setattr(module.lexical_index, "delete_document", Mock())
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
