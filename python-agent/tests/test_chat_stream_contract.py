import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.models.chat_stream import AGENT_EVENTS, validate_event
from scripts.export_stream_contract import check_vocabulary

ROOT = Path(__file__).resolve().parents[2]
CASES = json.loads((ROOT / "contracts/chat-stream.cases.json").read_text(encoding="utf-8"))


def test_generated_stream_contract_and_types_are_current():
    subprocess.run([sys.executable, str(ROOT / "python-agent/scripts/export_stream_contract.py"), "--check"], check=True)


@pytest.mark.parametrize("schema", [
    {"pattern": "secret"}, {"properties": {"field": {"format": "date-time"}}},
    {"items": {"minItems": 2}}, {"additionalProperties": {"uniqueItems": True}},
    {"anyOf": [{"exclusiveMinimum": 0}]},
])
def test_unsupported_nested_schema_constraint_blocks_publication(schema):
    with pytest.raises(ValueError, match="Unsupported stream schema vocabulary"):
        check_vocabulary(schema)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_shared_wire_cases(case):
    for agent in (False, True):
        valid = case["valid"] and (not agent or case["event"] in AGENT_EVENTS)
        if valid:
            validate_event(case["event"], case["data"], agent=agent)
        else:
            with pytest.raises(ValueError, match="^INVALID_CHAT_EVENT$"):
                validate_event(case["event"], case["data"], agent=agent)


def test_agent_serializer_rejects_invalid_event_before_emitting_private_payload():
    from app.api.chat_stream import _event
    for event, data in [("token", {"content": 123}), ("done", {}), ("start", {}),
                        ("error", {"message": "private", "unknown": "secret"})]:
        with pytest.raises(ValueError, match="^INVALID_CHAT_EVENT$"):
            _event(event, data)


def test_completion_history_bound_and_internal_only():
    payload = {"input": {"user_id": "7", "session_id": "9", "delivery_id": "turn",
                         "reference_time": "2026-11-06T00:00:00Z", "answer": "saved",
                         "history": [{"role": "user", "content": "question", "timestamp": "2026-11-06T00:00:00Z"}] * 41}}
    validate_event("completion", payload, agent=True)
    with pytest.raises(ValueError, match="^INVALID_CHAT_EVENT$"):
        validate_event("completion", payload)
    payload["input"]["history"].append(payload["input"]["history"][0])
    with pytest.raises(ValueError, match="^INVALID_CHAT_EVENT$"):
        validate_event("completion", payload, agent=True)
