import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "full_stack_verification.py"
SPEC = importlib.util.spec_from_file_location("full_stack_verification", SCRIPT)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)


def stream(*events):
    return "".join(
        f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        for name, data in events
    )


def test_empty_account_accepts_completed_evidence_refusal():
    verification.assert_no_evidence_stream(stream(
        ("meta", {"intent": "qa", "sources": []}),
        ("token", {"content": "当前资料没有足够的可核查证据回答这个问题。"}),
        ("done", {"answer_length": 26}),
    ))


@pytest.mark.parametrize("events", [
    [("meta", {"sources": []}), ("token", {"content": "缺少证据"})],
    [("meta", {"sources": []}), ("error", {"message": "failed"}), ("done", {})],
    [("meta", {"sources": [{"id": 1}]}), ("token", {"content": "缺少证据"}), ("done", {})],
    [("meta", {"sources": []}), ("token", {"content": "证据是 QZ-7294"}), ("done", {})],
    [("meta", {"sources": []}), ("done", {})],
])
def test_empty_account_rejects_incomplete_or_fabricated_response(events):
    with pytest.raises(verification.VerificationError):
        verification.assert_no_evidence_stream(stream(*events))


@pytest.mark.parametrize("checkpoint, accepted", [
    (("retry", "knowledge_cleanup"), True),
    (("retry", "memory_cleanup"), False),
    (("retry", "queued"), False),
    (("completed", "knowledge_cleanup"), False),
])
def test_redis_outage_requires_memory_cleanup_to_remain_uncheckpointed(monkeypatch, checkpoint, accepted):
    from types import SimpleNamespace
    from unittest.mock import Mock
    client = Mock()
    client.request.return_value = {"operation_id": "test-operation"}
    monkeypatch.setattr(verification, "new_user", lambda *a, **kw: (client, {"user_id": 7}))
    monkeypatch.setattr(verification, "compose", Mock())
    monkeypatch.setattr(verification, "enqueue_db", lambda *a: "redis-operation")
    monkeypatch.setattr(verification, "wait_http", Mock())
    monkeypatch.setattr(verification, "assert_deleted", Mock())
    waits = Mock(side_effect=[("retry", "queued"), ("completed", "user_delete"),
        ("retry", "session_cleanup"), ("completed", "user_delete"), checkpoint,
        ("completed", "user_delete"), ("completed", "user_delete")])
    monkeypatch.setattr(verification, "wait_task", waits)
    args = SimpleNamespace(base_url="http://isolated", compose_file=[])
    if accepted:
        verification.deletion_drill(args)
        assert verification.assert_deleted.call_count == 4
    else:
        with pytest.raises(verification.VerificationError, match="unexpected checkpoint"):
            verification.deletion_drill(args)
        assert verification.assert_deleted.call_count == 2
