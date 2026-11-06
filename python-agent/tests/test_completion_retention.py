"""Real SQL expiry, replay fencing and bounded completion admission."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock

import pytest

from app.core.time import utc_now
from app.knowledge.generations import generation_store
from app.memory import completion, completion_retention as retention
from app.memory.session_history import session_key
from app.memory.session_retention import SessionHistoryRetention
from app.memory.session_scope import account_session
from app.memory.session_store import session_store
from app.memory.short_term_memory import short_term_memory
from app.memory.reflection_scheduler import ReflectionScheduler
from tests.test_memory_completion import setup as completion_setup, entry  # noqa: F401
from tests.test_reflection_scheduler import FakeRedis


@pytest.fixture
def setup(request):
    return request.getfixturevalue("completion_setup")


def job(at, *, legacy=False):
    result = {"fingerprint": "a" * 64, "created_at": at.isoformat(), "phases": {"history": True}}
    if not legacy:
        result["reference_time"] = at.isoformat()
    return result


def policy(monkeypatch, **kwargs):
    monkeypatch.setattr(retention, "settings", replace(retention.settings, **kwargs))


def test_actual_worker_reclaims_sql_only_jobs_and_preserves_legacy_and_other_accounts():
    now = utc_now()
    old = now - timedelta(days=31)
    with account_session("alice") as state:
        state["memory_completions"] = {"expired": {"old": job(old)}, "active": {"new": job(now), "legacy": job(old, legacy=True)}}
        state["libraries"] = {"preserve": True}
    with account_session("bob") as state:
        state["memory_completions"] = {"s": {"new": job(now)}}
    before = generation_store.snapshot("bob")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: SessionHistoryRetention().run_batch(), range(2)))
    assert sum(row["expired"] for row in results) == 1
    after = generation_store.snapshot("alice")
    assert set(after["memory_completions"]) == {"active"}
    assert set(after["memory_completions"]["active"]) == {"new", "legacy"}
    assert after["libraries"] == {"preserve": True}
    assert generation_store.snapshot("bob") == before
    assert SessionHistoryRetention().run_batch()["expired"] == 0
    assert generation_store.snapshot("alice") == after


def test_retired_cutoff_survives_clock_rollback_and_policy_extension(monkeypatch):
    now = utc_now()
    at = now - timedelta(days=31)
    state = {"memory_completions": {"s": {"old": job(at)}}}
    assert retention.expire_user(state) == 1
    retired = state["memory_completion_retired_before"]
    monkeypatch.setattr(retention, "utc_now", lambda: now - timedelta(days=60))
    policy(monkeypatch, memory_completion_retention_days=180)
    assert retention.expire_user(state) == 0
    assert state["memory_completion_retired_before"] == retired
    with pytest.raises(ValueError, match="保留期"):
        retention.require_current(state, at.isoformat())


@pytest.mark.parametrize("corrupt", [None, [], "bad-time"])
def test_invalid_inventory_never_partially_removes_jobs(corrupt):
    old = utc_now() - timedelta(days=31)
    state = {"memory_completions": {"s": {"old": job(old), "broken": job(old)}}}
    state["memory_completions"]["s"]["broken"]["reference_time"] = corrupt
    before = deepcopy(state)
    with pytest.raises(ValueError):
        retention.expire_user(state)
    assert state == before


def test_worker_bad_account_rolls_back_and_continues():
    old = utc_now() - timedelta(days=31)
    for user in ("alice", "bob"):
        with account_session(user) as state:
            state["memory_completions"] = {"s": {"old": job(old)}}
    with account_session("alice") as state:
        state["memory_completions"]["s"]["bad"] = None
    before = generation_store.snapshot("alice")
    assert SessionHistoryRetention().run_batch() == {"scanned": 2, "expired": 1, "failed": 1}
    assert generation_store.snapshot("alice") == before
    assert generation_store.snapshot("bob")["memory_completions"] == {}


def test_count_admission_rejects_before_assistant_history_or_provider(setup, monkeypatch):
    request, _, _ = setup
    policy(monkeypatch, memory_completion_max_jobs=1)
    with account_session("owner") as state:
        state["memory_completions"] = {"legacy": {"protected": job(utc_now(), legacy=True)}}
    before = generation_store.snapshot("owner")
    with pytest.raises(ValueError, match="容量已满"):
        completion.complete_memory(request)
    assert generation_store.snapshot("owner") == before
    completion._extract.assert_not_called()
    assert session_store.get_sessions("owner")[0]["message_count"] == 1
    assert [m.content for m in short_term_memory.get_history("session", user_id="owner")] == ["question"]


def test_bytes_admission_and_retry_preserve_one_history_effect(setup, monkeypatch):
    request, _, _ = setup
    extract = Mock(return_value=[{**entry(), "content": "私" * 500}])
    monkeypatch.setattr(completion, "_extract", extract)
    policy(monkeypatch, memory_completion_max_bytes=1000)
    with pytest.raises(ValueError, match="容量已满"):
        completion.complete_memory(request)
    checkpoints = generation_store.snapshot("owner")["memory_completions"][session_key("session")]
    assert next(iter(checkpoints.values()))["phases"] == {"history": True}
    policy(monkeypatch, memory_completion_max_bytes=100000)
    completion.complete_memory(request)
    assert session_store.get_sessions("owner")[0]["message_count"] == 2
    assert len(short_term_memory.get_history("session", user_id="owner")) == 2


def test_expiry_during_extraction_cannot_recreate_checkpoint_or_write_vectors(setup, monkeypatch):
    request, store, _ = setup
    future = utc_now() + timedelta(days=31)
    def extract(_):
        monkeypatch.setattr(retention, "utc_now", lambda: future)
        assert SessionHistoryRetention().run_batch()["expired"] == 1
        return [entry()]
    monkeypatch.setattr(completion, "_extract", extract)
    with pytest.raises(ValueError, match="保留期"):
        completion.complete_memory(request)
    assert generation_store.snapshot("owner")["memory_completions"] == {}
    assert store.count_user_memories("owner") == 0
    with pytest.raises(ValueError, match="保留期"):
        completion.complete_memory(request)


def test_expiry_during_embedding_refuses_vector_commit(setup, monkeypatch):
    request, store, _ = setup
    plan = completion._plan(request, entry(), "expired-effect")
    from app.utils import embedding
    original = embedding.embeddings
    future = utc_now() + timedelta(days=31)
    def embed(texts):
        vectors = original(texts)
        monkeypatch.setattr(retention, "utc_now", lambda: future)
        return vectors
    monkeypatch.setattr(embedding, "embeddings", embed)
    with pytest.raises(ValueError, match="保留期"):
        completion._apply(request, plan, "expired-effect")
    assert store.count_user_memories("owner") == 0


def test_expiry_during_summary_preserves_the_committed_history(setup, monkeypatch):
    request, _, _ = setup
    from app.memory import short_term_memory as module
    policy(monkeypatch, memory_completion_retention_days=1)
    monkeypatch.setattr(module, "settings", replace(module.settings, working_memory_max_tokens=100))
    for index in range(6):
        short_term_memory.add_message("session", module.Message(role="user", content="history " + str(index),
                                      timestamp=request.reference_time, token_count=60), user_id="owner")
    before = short_term_memory.get_history("session", user_id="owner")
    def summarize(_):
        monkeypatch.setattr(retention, "utc_now", lambda: utc_now() + timedelta(days=2))
        return Mock(content="model summary")
    monkeypatch.setattr(module, "llm", Mock(invoke=summarize))
    with pytest.raises(ValueError, match="保留期"):
        short_term_memory.summarize("session", user_id="owner", raise_on_error=True,
                                   commit_guard=lambda state: retention.require_current(state, request.reference_time))
    assert short_term_memory.get_history("session", user_id="owner") == before


def test_lost_vector_ack_then_expiry_and_user_delete_cannot_resurrect(setup, monkeypatch):
    request, store, _ = setup
    monkeypatch.setattr(completion, "_extract", Mock(return_value=[entry()]))
    upsert = store._collection.upsert
    def lost_ack(**kwargs):
        upsert(**kwargs)
        raise OSError("lost acknowledgement")
    with monkeypatch.context() as fault:
        fault.setattr(store._collection, "upsert", lost_ack)
        with pytest.raises(OSError):
            completion.complete_memory(request)
    target = store.get_by_category("owner", "preference")[0]
    store.delete_memory(target["id"])
    monkeypatch.setattr(retention, "utc_now", lambda: utc_now() + timedelta(days=31))
    assert SessionHistoryRetention().run_batch()["expired"] == 1
    with pytest.raises(ValueError, match="保留期"):
        completion.complete_memory(request)
    assert store.count_user_memories("owner") == 0
    assert generation_store.snapshot("owner")["memory_completions"] == {}


def test_completion_real_reflection_transactions_commit_before_marker_cleanup(setup, monkeypatch):
    request, _, _ = setup
    from app.memory import reflection_scheduler as module
    fake = FakeRedis()
    scheduler = ReflectionScheduler(redis_client=fake)
    original_delete = fake.delete
    def committed_delete(marker):
        # A separate SQL connection must observe the receipt before Redis DEL.
        assert generation_store.snapshot("owner")["reflection_deliveries"]
        return original_delete(marker)
    monkeypatch.setattr(fake, "delete", committed_delete)
    monkeypatch.setattr(module, "reflection_scheduler", scheduler)
    result = completion.complete_memory(request)
    assert completion.complete_memory(request) == result
    assert fake.values[scheduler._counter_key("owner")] == 1
    assert not fake.deliveries


def test_expired_guard_precedes_manifest_and_reflection_mutations(setup, monkeypatch):
    request, _, _ = setup
    future = utc_now() + timedelta(days=31)
    monkeypatch.setattr(retention, "utc_now", lambda: future)
    def guard(state):
        retention.require_current(state, request.reference_time)
    fake = FakeRedis()
    scheduler = ReflectionScheduler(redis_client=fake)
    before = generation_store.snapshot("owner")
    for action in (
        lambda: session_store.increment_message_count("owner", "session", delivery_id="turn", commit_guard=guard),
        lambda: scheduler.record_session("owner", "session", "turn", commit_guard=guard),
        lambda: scheduler.check_and_trigger("owner", commit_guard=guard),
    ):
        with pytest.raises(ValueError, match="保留期"):
            action()
    assert generation_store.snapshot("owner") == before
    assert not fake.values and not fake.stream and not fake.deliveries
    assert session_store.get_sessions("owner")[0]["message_count"] == 1


def test_legacy_binding_requires_matching_frozen_input(setup):
    request, _, _ = setup
    checkpoints = completion.Checkpoints(request)
    checkpoints.phase("init", lambda: True)
    with account_session("owner") as state:
        state["memory_completions"][session_key("session")][checkpoints.key].pop("reference_time")
    before = generation_store.snapshot("owner")
    with pytest.raises(ValueError, match="内容冲突"):
        completion.complete_memory(request.model_copy(update={"answer": "different"}))
    assert generation_store.snapshot("owner") == before
    completion.complete_memory(request)
    assert generation_store.snapshot("owner")["memory_completions"][session_key("session")][checkpoints.key]["reference_time"] == request.reference_time


def test_version_evidence_is_upper_bound_and_future_requests_fail(monkeypatch):
    policy(monkeypatch, memory_completion_retention_days=180, memory_version_retention_days=2)
    now = utc_now()
    for at in (now - timedelta(days=3), now + timedelta(minutes=6)):
        with pytest.raises(ValueError):
            retention.require_current({}, at.isoformat())
