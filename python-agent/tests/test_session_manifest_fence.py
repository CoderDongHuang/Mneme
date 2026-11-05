"""Persisted metadata races, atomic failure and post-deletion writes."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from app.knowledge.generations import generation_store, StaleGeneration
from app.memory.session_store import SessionStore
from app.memory.session_scope import tombstone_session


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


def test_delivery_survives_new_instances_and_is_scoped_by_role_user_session(tmp_path):
    for user, session in [("one", "first"), ("one", "second"), ("two", "first")]:
        for _ in range(2):
            store = SessionStore(str(tmp_path))
            store.register_session(user, session, delivery_id="private-request")
            store.increment_message_count(user, session, delivery_id="private-request")
        row = next(row for row in store.get_sessions(user) if row["id"] == session)
        assert row["message_count"] == 2
        assert "message_deliveries" not in row
        path = Path(store._get_file_path(user))
        before = path.read_bytes()
        store.register_session(user, session, title="changed", message_count=99, delivery_id="private-request")
        store.increment_message_count(user, session, delivery_id="private-request")
        assert path.read_bytes() == before
        assert "private-request" not in path.read_text(encoding="utf-8")
        store.register_session(user, session, delivery_id="next")
        store.increment_message_count(user, session, delivery_id="next")
        assert next(row for row in store.get_sessions(user) if row["id"] == session)["message_count"] == 4


def test_concurrent_repeated_deliveries_have_one_count_per_role(tmp_path):
    stores = [SessionStore(str(tmp_path)), SessionStore(str(tmp_path))]

    def deliver(i):
        store = stores[i % 2]
        store.register_session("user", "session", delivery_id=str(i % 8))
        store.increment_message_count("user", "session", delivery_id=str(i % 8))

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(deliver, range(64)))
    assert stores[0].get_sessions("user")[0]["message_count"] == 16


@pytest.mark.parametrize("operation", ["register", "increment"])
@pytest.mark.parametrize("failure", ["serialize", "fsync", "replace", "ack"])
def test_delivery_publication_and_lost_ack_retry(tmp_path, monkeypatch, operation, failure):
    store = SessionStore(str(tmp_path))
    store.register_session("user", "session", delivery_id="initial")
    path = Path(store._get_file_path("user"))
    before = path.read_bytes()
    method = "register_session" if operation == "register" else "increment_message_count"
    original = store._write

    def broken(*args, **kwargs):
        if failure == "ack":
            original(*args, **kwargs)
        raise OSError("storage unavailable")

    with monkeypatch.context() as fault:
        if failure == "ack":
            fault.setattr(store, "_write", broken)
        else:
            target = {"serialize": "json.dump", "fsync": "os.fsync", "replace": "os.replace"}[failure]
            fault.setattr("app.memory.session_store." + target, broken)
        with pytest.raises(OSError):
            getattr(store, method)("user", "session", delivery_id="retry")
    if failure != "ack":
        assert path.read_bytes() == before
    assert not list(tmp_path.glob(".session-*.tmp"))
    for _ in range(2):
        getattr(SessionStore(str(tmp_path)), method)("user", "session", delivery_id="retry")
    assert store.get_sessions("user")[0]["message_count"] == 2


@pytest.mark.parametrize("receipts", [None, [], {"bad": True}, {"a" * 64: 1}, {"A" * 64: True}])
def test_corrupt_delivery_receipts_fail_closed(tmp_path, receipts):
    store = SessionStore(str(tmp_path))
    path = Path(store._get_file_path("user"))
    path.write_text(json.dumps({"session": {"message_deliveries": receipts}}))
    before = path.read_bytes()
    for method in [store.register_session, store.increment_message_count]:
        with pytest.raises(ValueError, match="回执损坏"):
            method("user", "session", delivery_id="retry")
        assert path.read_bytes() == before


@pytest.mark.parametrize("delivery_id", [None, 1, " " , "x" * 65])
def test_invalid_delivery_never_publishes(tmp_path, delivery_id):
    store = SessionStore(str(tmp_path))
    for method in [store.register_session, store.increment_message_count]:
        with pytest.raises(ValueError, match="投递编号无效"):
            method("user", "session", delivery_id=delivery_id)
    assert not Path(store._get_file_path("user")).exists()


@pytest.mark.parametrize("scope", ["account", "session"])
def test_deleted_scope_rejects_late_delivery_even_with_old_receipt(tmp_path, scope):
    store = SessionStore(str(tmp_path))
    store.register_session("user", "session", delivery_id="turn")
    if scope == "account":
        generation_store.tombstone("user")
        store.delete_user("user")
    else:
        tombstone_session("user", "session")
        store.purge_deleted_session("user", "session")
    fresh = SessionStore(str(tmp_path))
    for method in [fresh.register_session, fresh.increment_message_count]:
        with pytest.raises(StaleGeneration):
            method("user", "session", delivery_id="turn")
    assert fresh.get_sessions("user") == []
