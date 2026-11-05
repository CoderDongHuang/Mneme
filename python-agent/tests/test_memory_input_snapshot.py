"""Completion reads its captured turn, regardless of later cache/time changes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.models.chat import ChatRequest, Message
from app.agents import nodes, runtime
from app.memory.distillation import apply_distilled_entries


NOW = datetime(2026, 11, 1, 8, tzinfo=timezone.utc)


def message(role, content, minutes_ago=0):
    return Message(role=role, content=content, timestamp=(NOW - timedelta(minutes=minutes_ago)).isoformat())


def state(history):
    return {"user_id": "owner", "session_id": "session", "memory_input": {
        "history": [item.model_dump() for item in history],
        "reference_time": NOW.isoformat(), "delivery_id": "turn-1",
    }}


def test_completion_distills_captured_turn_without_reading_mutable_cache(monkeypatch):
    captured = state([message("assistant", "earlier answer", 20), message("user", "current question")])
    monkeypatch.setattr(nodes.short_term_memory, "get_history", Mock(side_effect=AssertionError("late cache read")))
    distill = Mock(return_value=[{"category": "preference", "content": "captured preference", "confidence": .7}])
    monkeypatch.setattr(nodes, "distill_conversation", distill)
    pending = nodes.memory_write_node(captured)["pending_memories"]
    distill.assert_called_once_with("owner", "session", [{"role": "assistant", "content": "earlier answer"}])
    assert len(pending) == 1 and pending[0]["content"] == "captured preference"


def test_long_model_delay_does_not_create_an_idle_gap(monkeypatch):
    captured = state([message("assistant", "recent answer", 5), message("user", "question")])
    monkeypatch.setattr(nodes, "utc_now", lambda: NOW + timedelta(hours=8))
    distill = Mock(side_effect=AssertionError("model delay is not user inactivity"))
    monkeypatch.setattr(nodes, "distill_conversation", distill)
    assert nodes.memory_write_node(captured) == {"memory_entries_to_write": []}
    distill.assert_not_called()


@pytest.mark.parametrize("history", [[], [message("user", "first turn")]])
def test_empty_snapshot_does_not_fall_back_to_later_cache(monkeypatch, history):
    monkeypatch.setattr(nodes.short_term_memory, "get_history", Mock(side_effect=AssertionError("late cache read")))
    assert nodes.memory_write_node(state(history)) == {"memory_entries_to_write": []}


def test_prepare_copies_message_objects_before_pre_llm_nodes(monkeypatch):
    history = [message("assistant", "old answer", 20)]
    monkeypatch.setattr(runtime, "require_cloud_processing", lambda _: None)
    monkeypatch.setattr(runtime, "utc_now", lambda: NOW)
    monkeypatch.setattr(runtime, "working_memory", SimpleNamespace(replace_messages=lambda *args, **kw: None))
    monkeypatch.setattr(runtime, "short_term_memory", SimpleNamespace(
        add_message=lambda _, item, **kw: (history.append(item) or history),
        get_history=Mock(side_effect=AssertionError("must snapshot the committed append, not a later read"))))
    register = Mock()
    monkeypatch.setattr(runtime, "session_store", SimpleNamespace(register_session=register))

    def prepare(prepared):
        history[0].content = "changed later"
        history.append(message("user", "next turn"))
        return prepared

    monkeypatch.setattr(runtime, "run_pre_llm_nodes", prepare)
    prepared = runtime.prepare_conversation(ChatRequest(
        user_id="owner", session_id="session", request_id="turn-1", message="current question"))
    assert [item["content"] for item in prepared["memory_input"]["history"]] == ["old answer", "current question"]
    assert prepared["memory_input"]["reference_time"] == NOW.isoformat()
    assert prepared["memory_input"]["delivery_id"] == "turn-1"
    assert register.call_args.kwargs["delivery_id"] == prepared["memory_input"]["delivery_id"]


def test_candidate_identity_is_stable_reordered_and_tenant_turn_scoped():
    entries = [
        {"category": "preference", "content": "diagrams", "confidence": .7},
        {"category": "weak_point", "content": "calculus", "topic": "math", "confidence": .75},
    ]
    scope = ["owner", "session", "turn-1"]
    first = apply_distilled_entries("owner", entries, candidate_scope=scope)
    repeat = apply_distilled_entries("owner", list(reversed(entries)), candidate_scope=scope)
    assert first == list(reversed(repeat))
    assert len({item["temp_id"] for item in first}) == 2
    assert all(len(item["temp_id"]) <= 64 for item in first)
    for alternate in [["other", "session", "turn-1"], ["owner", "other", "turn-1"], ["owner", "session", "turn-2"]]:
        assert first[0]["temp_id"] != apply_distilled_entries("owner", entries, candidate_scope=alternate)[0]["temp_id"]


def test_legacy_call_without_delivery_id_never_coalesces_unrelated_candidates():
    entries = [{"category": "preference", "content": "diagrams", "confidence": .7}]
    first = apply_distilled_entries("owner", entries)
    assert first[0]["temp_id"] != apply_distilled_entries("owner", entries)[0]["temp_id"]


@pytest.mark.parametrize("request_id,captured_id", [("request-turn", "captured-turn"), ("request-turn", ""), ("", "")])
def test_completion_passes_stable_turn_identity_to_reflection(monkeypatch, request_id, captured_id):
    monkeypatch.setattr(runtime, "require_cloud_processing", lambda _: None)
    monkeypatch.setattr(runtime, "memory_write_node", lambda _: {})
    monkeypatch.setattr(runtime, "working_memory", SimpleNamespace(replace_messages=lambda *args, **kw: None))
    monkeypatch.setattr(runtime, "short_term_memory", SimpleNamespace(
        add_message=lambda *args, **kw: [], should_summarize=lambda _, **kw: False))
    count = Mock()
    monkeypatch.setattr(runtime, "session_store", SimpleNamespace(increment_message_count=count))
    monkeypatch.setattr(runtime.agent_trace_store, "record", lambda *args, **kw: None)
    record = Mock()
    monkeypatch.setattr(runtime, "reflection_scheduler", SimpleNamespace(
        record_session=record, check_and_trigger=lambda _: None))
    request = ChatRequest(user_id="owner", session_id="session", request_id=request_id, message="question")
    captured = {"memory_input": {"delivery_id": captured_id}} if captured_id else {}
    runtime.complete_conversation(request, captured, "answer")
    runtime.complete_conversation(request, captured, "answer")
    first, second = [call.args for call in record.call_args_list]
    assert first == second
    assert first[:2] == ("owner", "session")
    expected_id = captured_id or request_id or captured["completion_delivery_id"]
    assert first[2] == expected_id
    assert first[2]
    assert [call.kwargs["delivery_id"] for call in count.call_args_list] == [expected_id, expected_id]


def test_legacy_completion_keeps_identity_before_extraction_failure_without_fabricating_snapshot(monkeypatch):
    monkeypatch.setattr(runtime, "require_cloud_processing", lambda _: None)
    captured = {"user_id": "owner", "session_id": "session"}
    observed = []

    def fail(state):
        assert "memory_input" not in state
        observed.append(state["completion_delivery_id"])
        raise RuntimeError("extraction unavailable")

    monkeypatch.setattr(runtime, "memory_write_node", fail)
    request = ChatRequest(user_id="owner", session_id="session", message="question")
    for _ in range(2):
        with pytest.raises(RuntimeError, match="extraction unavailable"):
            runtime.complete_conversation(request, captured, "answer")
    assert observed[0] and observed[0] == observed[1]
