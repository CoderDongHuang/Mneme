import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "collect_operational_trends", ROOT / "scripts" / "collect_operational_trends.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_snapshot_uses_route_templates_and_low_cardinality_counters():
    payload = """
# HELP mneme_python_http_requests_total HTTP requests
# TYPE mneme_python_http_requests_total counter
mneme_python_http_requests_total{method="GET",path="/api/v1/session/{session_id}",status="200"} 2
mneme_python_http_requests_total{method="GET",path="unmatched",status="404"} 1
# HELP mneme_input_rejections_total rejected
# TYPE mneme_input_rejections_total counter
mneme_input_rejections_total{source="request_validation",reason="schema"} 3
# HELP mneme_reflection_lease_takeovers_total takeovers
# TYPE mneme_reflection_lease_takeovers_total counter
mneme_reflection_lease_takeovers_total 1
"""
    report = MODULE.snapshot(payload)
    assert report["http_request_series"] == 2
    assert report["http_unique_paths"] == 2
    assert report["input_rejections_total"] == 3
    assert report["reflection_lease_takeovers_total"] == 1


def test_collect_reports_rejection_rate_and_cardinality(monkeypatch):
    payloads = iter(
        [
            "# TYPE mneme_input_rejections_total counter\nmneme_input_rejections_total 1\n",
            "# TYPE mneme_input_rejections_total counter\nmneme_input_rejections_total 3\n",
        ]
    )
    monkeypatch.setattr(MODULE, "urlopen", lambda *_args, **_kwargs: _Response(next(payloads)))
    report = MODULE.collect("http://metrics", samples=2, interval=0, max_series=10, max_paths=10)
    assert report["status"] == "passed"
    assert report["trend"]["input_rejection_rate_per_minute"] >= 0


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload.encode()
