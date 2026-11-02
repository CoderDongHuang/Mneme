"""Storage races and independent deletion readback, without provider calls."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event

import pytest

from app.agents import trace_store
from app.core import privacy
from app.knowledge.generations import GenerationStore, StaleGeneration, generation_store


@pytest.fixture
def stores(tmp_path, monkeypatch):
    policy = privacy.PrivacyStore(str(tmp_path / "privacy.sqlite3"))
    monkeypatch.setattr(privacy, "privacy_store", policy)
    monkeypatch.setattr(trace_store, "privacy_store", policy)
    return trace_store.AgentTraceStore(str(tmp_path / "trace.sqlite3")), policy


def seed(trace, policy, user):
    policy.save(user, True, 1)
    trace.record(user, "session", "node", "ok", {"content": "private"})


def test_deleted_account_cannot_recreate_records_or_regain_default_consent(stores):
    trace, policy = stores
    for user in ("deleted", "other"):
        seed(trace, policy, user)
    generation_store.tombstone("deleted")
    assert trace.delete_user("deleted") == 1
    policy.delete("deleted")
    assert GenerationStore(generation_store.path).snapshot("deleted")["deleted"]
    next_trace = trace_store.AgentTraceStore(str(trace.path))
    next_policy = privacy.PrivacyStore(str(policy.path))
    next_trace.record("deleted", "session", "late", "ok")
    with pytest.raises(StaleGeneration):
        next_policy.save("deleted", True, 1)
    with pytest.raises(StaleGeneration):
        privacy.require_cloud_processing("deleted")
    assert not next_policy.get("deleted")["cloud_allowed"]
    assert next_trace.count_user("deleted") == next_policy.count_user("deleted") == 0
    assert trace.count_user("other") == policy.count_user("other") == 1
    privacy.require_cloud_processing("new-account")


@pytest.mark.parametrize("kind", ["trace", "privacy"])
def test_in_progress_storage_write_finishes_before_tombstone_and_cleanup(stores, monkeypatch, kind):
    trace, policy = stores
    entered, release, deleting = Event(), Event(), Event()
    target, name = (trace, "_insert_record") if kind == "trace" else (policy, "_save")
    original = getattr(target, name)

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(target, name, delayed)

    def cleanup():
        deleting.set()
        generation_store.tombstone("racing")
        trace.delete_user("racing")
        policy.delete("racing")

    with ThreadPoolExecutor(max_workers=2) as pool:
        write = pool.submit(trace.record, "racing", "s", "n", "ok") if kind == "trace" else pool.submit(policy.save, "racing", True, 1)
        try:
            assert entered.wait(5)
            deletion = pool.submit(cleanup)
            assert deleting.wait(5)
            assert not deletion.done()
        finally:
            release.set()
        write.result(5)
        deletion.result(5)
    assert trace.count_user("racing") == policy.count_user("racing") == 0


@pytest.mark.parametrize("kind", ["trace", "privacy"])
@pytest.mark.parametrize("failure", ["noop", "read_error"])
def test_delete_does_not_acknowledge_noop_or_failed_readback(stores, monkeypatch, kind, failure):
    trace, policy = stores
    seed(trace, policy, "deleted")
    seed(trace, policy, "other")
    generation_store.tombstone("deleted")
    target, name = (trace, "_connect") if kind == "trace" else (policy, "_local")
    original = getattr(target, name)

    class Fault:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, *args):
            if failure == "noop" and sql.startswith("DELETE"):
                return self.conn.execute("SELECT 1")
            if failure == "read_error" and sql.startswith("SELECT COUNT"):
                raise RuntimeError("read unavailable")
            return self.conn.execute(sql, *args)

    @contextmanager
    def broken():
        with original() as conn:
            yield Fault(conn)

    with monkeypatch.context() as fault:
        fault.setattr(target, name, broken)
        with pytest.raises(RuntimeError, match="残留|read unavailable"):
            target.delete_user("deleted") if kind == "trace" else target.delete("deleted")
    target.delete_user("deleted") if kind == "trace" else target.delete("deleted")
    assert target.count_user("deleted") == 0
    assert target.count_user("other") == 1
    assert generation_store.snapshot("deleted")["deleted"]


def test_unavailable_manifest_never_writes_or_restores_consent(stores, tmp_path, monkeypatch):
    trace, policy = stores
    monkeypatch.setattr(generation_store, "path", tmp_path)
    for call in (lambda: trace.record("user", "s", "n", "ok"),
                 lambda: policy.save("user", True, 1), lambda: privacy.require_cloud_processing("user")):
        with pytest.raises(Exception, match="unable to open"):
            call()
    assert trace.count_user("user") == policy.count_user("user") == 0
