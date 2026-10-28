from unittest.mock import MagicMock
import threading

import pytest

from app.knowledge import cancellation


def test_cancelled_request_stops_before_body_and_releases_own_lock(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    client.eval.return_value = 1
    client.exists.return_value = True
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with pytest.raises(cancellation.IngestionCancelled):
        with cancellation.ingestion_task("u1", "task1"):
            pytest.fail("cancelled ingestion was executed")
    client.set.assert_called_once()
    assert client.set.call_args.kwargs["ex"] == cancellation._LEASE_SECONDS
    assert client.eval.call_count == 2  # checkpoint renewal and owner release
    assert client.eval.call_args.args[2] == "mneme:ingestion:active:u1:task1"
    assert client.eval.call_args.args[3] == client.set.call_args.args[1]
    cancellation.check_cancelled()  # No leaked task context.


def test_duplicate_worker_cannot_remove_the_active_workers_lock(monkeypatch):
    client = MagicMock()
    client.set.return_value = False
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with pytest.raises(RuntimeError, match="仍在运行"):
        with cancellation.ingestion_task("u1", "task1"):
            pytest.fail("duplicate executed")
    client.delete.assert_not_called()
    client.eval.assert_not_called()


def test_cancellation_is_checked_during_processing(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    client.exists.side_effect = [False, True]
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with cancellation.ingestion_task("u1", "task1"):
        with pytest.raises(cancellation.IngestionCancelled):
            cancellation.check_cancelled()


def test_lease_renewal_is_owner_scoped_and_lost_lease_stops_work(monkeypatch):
    client = MagicMock()
    client.eval.return_value = 0
    assert not cancellation._renew_lease(client, "active", "old-owner")
    assert "redis.call('get', KEYS[1]) == ARGV[1]" in client.eval.call_args.args[0]

    lost = threading.Event()
    lost.set()
    token = cancellation._task.set(("u1", "task1", lost, "owner"))
    try:
        with pytest.raises(cancellation.IngestionLeaseLost, match="租约已丢失"):
            cancellation.check_cancelled()
    finally:
        cancellation._task.reset(token)


def test_heartbeat_marks_lease_lost_if_renewal_fails(monkeypatch):
    client = MagicMock()
    stop = threading.Event()
    lost = threading.Event()
    monkeypatch.setattr(cancellation, "_LEASE_RENEW_SECONDS", 0.01)
    monkeypatch.setattr(cancellation, "_renew_lease", lambda *_args: False)

    worker = threading.Thread(
        target=cancellation._heartbeat,
        args=(client, "active", "owner", stop, lost),
    )
    worker.start()
    assert lost.wait(timeout=1)
    worker.join(timeout=1)
    assert not worker.is_alive()


def test_resumed_worker_checks_redis_owner_before_heartbeat(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    client.eval.side_effect = [1, 0, 0]
    client.exists.return_value = False
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with cancellation.ingestion_task("u1", "task1"):
        with pytest.raises(cancellation.IngestionLeaseLost):
            cancellation.check_cancelled()


def test_release_failure_preserves_body_error_and_closes_client(monkeypatch):
    client = MagicMock()
    client.set.return_value = True
    client.eval.side_effect = [1, cancellation.redis.ConnectionError("offline")]
    client.exists.return_value = False
    monkeypatch.setattr(cancellation.redis, "Redis", lambda **kwargs: client)
    with pytest.raises(ValueError, match="original"):
        with cancellation.ingestion_task("u1", "task1"):
            raise ValueError("original")
    assert client.close.call_count == 2


def test_lease_is_rechecked_after_embedding_before_any_vector_write(monkeypatch, tmp_path):
    from app.knowledge import ingestion

    path = tmp_path / "synthetic.txt"
    path.write_text("Synthetic evidence for cancellation after provider return.", encoding="utf-8")
    collection = MagicMock()
    collection.get.return_value = {"ids": []}
    lost = threading.Event()

    def embed(documents):
        lost.set()  # Simulates a lease lost while a slow provider call was in flight.
        return [[0.0] * 1024 for _ in documents]

    def checkpoint():
        if lost.is_set():
            raise cancellation.IngestionLeaseLost("lost during embedding")

    monkeypatch.setattr(ingestion, "embeddings", embed)
    monkeypatch.setattr(ingestion, "check_cancelled", checkpoint)
    monkeypatch.setattr(ingestion.vector_store, "get_or_create_collection", lambda *_: collection)
    with pytest.raises(cancellation.IngestionLeaseLost, match="during embedding"):
        ingestion.ingest_document("synthetic", "kb", str(path))
    collection.upsert.assert_not_called()
    collection.delete.assert_not_called()
