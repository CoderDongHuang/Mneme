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
