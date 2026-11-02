"""Real account transactions fence cache writes, snapshots and stale summaries."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chat
from app.knowledge.generations import generation_store, StaleGeneration
from app.memory.session_persistence import SessionPersistence
from app.memory.session_scope import account_session, session_deleted, tombstone_session
from app.memory.session_store import SessionStore
from app.memory.short_term_memory import ShortTermMemoryManager
from app.memory.working_memory import WorkingMemoryManager


def message(content="private", tokens=500):
    from app.models.chat import Message
    return Message(role="user", content=content, timestamp="2026-11-02T00:00:00Z", token_count=tokens)


@pytest.fixture
def caches(monkeypatch, tmp_path):
    values = {}
    backend = Mock()
    backend.setex.side_effect = lambda key, ttl, value: values.__setitem__(key, value)
    backend.get.side_effect = values.get
    backend.delete.side_effect = lambda key: values.pop(key, None)
    backend.exists.side_effect = lambda *keys: sum(key in values for key in keys)
    backend.scan_iter.side_effect = lambda **kw: iter(sorted(key for key in values if key.startswith(kw["match"][:-1])))
    persistence = object.__new__(SessionPersistence)
    persistence._available, persistence._last_attempt, persistence._redis = True, time.monotonic(), backend
    store = SessionStore(str(tmp_path / "sessions"))
    monkeypatch.setattr("app.memory.session_persistence.session_persistence", persistence)
    monkeypatch.setattr("app.memory.session_store.session_store", store)
    monkeypatch.setattr("app.memory.short_term_memory.session_persistence", persistence)
    return persistence, values, ShortTermMemoryManager(), WorkingMemoryManager(), store


def test_scoped_cache_and_defensive_message_copies(caches):
    persistence, values, short, working, _ = caches
    original = message("alice")
    for manager, reader in [(short, short.get_history), (working, working.get_messages)]:
        returned = manager.add_message("same-id", original, user_id="alice")
        returned[0].content = "external mutation"
        manager.add_message("same-id", message("bob"), user_id="bob")
        assert reader("same-id", user_id="alice")[0].content == "alice"
        reader("same-id", user_id="alice")[0].content = "read mutation"
        assert reader("same-id", user_id="bob")[0].content == "bob"
    original.content = "input mutation"
    assert short.get_history("same-id", user_id="alice")[0].content == "alice"
    assert working.get_all_sessions("alice")[0]["title"] == "alice"
    assert working.get_all_sessions("unknown") == []
    assert len(values) == 2
    assert all("alice" not in key and "same-id" not in key for key in values)
    assert persistence.load_messages("same-id", user_id="unknown") is None


def test_legacy_cache_requires_strict_manifest_owner_and_migrates(caches):
    persistence, values, short, _, store = caches
    values["mneme:session:11"] = json.dumps([message("old history").model_dump()])
    assert persistence.load_messages("11", user_id="bob") is None
    store.register_session("alice", "11")
    assert short.get_history("11", user_id="alice")[0].content == "old history"
    short.add_message("11", message("new history"), user_id="alice")
    assert [item.content for item in ShortTermMemoryManager().get_history("11", user_id="alice")] == ["old history", "new history"]
    # Clearing the published v2 key cannot fall back to old legacy text.
    values.pop(persistence._session_key("11", "alice"))
    assert persistence.load_messages("11", user_id="alice") is None


def test_corrupt_legacy_manifest_never_grants_ownership(caches):
    persistence, values, _, _, store = caches
    values["mneme:session:11"] = json.dumps([message().model_dump()])
    with open(store._get_file_path("alice"), "w", encoding="utf-8") as handle:
        handle.write("{broken")
    assert persistence.load_messages("11", user_id="alice") is None
    assert not persistence.available


def test_independent_workers_serialize_appends_and_reload_shared_revision(caches):
    _, _, first, _, _ = caches
    second = ShortTermMemoryManager()
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda i: (first if i % 2 else second).add_message("shared", message(str(i)), user_id="alice"), range(24)))
    assert {item.content for item in first.get_history("shared", user_id="alice")} == {str(i) for i in range(24)}
    assert second.get_history("shared", user_id="alice") == first.get_history("shared", user_id="alice")


def test_redis_outage_invalidates_old_payload_in_other_worker(caches):
    persistence, _, first, _, _ = caches
    first.add_message("s", message("before outage"), user_id="alice")
    other = ShortTermMemoryManager()
    assert len(other.get_history("s", user_id="alice")) == 1
    persistence._redis.setex.side_effect = OSError("private provider details")
    first.add_message("s", message("memory only"), user_id="alice")
    persistence._available = True
    assert other.get_history("s", user_id="alice") == []
    assert len(first.get_history("s", user_id="alice")) == 2


def test_db_rollback_cannot_reuse_an_orphan_redis_revision(caches, monkeypatch):
    persistence, _, _, _, _ = caches
    locked = generation_store.locked

    @contextmanager
    def rollback(user):
        with locked(user) as state:
            yield state
            raise OSError("commit failed")

    with monkeypatch.context() as fault:
        fault.setattr(generation_store, "locked", rollback)
        with pytest.raises(OSError, match="commit failed"):
            persistence.save_messages("s", [message("uncommitted")], user_id="alice")
    persistence._redis.setex.side_effect = OSError("outage")
    persistence.save_messages("s", [message("committed memory-only")], user_id="alice")
    persistence._available = True
    assert persistence.load_messages("s", user_id="alice") is None


def test_tombstone_blocks_all_reads_and_late_writes_after_new_instances(caches):
    persistence, values, short, working, _ = caches
    short.add_message("s", message(), user_id="alice")
    working.add_message("s", message(), user_id="alice")
    short.add_message("s", message("protected"), user_id="bob")
    generation_store.tombstone("alice")
    operations = [lambda: short.add_message("s", message(), user_id="alice"),
                  lambda: short.get_history("s", user_id="alice"),
                  lambda: short.should_summarize("s", user_id="alice"),
                  lambda: working.get_messages("s", user_id="alice"),
                  lambda: working.add_message("s", message(), user_id="alice"),
                  lambda: working.get_all_sessions("alice"),
                  lambda: ShortTermMemoryManager().get_history("s", user_id="alice"),
                  lambda: persistence.save_messages("late", [message()], user_id="alice"),
                  lambda: persistence.load_messages("s", user_id="alice")]
    for operation in operations:
        with pytest.raises(StaleGeneration):
            operation()
    persistence.delete_user_sessions("alice")
    short.clear_user("alice")
    working.clear_user("alice")
    assert len(values) == 1
    assert all(key[0] != "alice" for key in short._store)
    assert working.get_messages("s", user_id="bob") == []
    assert short.get_history("s", user_id="bob")[0].content == "protected"


@pytest.mark.parametrize("stage", ["append", "clear", "delete"])
def test_model_runs_without_lock_and_stale_summary_cannot_publish(caches, monkeypatch, stage):
    _, _, short, _, _ = caches
    for i in range(20):
        short.add_message("s", message(str(i)), user_id="alice")
    started, finish = Event(), Event()

    def model(_):
        started.set()
        assert finish.wait(5), "model test timed out"
        return SimpleNamespace(content="stale summary")

    monkeypatch.setattr("app.memory.short_term_memory.llm", SimpleNamespace(invoke=model))
    with ThreadPoolExecutor(max_workers=1) as executor:
        result = executor.submit(short.summarize, "s", user_id="alice")
        try:
            assert started.wait(5)
            if stage == "append":
                # A different worker updates while the summary model waits.
                ShortTermMemoryManager().add_message("s", message("new turn"), user_id="alice")
            elif stage == "clear":
                short.clear("s", user_id="alice")
            else:
                generation_store.tombstone("alice")
        finally:
            finish.set()
        if stage == "delete":
            with pytest.raises(StaleGeneration):
                result.result(5)
        else:
            result.result(5)
    if stage == "append":
        history = short.get_history("s", user_id="alice")
        assert len(history) == 21 and history[-1].content == "new turn"
    elif stage == "clear":
        assert short.get_history("s", user_id="alice") == []


def test_failed_generation_read_never_returns_cached_private_history(caches, monkeypatch):
    _, _, short, working, _ = caches
    short.add_message("s", message(), user_id="alice")
    working.add_message("s", message(), user_id="alice")

    @contextmanager
    def offline(_):
        raise OSError("db offline")
        yield

    monkeypatch.setattr(generation_store, "locked", offline)
    for operation in [lambda: short.get_history("s", user_id="alice"), lambda: working.get_messages("s", user_id="alice")]:
        with pytest.raises(OSError, match="db offline"):
            operation()


def test_account_scope_cannot_reenter_under_another_owner():
    with account_session("alice"):
        with pytest.raises(RuntimeError, match="切换账号"):
            with account_session("bob"):
                pass


@pytest.mark.parametrize("fault", ["noop", "scan"])
def test_account_cleanup_verifies_scoped_orphans_and_retries(caches, monkeypatch, fault):
    persistence, values, _, _, _ = caches
    persistence.save_messages("unregistered", [message()], user_id="alice")
    generation_store.tombstone("alice")
    with monkeypatch.context() as failure:
        if fault == "noop":
            failure.setattr(persistence._redis, "delete", lambda key: 0)
        else:
            failure.setattr(persistence._redis, "scan_iter", Mock(side_effect=OSError("private")))
        with pytest.raises(RuntimeError, match="Redis 账号会话删除失败"):
            persistence.delete_user_sessions("alice")
    persistence._available = True
    persistence.delete_user_sessions("alice")
    assert not values


def test_history_api_requires_owner_and_does_not_read_default_namespace(caches, monkeypatch):
    _, _, short, working, _ = caches
    short.add_message("s", message("standalone default"))
    short.add_message("s", message("alice"), user_id="alice")
    monkeypatch.setattr(chat, "short_term_memory", short)
    monkeypatch.setattr(chat, "working_memory", working)
    app = FastAPI()
    app.include_router(chat.router)
    with TestClient(app) as client:
        assert client.get("/api/v1/session/s").status_code == 422
        assert client.get("/api/v1/session/s?user_id=bob").json()["messages"] == []
        assert client.get("/api/v1/session/s?user_id=alice").json()["messages"][0]["content"] == "alice"


def test_single_session_fence_blocks_existing_and_cold_caches_and_manifest(caches):
    persistence, values, short, working, store = caches
    for user, sid in [("alice", "deleted"), ("alice", "kept"), ("bob", "deleted")]:
        store.register_session(user, sid)
        short.add_message(sid, message(user + sid), user_id=user)
        working.add_message(sid, message(user + sid), user_id=user)
    tombstone_session("alice", "deleted")
    for operation in [lambda: short.get_history("deleted", user_id="alice"),
                      lambda: ShortTermMemoryManager().get_history("deleted", user_id="alice"),
                      lambda: working.get_messages("deleted", user_id="alice"),
                      lambda: working.add_message("deleted", message(), user_id="alice"),
                      lambda: persistence.load_messages("deleted", user_id="alice"),
                      lambda: persistence.save_messages("deleted", [message()], user_id="alice"),
                      lambda: store.register_session("alice", "deleted"),
                      lambda: store.update_title("alice", "deleted", "late"),
                      lambda: store.increment_message_count("alice", "deleted"),
                      lambda: store._save("alice", {"deleted": {}})]:
        with pytest.raises(StaleGeneration, match="会话已删除"):
            operation()
    assert not generation_store.snapshot("alice").get("deleted")
    assert [s["id"] for s in store.get_sessions("alice")] == ["kept"]
    assert store.get_session_count("alice") == 1
    assert [s["id"] for s in working.get_all_sessions("alice")] == ["kept"]
    short.clear("deleted", user_id="alice")
    working.clear("deleted", user_id="alice")
    store.purge_deleted_session("alice", "deleted")
    assert store.cleanup_session_ids("alice") == ["kept"]
    assert persistence.count_sessions(["deleted"], user_id="alice") == 0
    assert len(values) == 2
    assert short.get_history("kept", user_id="alice")[0].content == "alicekept"
    assert short.get_history("deleted", user_id="bob")[0].content == "bobdeleted"


@pytest.mark.parametrize("fault", ["redis", "silent_redis", "file", "silent_file"])
def test_single_session_api_retains_scope_after_failure_then_retries(caches, monkeypatch, fault):
    persistence, values, short, working, store = caches
    for sid in ["removed", "protected"]:
        store.register_session("alice", sid)
        short.add_message(sid, message(sid), user_id="alice")
    for name, value in [("short_term_memory", short), ("working_memory", working),
                        ("session_persistence", persistence), ("session_store", store)]:
        monkeypatch.setattr(chat, name, value)
    app = FastAPI()
    app.include_router(chat.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        with monkeypatch.context() as failure:
            if fault == "redis":
                failure.setattr(persistence._redis, "delete", Mock(side_effect=OSError("offline")))
            elif fault == "silent_redis":
                failure.setattr(persistence._redis, "delete", lambda _: 0)
            elif fault == "file":
                failure.setattr(store, "_write", Mock(side_effect=OSError("disk")))
            else:
                failure.setattr(store, "_write", lambda *args: None)
            assert client.delete("/api/v1/session/removed?user_id=alice").status_code == 500
        state = generation_store.snapshot("alice")
        assert session_deleted(state, "removed") and not state.get("deleted")
        assert set(store.cleanup_session_ids("alice")) == {"removed", "protected"}
        with pytest.raises(StaleGeneration):
            ShortTermMemoryManager().add_message("removed", message("late"), user_id="alice")
        persistence._available = True
        assert client.delete("/api/v1/session/removed?user_id=alice").json() == {"deleted": True, "session_id": "removed"}
        assert client.delete("/api/v1/session/removed?user_id=alice").status_code == 200
    assert store.cleanup_session_ids("alice") == ["protected"]
    assert len(values) == 1


def test_single_session_tombstone_invalidates_summary_during_model_call(caches, monkeypatch):
    _, _, short, _, _ = caches
    for i in range(20):
        short.add_message("s", message(str(i)), user_id="alice")
    entered, release = Event(), Event()

    def model(_):
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(content="obsolete summary")

    monkeypatch.setattr("app.memory.short_term_memory.llm", SimpleNamespace(invoke=model))
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(short.summarize, "s", user_id="alice")
        try:
            assert entered.wait(5)
            tombstone_session("alice", "s")
            short.clear("s", user_id="alice")
        finally:
            release.set()
        with pytest.raises(StaleGeneration, match="会话已删除"):
            result.result(5)


@pytest.mark.parametrize("corrupt", [[], {"anything": False}, {"anything": "true"}])
def test_corrupt_session_tombstones_fail_closed(caches, corrupt):
    _, _, short, _, _ = caches
    short.add_message("s", message(), user_id="alice")
    with generation_store.locked("alice") as state:
        state["deleted_sessions"] = corrupt
    with pytest.raises(ValueError, match="围栏损坏"):
        short.get_history("s", user_id="alice")
    with pytest.raises(ValueError, match="围栏损坏"):
        tombstone_session("alice", "s")


def test_single_session_cleanup_requires_committed_tombstone(caches):
    _, _, _, _, store = caches
    store.register_session("alice", "s")
    with pytest.raises(ValueError, match="需要持久删除围栏"):
        store.purge_deleted_session("alice", "s")
    assert store.cleanup_session_ids("alice") == ["s"]
