"""Durable completion replay against actual SQL checkpoints and local Qdrant."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import Mock
import uuid

import pytest

from app.core.time import utc_now
from app.knowledge.generations import generation_store, StaleGeneration
from app.memory import completion, memory_store as store_module, version_store
from app.memory.long_term_memory import long_term_memory
from app.memory.memory_store import MemoryVectorStore, memory_store
from app.memory.reflection_scheduler import reflection_scheduler
from app.memory.session_history import count_user, session_key
from app.memory.session_persistence import session_persistence
from app.memory.session_scope import account_session, tombstone_session
from app.memory.session_store import session_store
from app.memory.short_term_memory import short_term_memory
from app.memory.version_store import MemoryVersionStore
from app.models.chat import MemoryCompletion, Message
from app.utils.embedding import embeddings


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(session_store, "_data_dir", str(tmp_path))
    versions = MemoryVersionStore(str(tmp_path / "versions.sqlite3"))
    monkeypatch.setattr(version_store, "memory_version_store", versions)
    monkeypatch.setattr(store_module, "memory_version_store", versions)
    store = object.__new__(MemoryVectorStore)
    name = "completion-" + uuid.uuid4().hex
    store._collection = memory_store._client.get_or_create_collection(
        name, metadata={"embedding_profile": embeddings.profile()}, embedding_function=embeddings)
    monkeypatch.setattr(long_term_memory, "_store", store)
    monkeypatch.setattr(session_persistence, "_ensure_connection", lambda: False)
    monkeypatch.setattr(reflection_scheduler, "record_session", Mock())
    monkeypatch.setattr(reflection_scheduler, "check_and_trigger", Mock())
    now = utc_now()
    history = [Message(role="assistant", content="previous answer", timestamp=(now - timedelta(minutes=20)).isoformat()),
               Message(role="user", content="question", timestamp=now.isoformat())]
    request = MemoryCompletion(user_id="owner", session_id="session", delivery_id="turn",
                               reference_time=now.isoformat(), history=history, answer="saved answer")
    short_term_memory.add_message("session", history[-1], user_id="owner", delivery_id="turn")
    session_store.register_session("owner", "session", delivery_id="turn")
    monkeypatch.setattr(completion, "_extract", Mock(return_value=[]))
    try:
        yield request, store, versions
    finally:
        memory_store._client.delete_collection(name)


def entry(category="preference", confidence=.9):
    return {"category": category, "content": "calculus/derivatives" if category == "progress" else "prefer diagrams",
            "topic": "calculus", "confidence": confidence, "is_new": True}


@pytest.mark.parametrize("stage", ["extraction", "reflection", "summary"])
def test_failed_phase_retries_from_cold_checkpoints_without_repeating_completed_work(setup, monkeypatch, stage):
    request, store, _ = setup
    extract = Mock(return_value=[entry(confidence=.7)])
    monkeypatch.setattr(completion, "_extract", extract)
    summarize = Mock()
    monkeypatch.setattr(short_term_memory, "should_summarize", lambda *a, **k: True)
    monkeypatch.setattr(short_term_memory, "summarize", summarize)
    failure = {"extraction": extract, "reflection": reflection_scheduler.check_and_trigger, "summary": summarize}[stage]
    failure.side_effect = RuntimeError("private provider body")
    with pytest.raises(RuntimeError):
        completion.complete_memory(request)
    assert len(short_term_memory.get_history("session", user_id="owner")) == 2
    failure.side_effect = None
    result = completion.complete_memory(MemoryCompletion.model_validate(request.model_dump()))
    assert result["completed"] and len(result["pending_memories"]) == 1
    before = generation_store.snapshot("owner")
    assert completion.complete_memory(request) == result
    assert generation_store.snapshot("owner") == before
    assert extract.call_count == (2 if stage == "extraction" else 1)
    assert session_store.get_sessions("owner")[0]["message_count"] == 2
    assert store.count_user_memories("owner") == 0


@pytest.mark.parametrize("category", ["preference", "weak_point", "progress"])
@pytest.mark.parametrize("later", ["none", "edit", "delete"])
def test_lost_vector_ack_replay_preserves_one_effect_and_subsequent_user_intent(setup, monkeypatch, category, later):
    request, store, versions = setup
    if category == "weak_point":
        store.add_memory("owner", category, "original weak point", topic="calculus")
    monkeypatch.setattr(completion, "_extract", Mock(return_value=[entry(category)]))
    upsert = store._collection.upsert

    def lose_ack(**kwargs):
        upsert(**kwargs)
        raise OSError("response lost after durable upsert")

    with monkeypatch.context() as fault:
        fault.setattr(store._collection, "upsert", lose_ack)
        with pytest.raises(OSError):
            completion.complete_memory(request)
    current = store.get_by_category("owner", category)[0]
    assert current["importance"] == pytest.approx(.6 if category == "weak_point" else .5)
    if later == "edit":
        store.update_memory(current["id"], content="user edited content")
    elif later == "delete":
        store.delete_memory(current["id"])
        assert versions.list_versions("owner", current["id"])
    completion.complete_memory(request)
    rows = store.get_by_category("owner", category)
    if later == "delete":
        assert rows == []
    else:
        assert len(rows) == 1
        assert rows[0]["importance"] == current["importance"]
        assert rows[0]["content"] == ("user edited content" if later == "edit" else current["content"])


def test_parallel_extraction_consumes_first_committed_plan_once(setup, monkeypatch):
    request, store, _ = setup
    barrier = Barrier(2)

    def extract(_):
        barrier.wait(5)
        return [entry()]

    monkeypatch.setattr(completion, "_extract", extract)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: completion.complete_memory(request), range(2)))
    assert all(row["completed"] for row in results)
    assert len(store.get_by_category("owner", "preference")) == 1
    assert session_store.get_sessions("owner")[0]["message_count"] == 2


@pytest.mark.parametrize("scope", ["session", "account"])
def test_deletion_clears_orphan_checkpoints_and_fences_provider_inflight(setup, monkeypatch, scope):
    request, store, _ = setup
    checkpoints = completion.Checkpoints(request)
    checkpoints.phase("orphan", lambda: {"private": "frozen input"})
    assert count_user("owner") == 2  # History plus an independently counted job bucket.

    def delete_during_provider(_):
        if scope == "session":
            tombstone_session("owner", "session")
        else:
            generation_store.tombstone("owner")
            with monkeypatch.context() as online:
                online.setattr(session_persistence, "_ensure_connection", lambda: True)
                online.setattr(session_persistence, "_redis", Mock(scan_iter=lambda **_: iter([])))
                session_persistence.delete_user_sessions("owner")
        return [entry()]

    monkeypatch.setattr(completion, "_extract", delete_during_provider)
    with pytest.raises(StaleGeneration):
        completion.complete_memory(request)
    assert not generation_store.snapshot("owner").get("memory_completions", {})
    assert store.count_user_memories("owner") == 0


def test_conflicting_delivery_and_expired_unacknowledged_plan_fail_closed(setup):
    request, _, _ = setup
    checkpoints = completion.Checkpoints(request)
    checkpoints.phase("plan:pending", lambda: {"id": "target"})
    with pytest.raises(ValueError, match="内容冲突"):
        completion.complete_memory(request.model_copy(update={"answer": "changed"}))
    with account_session("owner") as state:
        state["memory_completions"][session_key("session")][checkpoints.key]["created_at"] = (
            utc_now() - timedelta(days=3660)).isoformat()
    with pytest.raises(ValueError, match="保留期"):
        completion.complete_memory(request)


def test_provider_calls_run_without_account_lock_and_newer_edit_supersedes_plan(setup, monkeypatch):
    request, store, _ = setup
    target = store.add_memory("owner", "weak_point", "original", topic="calculus")
    plan = completion._plan(request, entry("weak_point"), "effect")
    store.update_memory(target, content="user changed after planning")
    from app.memory import session_scope
    from app.utils import embedding
    original = embedding.embeddings

    def unlocked(texts):
        assert getattr(session_scope._current, "active", None) is None
        return original(texts)

    monkeypatch.setattr(embedding, "embeddings", unlocked)
    assert completion._apply(request, plan, "effect") == "superseded"
    assert store.get_memory(target)["content"] == "user changed after planning"


def test_late_assistant_orders_by_instant_preserving_summary_prefix(setup):
    request, _, _ = setup
    later = utc_now() + timedelta(minutes=1)
    short_term_memory.add_message("session", Message(role="user", content="next question", timestamp=later.isoformat()),
                                  user_id="owner", delivery_id="next")
    completion.complete_memory(request)
    history = short_term_memory.get_history("session", user_id="owner")
    assert [m.content for m in history] == ["question", "saved answer", "next question"]
    assert later > utc_now()


def test_corrupt_checkpoint_fails_before_any_untracked_effect(setup):
    request, _, _ = setup
    checkpoints = completion.Checkpoints(request)
    checkpoints.phase("init", lambda: True)
    with account_session("owner") as state:
        state["memory_completions"][session_key("session")][checkpoints.key]["phases"] = []
    effect = Mock()
    with pytest.raises(ValueError, match="检查点损坏"):
        checkpoints.phase("untracked", effect)
    effect.assert_not_called()
