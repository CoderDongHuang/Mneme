"""Expiry without history reads, using real SQL locks and commits."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import timedelta
import logging
from threading import Event

import pytest

from app.core.time import utc_now
from app.knowledge.generations import generation_store, StaleGeneration
from app.memory import session_history
from app.memory.session_persistence import session_persistence
from app.memory.session_retention import SessionHistoryRetention
from app.memory.session_scope import account_session, session_revision, tombstone_session
from app.memory.short_term_memory import ShortTermMemoryManager
from app.models.chat import Message


@pytest.fixture(autouse=True)
def offline_redis(monkeypatch):
    monkeypatch.setattr(session_persistence, "_ensure_connection", lambda: False)


def seed(user, session="s", *, expired=True):
    ShortTermMemoryManager().add_message(session, Message(role="user", content="PRIVATE_HISTORY_CANARY", timestamp=utc_now().isoformat()),
                                       user_id=user, delivery_id="receipt")
    if expired:
        with account_session(user) as state:
            state["session_histories"][session_history.session_key(session)]["expires_at"] = (
                utc_now() - timedelta(seconds=1)).timestamp()


def test_unread_orphans_expire_without_models_or_redis_and_old_mirror_cannot_return():
    seed("alice")
    seed("alice", "active", expired=False)
    seed("bob", expired=False)
    before = generation_store.snapshot("alice")
    other = generation_store.snapshot("bob")
    with account_session("alice") as state:
        state["libraries"] = {"preserve": {"deleted": True}}
        state["deleted_sessions"] = {session_history.session_key("erased"): True}
    assert SessionHistoryRetention().run_batch() == {"scanned": 2, "expired": 1, "failed": 0}
    after = generation_store.snapshot("alice")
    key = session_history.session_key("s")
    assert after["session_histories"][key] == {"expired": True}
    assert session_revision(after, "s") != session_revision(before, "s")
    assert after["session_histories"][session_history.session_key("active")] == before["session_histories"][session_history.session_key("active")]
    assert after["libraries"] == {"preserve": {"deleted": True}}
    assert after["deleted_sessions"][session_history.session_key("erased")] is True
    assert generation_store.snapshot("bob") == other
    # No Redis and no manifest exist. Expired bucket is not mistaken for legacy.
    assert ShortTermMemoryManager().get_history("s", user_id="alice") == []
    assert SessionHistoryRetention().run_batch()["expired"] == 0
    assert generation_store.snapshot("alice") == after  # Does not rotate token again.


def test_keyset_cycles_include_no_qdrant_users_and_do_not_load_all_states():
    for user in ("", "10", "2", "z", "中文"):
        seed(user)
    assert generation_store.user_page(limit=2) == ["", "10"]
    assert generation_store.user_page("10", limit=2) == ["2", "z"]
    worker = SessionHistoryRetention(batch_size=2)
    assert [worker.run_batch()["expired"] for _ in range(4)] == [2, 2, 1, 0]
    seed("new")  # Insert behind current cursor; reached on the next cycle.
    assert sum(worker.run_batch()["expired"] for _ in range(3)) == 1


@pytest.mark.parametrize("stage", ["rollback", "lost_ack"])
def test_sql_failure_remains_retryable_without_counting_unacknowledged_commits(monkeypatch, stage):
    seed("alice")
    before = generation_store.snapshot("alice")
    original = generation_store.locked

    @contextmanager
    def fail(user):
        with original(user) as state:
            yield state
            if stage == "rollback":
                raise OSError("PRIVATE_SQL_CANARY")
        raise OSError("PRIVATE_SQL_CANARY")

    worker = SessionHistoryRetention()
    with monkeypatch.context() as fault:
        fault.setattr(generation_store, "locked", fail)
        assert worker.run_batch() == {"scanned": 1, "expired": 0, "failed": 1}
    if stage == "rollback":
        assert generation_store.snapshot("alice") == before
    assert worker.run_batch() == {"scanned": 1, "expired": int(stage == "rollback"), "failed": 0}
    assert generation_store.snapshot("alice")["session_histories"][session_history.session_key("s")] == {"expired": True}


@pytest.mark.parametrize("corrupt", ["body", "key", "revision"])
def test_corrupt_user_rolls_back_all_expiries_without_blocking_later_users(monkeypatch, corrupt, caplog):
    seed("alice", "first")
    seed("alice", "second")
    seed("bob")
    with account_session("alice") as state:
        key = session_history.session_key("second")
        if corrupt == "body":
            state["session_histories"][key]["messages"] = "PRIVATE_CORRUPTION_CANARY"
        elif corrupt == "key":
            state["session_histories"]["PRIVATE_CORRUPTION_CANARY"] = state["session_histories"].pop(key)
        else:
            state["session_memory_revisions"][key] = "PRIVATE_CORRUPTION_CANARY"
    before = generation_store.snapshot("alice")
    # Capture through a normal logger: production handler has propagate=False.
    monkeypatch.setattr("app.memory.session_retention.logger", logging.getLogger("retention_test"))
    caplog.set_level(logging.INFO)
    worker = SessionHistoryRetention(batch_size=1)
    assert worker.run_batch()["failed"] == 1
    assert generation_store.snapshot("alice") == before
    assert worker.run_batch() == {"scanned": 1, "expired": 1, "failed": 0}
    assert worker.run_batch()["scanned"] == 0
    assert worker.run_batch()["failed"] == 1  # Revisit corrupt account next cycle.
    assert "PRIVATE_" not in caplog.text and "alice" not in caplog.text
    assert "history_retention" in caplog.text


def test_scan_failure_retries_same_cursor(monkeypatch):
    seed("alice")
    worker = SessionHistoryRetention(batch_size=1)
    with monkeypatch.context() as fault:
        fault.setattr(generation_store, "user_page", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("private")))
        assert worker.run_batch() == {"scanned": 0, "expired": 0, "failed": 1}
    assert worker.run_batch() == {"scanned": 1, "expired": 1, "failed": 0}


def test_concurrent_replicas_expire_once_and_deleted_session_stays_fenced():
    seed("alice")
    tombstone_session("alice", "s")
    workers = [SessionHistoryRetention(), SessionHistoryRetention()]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda w: w.run_batch(), workers))
    assert sum(r["expired"] for r in results) == 1
    assert sum(r["failed"] for r in results) == 0
    with pytest.raises(StaleGeneration):
        ShortTermMemoryManager().add_message("s", Message(role="user", content="late", timestamp=utc_now().isoformat()), user_id="alice", delivery_id="receipt")


def test_renewal_after_scan_before_row_lock_is_not_lost(monkeypatch):
    seed("alice")
    scanned, release = Event(), Event()
    original = generation_store.user_page

    def pause(*args, **kwargs):
        users = original(*args, **kwargs)
        scanned.set()
        assert release.wait(10)
        return users

    monkeypatch.setattr(generation_store, "user_page", pause)
    with ThreadPoolExecutor(max_workers=1) as pool:
        result = pool.submit(SessionHistoryRetention().run_batch)
        try:
            assert scanned.wait(10)
            ShortTermMemoryManager().add_message("s", Message(role="user", content="renewed", timestamp=utc_now().isoformat()), user_id="alice", delivery_id="new")
            renewed = generation_store.snapshot("alice")
        finally:
            release.set()
        assert result.result(10) == {"scanned": 1, "expired": 0, "failed": 0}
    assert generation_store.snapshot("alice") == renewed


@pytest.mark.parametrize("size", [0, -1, 1001, True, 1.5])
def test_invalid_scan_limits_cannot_create_unbounded_queries(size):
    with pytest.raises(ValueError):
        generation_store.user_page(limit=size)
    with pytest.raises(ValueError):
        SessionHistoryRetention(batch_size=size)


def test_scheduler_registers_bounded_coalesced_expiry_job(monkeypatch):
    from app.memory.reflection_scheduler import ReflectionScheduler
    scheduler = ReflectionScheduler()
    jobs = []
    monkeypatch.setattr(scheduler.scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler.scheduler, "add_job", lambda *a, **kw: jobs.append((a, kw)))
    monkeypatch.setattr("app.memory.reflection_scheduler.threading.Thread.start", lambda _: None)
    scheduler.start()
    registered = [j for j in jobs if j[1].get("id") == "session_history_retention"]
    assert len(registered) == 1
    assert registered[0][1]["max_instances"] == 1 and registered[0][1]["coalesce"] is True
    assert registered[0][1]["trigger"].interval.total_seconds() == 60
