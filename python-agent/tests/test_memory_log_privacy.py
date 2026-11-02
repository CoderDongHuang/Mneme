"""Canary checks exercise operations, including failures, without printing bodies."""
import asyncio
import io
import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from app.api import memory as api
from app.agents import trace_store
from app.core.logging import JsonFormatter, log_identifier, trace_id_var
from app.memory import distillation, long_term_memory as ltm_module
from app.memory.memory_store import MemoryVectorStore
from app.models.chat import MemoryConfirmRequest, Message
import app.agents.nodes as nodes
import app.memory.short_term_memory as stm_module


@pytest.fixture
def diagnostics():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    loggers = [logging.getLogger(name) for name in (
        "long_term_memory", "memory_api", "memory_store", "distillation", "nodes", "short_term_memory",
    )]
    previous = [(logger, logger.level) for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
    token = trace_id_var.set("privacy-request-trace")
    try:
        yield stream
    finally:
        trace_id_var.reset(token)
        for logger, level in previous:
            logger.removeHandler(handler)
            logger.setLevel(level)


def test_memory_operations_do_not_log_canaries(diagnostics, monkeypatch):
    body, user, session = "私密正文_UNIQUE_CANARY_1", "private-user-2", "private-session-3"
    store = Mock()
    store.find_duplicates.return_value = []
    store.search.return_value = []
    store.get_by_category.return_value = []
    store.add_memory.return_value = "private-legacy-memory-4"
    manager = ltm_module.LongTermMemoryManager()
    manager._store = store
    manager.add_preference(user, body, session)
    manager.add_weak_point(user, body, body, session)
    manager.update_progress(user, body, body, session)
    store.find_duplicates.return_value = [{"id": "private-legacy-memory-4", "content": body, "score": 0.01}]
    assert manager.add_preference(user, body) is None
    store.find_duplicates.return_value = []
    store.search.return_value = [{"id": "private-legacy-memory-4", "content": body}] * ltm_module.MAX_PREFERENCES
    manager.add_preference(user, body)
    store.get_by_category.return_value = [{"id": "private-legacy-memory-4", "topic": body, "importance": 0.1,
                                          "created_at": (datetime.now() - timedelta(days=40)).isoformat()}]
    manager.add_weak_point(user, body, body)
    manager.decay_weak_points(user)
    store.get_memory.return_value = None
    monkeypatch.setattr(api, "long_term_memory", manager)
    for action in ("confirm", "dismiss"):
        asyncio.run(api.confirm_memory(MemoryConfirmRequest(
            user_id=user, temp_id=body, content=body, topic=body,
            category="preference", action=action, source_session_id=session,
        )))
    monkeypatch.setattr(distillation, "long_term_memory", Mock(get_all_memories=Mock(return_value={})))
    monkeypatch.setattr(distillation, "llm", Mock(invoke=Mock(return_value=Mock(content=body))))
    assert distillation.distill_conversation(user, session, [{"role": "user", "content": body}]) == []
    output = diagnostics.getvalue()
    for private in (body, user, session, "private-legacy-memory-4"):
        assert private not in output
    records = [json.loads(line) for line in output.splitlines()]
    assert all(row["trace_id"] == "privacy-request-trace" for row in records)
    metadata = [json.loads(row["message"]) for row in records]
    assert {"write", "deduplicate", "evict", "reinforce", "decay", "confirm", "dismiss", "distill"} <= {m["operation"] for m in metadata}
    assert any(m["memory_id_hash"] == log_identifier("private-legacy-memory-4") for m in metadata)
    assert any(m["source_session_id_hash"] == log_identifier(session) for m in metadata)


def test_store_failures_do_not_echo_provider_body(diagnostics):
    store = object.__new__(MemoryVectorStore)
    store._collection = Mock(get=Mock(side_effect=RuntimeError("PRIVATE_PROVIDER_BODY")))
    assert store.get_by_category("PRIVATE_USER", "preference") == []
    output = diagnostics.getvalue()
    assert "PRIVATE_PROVIDER_BODY" not in output and "PRIVATE_USER" not in output
    assert "RuntimeError" in output and "read_category" in output


def test_trace_keeps_metadata_without_memory_or_exception_text(tmp_path, monkeypatch):
    monkeypatch.setattr(trace_store, "settings", replace(trace_store.settings,
                        auxiliary_store_backend="sqlite", agent_trace_redact_fields=""))
    store = trace_store.AgentTraceStore(str(tmp_path / "trace.sqlite3"))
    with pytest.raises(RuntimeError):
        with store.span("u", "s", "memory_write", {"content": "PRIVATE_BODY", "topic": "PRIVATE_TOPIC", "count": 1}):
            raise RuntimeError("PRIVATE_EXCEPTION")
    rows = store.list_session("u", "s")
    encoded = json.dumps(rows)
    assert all(canary not in encoded for canary in ("PRIVATE_BODY", "PRIVATE_TOPIC", "PRIVATE_EXCEPTION"))
    assert rows[0]["payload"]["count"] == 1
    assert rows[0]["payload"]["content"]["redacted"]
    assert rows[0]["status"] == "error"
    assert json.loads(rows[0]["error"])["redacted"]


def test_provider_fallbacks_never_log_body_or_raw_identity(diagnostics, monkeypatch):
    body, user, session = "PRIVATE_PROVIDER_CANARY", "PRIVATE_USER_CANARY", "PRIVATE_SESSION_CANARY"
    failure = Mock(invoke=Mock(side_effect=RuntimeError(body)))
    monkeypatch.setattr(nodes, "llm", failure)
    state = {"user_id": user, "session_id": session, "message": body}
    assert nodes.intent_classification_node(state) == {"intent": "qa", "confidence": 0.5}
    monkeypatch.setattr(nodes, "run_reflection", Mock(side_effect=RuntimeError(body)))
    assert nodes.suggestion_generation_node(state) == {}
    manager = stm_module.ShortTermMemoryManager()
    manager._store[session] = [Message(role="user", content=body, timestamp=datetime.now().isoformat(),
                                      token_count=500) for _ in range(30)]
    before = manager._store[session].copy()
    monkeypatch.setattr(stm_module, "llm", failure)
    persist = Mock()
    monkeypatch.setattr(manager, "_persist", persist)
    manager.summarize(session)
    assert manager._store[session] == before
    assert session not in manager._last_summary_time
    persist.assert_not_called()
    output = diagnostics.getvalue()
    assert all(private not in output for private in (body, user, session))
    assert "RuntimeError" in output
    assert log_identifier(user) in output and log_identifier(session) in output
    records = [json.loads(line) for line in output.splitlines()]
    assert len(records) == 4
    assert all(row["trace_id"] == "privacy-request-trace" and "exception" not in row for row in records)


def test_history_restore_summary_success_and_cooldown_hash_session(diagnostics, monkeypatch):
    session, body = "PRIVATE_SESSION_CANARY", "PRIVATE_BODY_CANARY"
    history = [Message(role="user", content=body, timestamp=datetime.now().isoformat(), token_count=500)
               for _ in range(30)]
    monkeypatch.setattr(stm_module, "session_persistence", Mock(load_messages=Mock(return_value=history)))
    monkeypatch.setattr(stm_module, "llm", Mock(invoke=Mock(return_value=Mock(content=body))))
    first, second = stm_module.ShortTermMemoryManager(), stm_module.ShortTermMemoryManager()
    assert first.get_history(session) == history
    second.add_message(session, history[0])
    first.summarize(session)
    assert body in first.get_history(session)[0].content
    # Still enough tokens to reach the cooldown diagnostic.
    first._store[session] = history
    assert not first.should_summarize(session)
    output = diagnostics.getvalue()
    assert session not in output and body not in output
    assert log_identifier(session) in output and '"cooldown"' in output.replace('\\"', '"')
