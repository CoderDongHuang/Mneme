import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.knowledge import ingestion, index_reconciliation as repair
from app.knowledge.index_version import index_version
from app.knowledge.lexical_index import LexicalIndex
from app.knowledge.qdrant_store import VectorClient
from app.knowledge.vector_store import VectorStore


@pytest.fixture
def stores(tmp_path, monkeypatch):
    store = object.__new__(VectorStore)
    store.clients = [VectorClient(path=str(tmp_path / "vectors"))]
    lexical = LexicalIndex(str(tmp_path / "lexical.sqlite3"))
    monkeypatch.setattr(ingestion, "vector_store", store)
    monkeypatch.setattr(ingestion, "lexical_index", lexical)
    monkeypatch.setattr(repair, "vector_store", store)
    # Default argument belongs to ingestion's injected index; repair explicitly injects below.
    original = repair.synchronize_lexical
    monkeypatch.setattr(repair, "synchronize_lexical", lambda *args: original(*args, index=lexical))
    return store, lexical


@pytest.mark.parametrize("failure", ["readonly", "locked", "disk_full"])
def test_partial_ingestion_repaired_without_file_or_embedding(stores, tmp_path, monkeypatch, failure):
    store, lexical = stores
    path = tmp_path / "source.txt"
    path.write_text("可恢复的词法证据 reconciliation evidence", encoding="utf-8")
    connect = lexical._connect
    blocker = None
    if failure == "readonly":
        monkeypatch.setattr(lexical, "_connect", lambda: sqlite3.connect(lexical.path.as_uri() + "?mode=ro", uri=True))
    elif failure == "locked":
        blocker = connect()
        blocker.execute("BEGIN EXCLUSIVE")
        monkeypatch.setattr(lexical, "_connect", lambda: sqlite3.connect(lexical.path, timeout=0))
    else:
        monkeypatch.setattr(lexical, "_connect", Mock(side_effect=sqlite3.OperationalError("database or disk is full")))
    report = {}
    try:
        assert ingestion.ingest_document("alice", "kb", str(path), document_id="doc", report=report) == "doc"
    finally:
        if blocker:
            blocker.rollback()
            blocker.close()
        monkeypatch.setattr(lexical, "_connect", connect)
    assert report["status"] == "partial"
    assert report["index_status"] == "pending"
    assert len(report["vector_index_version"]) == 64
    assert report["lexical_index_version"] is None
    assert store.get_collection("alice", "kb").count() > 0
    path.unlink()
    # Provider/profile changes must not force a new embedding request during repair.
    forbidden = Mock(side_effect=AssertionError("repair must not parse or embed"))
    monkeypatch.setattr(ingestion, "parse_document", forbidden)
    monkeypatch.setattr(ingestion, "embeddings", forbidden)
    result = repair.reconcile_document("alice", "kb", "doc", report["vector_index_version"])
    assert result["vector_index_version"] == result["lexical_index_version"] == report["vector_index_version"]
    assert lexical.search("alice", "kb", "reconciliation", 5)
    assert repair.reconcile_document("alice", "kb", "doc", report["vector_index_version"]) == result
    forbidden.assert_not_called()


def test_repair_rejects_other_tenant_missing_or_changed_version(stores, tmp_path):
    _, lexical = stores
    path = tmp_path / "source.txt"
    path.write_text("evidence", encoding="utf-8")
    report = {}
    ingestion.ingest_document("alice", "kb", str(path), document_id="doc", report=report)
    for user, version in [("bob", report["vector_index_version"]), ("alice", "0" * 64)]:
        with pytest.raises(ValueError):
            repair.reconcile_document(user, "kb", "doc", version)
    assert lexical.document_version("alice", "kb", "doc") == report["vector_index_version"]
    assert lexical.document_version("bob", "kb", "doc") is None


def test_versions_read_actual_rows_and_detect_missing_chunks(stores, tmp_path):
    _, lexical = stores
    path = tmp_path / "source.txt"
    path.write_text("reconciliation evidence", encoding="utf-8")
    report = {}
    ingestion.ingest_document("alice", "kb", str(path), document_id="doc", report=report)
    with lexical._connect() as conn:
        conn.execute("UPDATE lexical_chunks SET content='corrupt' WHERE user_id='alice'")
    assert lexical.document_version("alice", "kb", "doc") != report["vector_index_version"]
    repair.reconcile_document("alice", "kb", "doc", report["vector_index_version"])
    assert lexical.document_version("alice", "kb", "doc") == report["vector_index_version"]


def test_readback_mismatch_is_not_ready(stores, tmp_path, monkeypatch):
    _, lexical = stores
    path = tmp_path / "source.txt"
    path.write_text("evidence", encoding="utf-8")
    report = {}
    monkeypatch.setattr(lexical, "document_version", lambda *_: "incorrect")
    ingestion.ingest_document("alice", "kb", str(path), document_id="doc", report=report)
    assert report["index_status"] == "pending"
    with pytest.raises(sqlite3.DatabaseError, match="读回"):
        repair.reconcile_document("alice", "kb", "doc", report["vector_index_version"])


def test_repair_detects_dense_change_during_lexical_write(monkeypatch):
    chunks = [{"id": "one", "content": "first", "metadata": {}}]
    version = index_version(chunks)
    collection = Mock()
    collection.get.side_effect = [
        {"ids": ["one"], "documents": ["first"], "metadatas": [{}]},
        {"ids": ["one"], "documents": ["changed"], "metadatas": [{}]},
    ]
    monkeypatch.setattr(repair, "vector_store", SimpleNamespace(get_collection=lambda *a, **k: collection))
    monkeypatch.setattr(repair, "synchronize_lexical", lambda *a: {})
    with pytest.raises(ValueError, match="修复期间"):
        repair.reconcile_document("alice", "kb", "doc", version)
