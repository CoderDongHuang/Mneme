import importlib.util
from pathlib import Path
from types import SimpleNamespace


SCRIPT = Path(__file__).parents[2] / "scripts" / "capacity_verification.py"
SPEC = importlib.util.spec_from_file_location("capacity_verification", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_load_test_uses_all_urls_and_reports_latency(monkeypatch):
    calls = []

    def request_json(url, method="GET", payload=None):
        calls.append(url)
        return {"status": "ok"}

    monkeypatch.setattr(MODULE, "request_json", request_json)
    report = MODULE.load_test(["http://one/health", "http://two/health"], 8, 2, 0)
    assert report["completed"] == 8
    assert report["errors"] == 0
    assert set(calls) == {"http://one/health", "http://two/health"}


def test_percentile_is_deterministic():
    assert MODULE.percentile([10, 20, 30, 40], 0.95) == 40


def test_run_fails_capacity_thresholds(monkeypatch):
    monkeypatch.setattr(MODULE, "seed_data", lambda *_args: ("user", ["kb"]))
    monkeypatch.setattr(
        MODULE,
        "load_test",
        lambda *_args: {
            "requested": 10,
            "completed": 9,
            "errors": 1,
            "p95_latency_ms": 2500.0,
        },
    )
    monkeypatch.setattr(MODULE, "recover_faults", lambda *_args: [])
    report = MODULE.run(
        SimpleNamespace(
            data_profile="small",
            agent_url="http://one",
            agent_url_2="http://two",
            requests=10,
            concurrency=2,
            duration_seconds=0,
            compose_file=["compose.yml"],
            fault_services=["redis"],
            fault_rounds=1,
            max_errors=0,
            max_p95_ms=2000.0,
        )
    )
    assert report["status"] == "failed"
    assert len(report["quality_gate"]["failures"]) == 3
