from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from threading import Event, current_thread

import pytest

from app.knowledge import ingestion, retriever, index_reconciliation as repair
from app.knowledge.generations import GenerationStore, StaleGeneration, generation_store
from app.knowledge.lexical_index import LexicalIndex
from app.knowledge.qdrant_store import VectorClient
from app.knowledge.vector_store import VectorStore


@pytest.fixture
def stores(tmp_path, monkeypatch):
    from app.knowledge import vector_store as store_module
    store = object.__new__(VectorStore)
    store.clients = [VectorClient(path=str(tmp_path / "vectors"))]
    lexical = LexicalIndex(str(tmp_path / "fts.sqlite3"))
    for module in (ingestion, retriever, repair):
        monkeypatch.setattr(module, "vector_store", store)
    for module in (ingestion, retriever, store_module):
        monkeypatch.setattr(module, "lexical_index", lexical)
    original = repair.synchronize_lexical
    monkeypatch.setattr(repair, "synchronize_lexical", lambda *a: original(*a, index=lexical))
    return store, lexical


def source(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


@pytest.mark.parametrize("channel", ["exact", "ann", "fallback"])
def test_paused_worker_after_checkpoint_cannot_touch_latest_generation(stores, tmp_path, monkeypatch, channel):
    store, lexical = stores
    old = source(tmp_path, "old.txt", "旧证据 old obsolete generation")
    new = source(tmp_path, "new.txt", "最新证据 latest generation")
    paused, resume = Event(), Event()
    writing = generation_store.writing

    @contextmanager
    def pause_after_lease_check(*args, **kwargs):
        if current_thread().name.startswith("stale"):
            paused.set()
            assert resume.wait(10)
        with writing(*args, **kwargs):
            yield

    monkeypatch.setattr(generation_store, "writing", pause_after_lease_check)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stale") as pool:
        future = pool.submit(ingestion.ingest_document, "alice", "kb", old, document_id="doc", index_generation=1)
        try:
            assert paused.wait(10)
            report = {}
            ingestion.ingest_document("alice", "kb", new, document_id="doc", report=report, index_generation=2)
            before = store.get_collection("alice", "kb").get(include=["documents", "metadatas", "embeddings"])
        finally:
            resume.set()
        with pytest.raises(StaleGeneration):
            future.result(10)
    assert store.get_collection("alice", "kb").get(include=["documents", "metadatas", "embeddings"]) == before
    assert lexical.document_version("alice", "kb", "doc") == report["vector_index_version"]
    if channel == "ann":
        monkeypatch.setattr(retriever, "settings", replace(retriever.settings, offline_embeddings=False))
    elif channel == "fallback":
        monkeypatch.setattr(lexical, "_available", False)
    chunks = retriever.retrieve("alice", "kb", "generation", 5)
    assert chunks and all(item["metadata"]["index_generation"] == 2 for item in chunks)
    assert all("obsolete" not in item["content"] for item in chunks)
    assert report["index_generation"] == 2
    assert all(item["metadata"]["index_generation"] == 2 for item in store.get_document_chunks("alice", "kb", "doc"))


@pytest.mark.parametrize("scope", ["document", "kb", "user"])
def test_deletion_tombstone_fences_inflight_and_late_requests(stores, tmp_path, monkeypatch, scope):
    store, _ = stores
    path = source(tmp_path, "a.txt", "generation evidence")
    generation_store.begin("alice", "kb", "doc", 1)
    if scope == "document":
        store.delete_document("alice", "kb", "doc")
    elif scope == "kb":
        store.delete_collection("alice", "kb")
    else:
        store.delete_user_collections("alice")
    with pytest.raises(StaleGeneration):
        with generation_store.writing("alice", "kb", "doc", 1):
            pytest.fail("deleted scope writable")
    with pytest.raises(StaleGeneration):
        ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=2)
    assert store.deletion_report("alice", "kb", "doc") == {"qdrant_chunks": 0, "fts_rows": 0}
    assert not store.list_user_collections("alice")


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_cancel_fences_old_work_but_explicit_new_generation_can_reparse(stores, tmp_path, monkeypatch, cleanup_fails):
    store, lexical = stores
    path = source(tmp_path, "cancel.txt", "published generation evidence")
    ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=1)
    generation_store.begin("alice", "kb", "doc", 2)  # cancelled worker already passed begin
    if cleanup_fails:
        with monkeypatch.context() as fault:
            fault.setattr(store, "_delete_document", lambda *_: (_ for _ in ()).throw(OSError("cleanup failed")))
            with pytest.raises(OSError):
                store.cancel_document("alice", "kb", "doc")
        assert store.get_document_chunks("alice", "kb", "doc") == []
        assert retriever.retrieve("alice", "kb", "evidence") == []
    store.cancel_document("alice", "kb", "doc")
    store.cancel_document("alice", "kb", "doc")  # cleanup retry is idempotent
    assert store.deletion_report("alice", "kb", "doc") == {"qdrant_chunks": 0, "fts_rows": 0}
    with pytest.raises(StaleGeneration):
        with generation_store.writing("alice", "kb", "doc", 2):
            pytest.fail("cancelled worker resumed")
    with pytest.raises(StaleGeneration):
        ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=2)
    assert generation_store.begin("alice", "kb", "doc", 3) == 3
    assert store.get_document_chunks("alice", "kb", "doc") == []  # reservation alone cannot publish
    report = {}
    ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=4, report=report)
    chunks = store.get_document_chunks("alice", "kb", "doc")
    assert chunks and all(chunk["metadata"]["index_generation"] == 4 for chunk in chunks)
    assert lexical.document_version("alice", "kb", "doc") == report["vector_index_version"]
    store.delete_document("alice", "kb", "doc")
    with pytest.raises(StaleGeneration):
        store.cancel_document("alice", "kb", "doc")  # cancellation cannot undo permanent deletion
    with pytest.raises(StaleGeneration):
        ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=5)


def test_cancel_before_first_begin_rejects_late_initial_request(stores, tmp_path):
    store, _ = stores
    path = source(tmp_path, "late.txt", "generation evidence")
    store.cancel_document("alice", "kb", "doc")
    with pytest.raises(StaleGeneration):
        ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=1)
    ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=2)
    assert store.get_document_chunks("alice", "kb", "doc")


def test_partial_storage_failure_keeps_previous_published_generation(stores, tmp_path, monkeypatch):
    store, lexical = stores
    ingestion.ingest_document("alice", "kb", source(tmp_path, "a.txt", "prior evidence"), document_id="doc")
    collection = store.get_collection("alice", "kb")
    upsert = collection.upsert

    def fail_after_write(**kwargs):
        upsert(**kwargs)
        raise OSError("response lost after durable write")

    monkeypatch.setattr(store, "get_or_create_collection", lambda *_: collection)
    monkeypatch.setattr(collection, "upsert", fail_after_write)
    with pytest.raises(OSError):
        ingestion.ingest_document("alice", "kb", source(tmp_path, "b.txt", "staged evidence"), document_id="doc")
    assert collection.count() == 2  # An uncommitted physical write is possible.
    hits = retriever.retrieve("alice", "kb", "evidence", 5)
    assert hits and all(item["content"] == "prior evidence" for item in hits)
    monkeypatch.setattr(collection, "upsert", upsert)
    report = {}
    ingestion.ingest_document("alice", "kb", source(tmp_path, "c.txt", "final evidence"), document_id="doc", report=report)
    assert collection.count() == 1
    assert report["index_generation"] == 3
    assert lexical.document_version("alice", "kb", "doc") == report["vector_index_version"]


def test_manifest_restart_replay_tenant_and_read_failure(stores, tmp_path, monkeypatch):
    store, _ = stores
    path = source(tmp_path, "a.txt", "published evidence")
    ingestion.ingest_document("alice", "kb", path, document_id="doc", index_generation=7)
    reopened = GenerationStore(generation_store.path)
    assert reopened.snapshot("alice")["libraries"]["kb"]["documents"]["doc"]["active"] == 7
    with pytest.raises(StaleGeneration):
        reopened.begin("alice", "kb", "doc", 6)
    with pytest.raises(StaleGeneration):
        reopened.begin("alice", "kb", "doc", 7)
    assert reopened.begin("bob", "kb", "doc", 1) == 1
    # Loss of the manifest never guesses a generation from Qdrant.
    with reopened.locked("alice") as state:
        state.clear()
    assert retriever.retrieve("alice", "kb", "evidence", 5) == []
    monkeypatch.setattr(generation_store, "snapshot", lambda *_: (_ for _ in ()).throw(OSError("unreadable")))
    with pytest.raises(OSError):
        retriever.retrieve("alice", "kb", "evidence", 5)
    assert store.get_collection("alice", "kb").count() == 1
