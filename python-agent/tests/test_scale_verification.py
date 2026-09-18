import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "scale_verification.py"
SPEC = importlib.util.spec_from_file_location("scale_verification", SCRIPT)
assert SPEC and SPEC.loader
scale_verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scale_verification)


def test_jaeger_traces_accepts_api_envelope_and_unwrapped_data():
    trace = {"traceID": "0123456789abcdef0123456789abcdef"}

    assert scale_verification._jaeger_traces({"data": [trace]}) == [trace]
    assert scale_verification._jaeger_traces([trace]) == [trace]


def test_jaeger_traces_rejects_malformed_payload():
    assert scale_verification._jaeger_traces({"data": {"unexpected": True}}) == []
    assert scale_verification._jaeger_traces(None) == []
