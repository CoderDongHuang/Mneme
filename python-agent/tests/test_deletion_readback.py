"""Real Qdrant/SQLite stores: successful calls alone do not prove deletion."""
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import knowledge
from app.knowledge import vector_store as module
from app.knowledge.lexical_index import LexicalIndex
from app.knowledge.qdrant_store import VectorClient


@pytest.fixture
def resources(tmp_path, monkeypatch):
    client = VectorClient(path=str(tmp_path / "vectors"), dimension=2)
    store = object.__new__(module.VectorStore)
    store.clients = [client]
    lexical = LexicalIndex(str(tmp_path / "lexical.sqlite3"))
    monkeypatch.setattr(module, "lexical_index", lexical)
    monkeypatch.setattr(knowledge, "vector_store", store)
    for user, kb, doc in (("alice", "kb", "doc"), ("alice", "kb", "keep"), ("bob", "kb", "doc")):
        collection = store.get_or_create_collection(user, kb)
        collection.add(ids=[doc], documents=["private deletion evidence"], embeddings=[[1., 0.]],
                       metadatas=[{"document_id": doc}])
        lexical.replace_document(user, kb, doc, [{"id": doc, "content": "private deletion evidence"}])
    app = FastAPI()
    app.include_router(knowledge.router)
    return store, lexical, TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("scope", ["documents/doc", "collections/kb", "user/alice"])
@pytest.mark.parametrize("failure", ["fts_noop", "vector_noop", "fts_read_error"])
def test_http_refuses_false_success_then_retry_verifies_each_store(resources, monkeypatch, scope, failure):
    store, lexical, http = resources
    document_scope = scope.startswith("documents")
    suffix = "&kb_id=kb" + ("&document_id=doc" if document_scope else "")
    if scope.startswith("user"):
        suffix = ""
    report_url = "/api/v1/knowledge/admin/deletion-report?user_id=alice" + suffix
    with monkeypatch.context() as fault:
        if failure == "fts_noop":
            method = "delete_document" if document_scope else "delete_collection" if scope.startswith("collections") else "delete_user"
            fault.setattr(lexical, method, lambda *_: 0)
        elif failure == "fts_read_error":
            def broken(*_):
                raise sqlite3.OperationalError("database is locked")
            fault.setattr(lexical, "count_scope", broken)
        elif document_scope:
            fault.setattr(type(store.get_collection("alice", "kb")), "delete", lambda *_, **__: None)
        else:
            fault.setattr(store.clients[0], "delete_collection", lambda *_, **__: None)
        assert http.delete(f"/api/v1/knowledge/admin/{scope}?user_id=alice&kb_id=kb").status_code == 500
        report = http.get(report_url).json()
        expected_fts = -1 if failure == "fts_read_error" else (1 if document_scope else 2) if failure == "fts_noop" else 0
        assert report["fts_rows"] == expected_fts
        assert report["qdrant_chunks"] == ((1 if document_scope else 2) if failure == "vector_noop" else 0)
    assert http.delete(f"/api/v1/knowledge/admin/{scope}?user_id=alice&kb_id=kb").status_code == 200
    assert all(count == 0 for count in http.get(report_url).json().values())
    assert lexical.count_scope("bob", "kb", "doc") == 1
    assert store.get_collection("bob", "kb").count() == 1
    assert store.deletion_report("bob", "kb", "doc") == {"qdrant_chunks": 1, "fts_rows": 1}
    if document_scope:
        assert lexical.count_scope("alice", "kb", "keep") == 1
        assert store.get_collection("alice", "kb").count() == 1


def test_unavailable_qdrant_keeps_fts_count_but_never_reports_zero(resources, monkeypatch):
    store, _, http = resources
    def unavailable(*_, **__):
        raise ConnectionError("offline")
    monkeypatch.setattr(store, "get_collection", unavailable)
    report = http.get("/api/v1/knowledge/admin/deletion-report?user_id=alice&kb_id=kb&document_id=doc").json()
    assert report == {"qdrant_chunks": -1, "fts_rows": 1}
    with pytest.raises(RuntimeError, match="verification failed"):
        store.require_deleted("alice", "kb", "doc")


def test_invalid_document_scope_is_rejected(resources):
    _, lexical, http = resources
    assert http.get("/api/v1/knowledge/admin/deletion-report?user_id=alice&document_id=doc").status_code == 400
    with pytest.raises(ValueError):
        lexical.count_scope("alice", document_id="doc")


@pytest.mark.parametrize("whole_kb", [False, True])
def test_old_named_collections_on_other_configured_shards_are_also_erased(resources, tmp_path, whole_kb):
    store, _, _ = resources
    old_shard = VectorClient(path=str(tmp_path / "old-shard"), dimension=2)
    store.clients.append(old_shard)
    for user in ("alice", "bob"):
        collection = old_shard.get_or_create_collection(
            name=f"legacy_{user}", metadata={"user_id": user, "kb_id": "kb", "embedding_profile": "obsolete"})
        collection.add(ids=["old-doc"], documents=["old index"], embeddings=[[1., 0.]], metadatas=[{"document_id": "doc"}])
    assert store.deletion_report("alice", "kb", "doc")["qdrant_chunks"] == 2
    if whole_kb:
        store.delete_collection("alice", "kb")
        assert all(count == 0 for count in store.deletion_report("alice", "kb").values())
    else:
        assert store.delete_document("alice", "kb", "doc") == 2
        assert all(count == 0 for count in store.deletion_report("alice", "kb", "doc").values())
    assert store.deletion_report("bob", "kb", "doc")["qdrant_chunks"] == 2
