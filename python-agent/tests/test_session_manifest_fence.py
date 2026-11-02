"""Persisted metadata races, atomic failure and post-deletion writes."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from app.knowledge.generations import generation_store, StaleGeneration
from app.memory.session_store import SessionStore


def test_two_instances_do_not_lose_concurrent_sessions_or_counts(tmp_path):
    stores = [SessionStore(str(tmp_path)), SessionStore(str(tmp_path))]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: stores[i % 2].register_session("user", str(i)), range(32)))
        list(pool.map(lambda i: stores[i % 2].increment_message_count("user", "0"), range(32)))
    sessions = stores[0].get_sessions("user")
    assert len(sessions) == 32
    assert next(row for row in sessions if row["id"] == "0")["message_count"] == 33


def test_inflight_publication_finishes_before_tombstone_and_file_cleanup(tmp_path, monkeypatch):
    first, second = SessionStore(str(tmp_path)), SessionStore(str(tmp_path))
    entered, release, deleting = Event(), Event(), Event()
    original = first._write

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        original(*args)

    monkeypatch.setattr(first, "_write", delayed)

    def erase():
        deleting.set()
        generation_store.tombstone("user")
        assert second.cleanup_session_ids("user") == ["session"]
        second.delete_user("user")

    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(first.register_session, "user", "session")
        try:
            assert entered.wait(5)
            deletion = pool.submit(erase)
            assert deleting.wait(5)
            assert not deletion.done()
        finally:
            release.set()
        writing.result(5)
        deletion.result(5)
    assert not Path(first._get_file_path("user")).exists()


def test_all_late_mutations_rejected_and_reads_do_not_recreate_manifest(tmp_path):
    store = SessionStore(str(tmp_path))
    store.register_session("other", "kept")
    generation_store.tombstone("deleted")
    # Fresh instance, not a process-local set of deleted users.
    store = SessionStore(str(tmp_path))
    calls = [lambda: store.register_session("deleted", "late"),
             lambda: store.update_title("deleted", "late", "late"),
             lambda: store.increment_message_count("deleted", "late"),
             lambda: store.delete_session("deleted", "late"),
             lambda: store._save("deleted", {"late": {}})]
    for call in calls:
        with pytest.raises(StaleGeneration):
            call()
    assert store.get_sessions("deleted") == []
    assert store.get_session_count("deleted") == 0
    assert store.cleanup_session_ids("deleted") == []
    assert not Path(store._get_file_path("deleted")).exists()
    assert store.cleanup_session_ids("other") == ["kept"]


@pytest.mark.parametrize("failure", ["serialize", "fsync", "replace"])
def test_failed_publication_preserves_old_bytes_and_propagates(tmp_path, monkeypatch, failure):
    store = SessionStore(str(tmp_path))
    store.register_session("user", "kept")
    path = Path(store._get_file_path("user"))
    before = path.read_bytes()

    def broken(*args, **kwargs):
        raise OSError("private storage path")

    target = {"serialize": "json.dump", "fsync": "os.fsync", "replace": "os.replace"}[failure]
    with monkeypatch.context() as fault:
        fault.setattr("app.memory.session_store." + target, broken)
        with pytest.raises(OSError):
            store.register_session("user", "new")
    assert path.read_bytes() == before
    assert not list(tmp_path.glob(".session-*.tmp"))
    store.register_session("user", "new")
    assert set(store.cleanup_session_ids("user")) == {"kept", "new"}


@pytest.mark.parametrize("content", ["{broken", "[]", '{"session":null}'])
def test_corrupt_manifest_never_overwritten_or_reported_empty(tmp_path, content):
    store = SessionStore(str(tmp_path))
    path = Path(store._get_file_path("user"))
    path.write_text(content)
    for call in [lambda: store.register_session("user", "new"),
                 lambda: store.get_sessions("user"), lambda: store.get_session_count("user"),
                 lambda: store.cleanup_session_ids("user")]:
        with pytest.raises((ValueError, json.JSONDecodeError)):
            call()
        assert path.read_text() == content


def test_ttl_publication_serialized_before_deletion(tmp_path, monkeypatch):
    store = SessionStore(str(tmp_path))
    store._save("user", {"expired": {"last_updated": "2000-01-01T00:00:00"}})
    entered, release = Event(), Event()
    original = store._write

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        original(*args)

    monkeypatch.setattr(store, "_write", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pruning = pool.submit(store.get_sessions, "user")
        try:
            assert entered.wait(5)
            deletion = pool.submit(generation_store.tombstone, "user")
            assert not deletion.done()
        finally:
            release.set()
        assert pruning.result(5) == []
        deletion.result(5)
    store.delete_user("user")
    assert store.get_sessions("user") == []
    assert not Path(store._get_file_path("user")).exists()
