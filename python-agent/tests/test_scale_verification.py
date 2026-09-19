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


def test_restart_vector_shard_recreates_container_and_waits_for_readiness(monkeypatch):
    calls = []
    monkeypatch.setattr(
        scale_verification,
        "compose",
        lambda *args: calls.append(("compose", args)),
    )
    monkeypatch.setattr(
        scale_verification,
        "wait_http",
        lambda url: calls.append(("wait_http", url)),
    )

    scale_verification._restart_vector_shard()

    assert calls == [
        ("compose", ("up", "-d", "--force-recreate", "chroma-2")),
        ("wait_http", "http://127.0.0.1:8002/health/ready"),
    ]
