import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.memory.reflection as reflection
import app.memory.reflection_scheduler as scheduler_module
from tests.test_reflection_scheduler import FakeRedis


VALID = {"implicit_preferences": ["diagrams"], "priority_weak_points": [],
         "next_step_suggestion": "Review the basics"}


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setattr(reflection, "require_cloud_processing", Mock())
    monkeypatch.setattr(reflection, "long_term_memory", SimpleNamespace(
        get_preferences=Mock(return_value=[{"content": "private memory"}]),
        get_weak_points=Mock(return_value=[]), get_progress=Mock(return_value=None)))
    model = Mock(invoke=Mock(return_value=SimpleNamespace(content=json.dumps(VALID))))
    monkeypatch.setattr(reflection, "llm", model)
    return model


@pytest.mark.parametrize("content", [
    "PRIVATE_PROVIDER_CANARY", "```json\n{}\n```", "null", "[]", '"text"', "true", "1", "{}", None, b"\xff",
    json.dumps({**VALID, "extra": "private"}),
    json.dumps({**VALID, "implicit_preferences": "diagrams"}),
    json.dumps({**VALID, "priority_weak_points": [None]}),
    json.dumps({**VALID, "implicit_preferences": [3]}),
    json.dumps({**VALID, "next_step_suggestion": None}),
])
def test_invalid_provider_result_is_failure_without_body(provider, content):
    provider.invoke.return_value.content = content
    with pytest.raises(reflection.ReflectionResultError) as raised:
        reflection.run_reflection("qa-user")
    assert "PRIVATE_PROVIDER_CANARY" not in str(raised.value)
    assert not hasattr(raised.value, "doc")
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_valid_schema_succeeds_and_insufficient_data_skips_provider(provider):
    assert reflection.run_reflection("qa-user") == VALID
    reflection.long_term_memory.get_preferences.return_value = []
    provider.invoke.reset_mock()
    assert reflection.run_reflection("qa-user") == {}
    provider.invoke.assert_not_called()


def test_invalid_result_keeps_queue_count_and_recovery_settles_once(provider, monkeypatch):
    monkeypatch.setattr(scheduler_module, "settings", SimpleNamespace(
        memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60))
    monkeypatch.setattr(scheduler_module, "run_reflection", reflection.run_reflection)
    fake = FakeRedis()
    scheduler = scheduler_module.ReflectionScheduler(redis_client=fake)
    scheduler.record_session("qa-user")
    assert scheduler.check_and_trigger("qa-user")
    entry = fake.stream[0]
    provider.invoke.return_value.content = "PRIVATE_PROVIDER_CANARY"
    scheduler._run_queued_reflection(*entry)
    assert fake.acked == []
    assert fake.values[scheduler._counter_key("qa-user")] == 1
    assert scheduler._job_key("qa-user") in fake.values
    # Lease expiry lets a new owner retry the same pending entry.
    fake.leases.clear()
    provider.invoke.return_value.content = json.dumps(VALID)
    scheduler._run_queued_reflection(*entry)
    assert fake.acked == [entry[0]]
    assert scheduler._counter_key("qa-user") not in fake.values
    scheduler._run_queued_reflection(*entry)
    assert fake.acked == [entry[0]]
    assert provider.invoke.call_count == 2
