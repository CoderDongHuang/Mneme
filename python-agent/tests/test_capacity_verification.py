import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_deadline_rechecked_after_early_wakeup(monkeypatch):
    now = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += min(seconds, 0.04)

    monkeypatch.setattr(MODULE, "time", SimpleNamespace(monotonic=lambda: now[0], sleep=sleep))
    MODULE.wait_until(0.15)
    assert now[0] >= 0.15
    assert len(sleeps) > 1


def test_load_paces_individual_requests_and_retains_errors(monkeypatch):
    import time

    starts = []

    def request(_url):
        starts.append(time.monotonic())
        if len(starts) == 2:
            raise MODULE.CapacityVerificationError("HTTP 429")
        return {"chunks": [1]}

    monkeypatch.setattr(MODULE, "request_json", request)
    result = MODULE.load_test(["http://one"], 3, 2, 0.15)
    assert result["completed"] == 2
    assert result["errors"] == 1
    assert result["error_samples"] == ["HTTP 429"]
    assert starts[-1] - starts[0] >= 0.08
    assert result["duration_seconds"] >= 0.15


def test_run_fails_capacity_thresholds(monkeypatch):
    monkeypatch.setattr(MODULE, "wait_http", lambda *_args: None)
    monkeypatch.setattr(MODULE.Path, "read_bytes", lambda *_args: b"fixture")
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
    assert len(report["quality_gate"]["failures"]) == 4


def arguments(**overrides):
    values = dict(
        data_profile="small,medium,large", agent_url="http://one", agent_url_2="http://two",
        requests=12, concurrency=2, duration_seconds=0, compose_file=["compose.yml"],
        fault_services=["redis"], fault_matrix=[["redis"], ["chroma-1", "redis"]],
        fault_rounds=2, max_errors=0, max_p95_ms=2000.0, max_recovery_seconds=20,
        fault_hold_seconds=0,
    )
    return SimpleNamespace(**{**values, **overrides})


@pytest.mark.parametrize("name", ["max_errors", "max_p95_ms", "max_recovery_seconds", "fault_hold_seconds"])
@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), True])
def test_invalid_thresholds_rejected_before_side_effects(monkeypatch, name, value):
    monkeypatch.setattr(MODULE, "seed_data", lambda *_args: pytest.fail("must not seed"))
    with pytest.raises(ValueError, match="finite and nonnegative"):
        MODULE.run(arguments(**{name: value}))


@pytest.mark.parametrize("overrides", [
    {"fault_rounds": 1}, {"fault_rounds": 0}, {"fault_matrix": []},
    {"fault_matrix": [[]]}, {"fault_matrix": [["redis", "redis"]]},
    {"requests": 5}, {"concurrency": 0}, {"duration_seconds": -1},
    {"data_profile": ""}, {"data_profile": "unknown"},
])
def test_incomplete_matrix_or_load_rejected_before_seeding(monkeypatch, overrides):
    monkeypatch.setattr(MODULE, "seed_data", lambda *_args: pytest.fail("must not seed"))
    with pytest.raises(ValueError):
        MODULE.run(arguments(**overrides))


def test_run_probes_every_profile_on_both_agents_and_gates_recovery(monkeypatch):
    urls = []
    monkeypatch.setattr(MODULE, "wait_http", lambda *_args: None)
    monkeypatch.setattr(MODULE.Path, "read_bytes", lambda *_args: b"fixture")
    monkeypatch.setattr(MODULE, "seed_data", lambda *_args: ("user", ["small", "medium", "large"]))

    def load_test(load_urls, *_args):
        urls.extend(load_urls)
        return {"requested": 12, "completed": 12, "errors": 0, "p95_latency_ms": 100}

    monkeypatch.setattr(MODULE, "load_test", load_test)
    monkeypatch.setattr(MODULE, "recover_faults", lambda *_args: [
        {"round": 1, "services": ["redis"], "status": "passed", "recovery_seconds": 5},
        {"round": 2, "services": ["chroma-1", "redis"], "status": "passed", "recovery_seconds": 25},
    ])
    result = MODULE.run(arguments())
    assert len(urls) == 6
    for kb in ("small", "medium", "large"):
        for agent in ("one", "two"):
            assert any(f"http://{agent}/" in url and f"kb_id={kb}" in url for url in urls)
    assert result["status"] == "failed"
    assert result["quality_gate"]["failures"] == ["fault round 2 recovery exceeds 20 or is invalid"]
    assert result["provenance"]["configuration"]["fault_matrix"] == arguments().fault_matrix
    assert result["provenance"]["report_id"]


@pytest.mark.parametrize("failure", ["stop", "health", "restart"])
def test_fault_cleanup_attempts_every_service_even_on_failure(monkeypatch, failure):
    calls = []

    def compose(_files, *args, **_kwargs):
        calls.append(args)
        if (failure == "stop" and args == ("stop", "redis")) or (
            failure == "restart" and args[0] == "up" and args[-1] == "chroma-1"
        ):
            raise MODULE.CapacityVerificationError(f"{failure} failed")

    def request(_url):
        if failure == "health":
            raise MODULE.CapacityVerificationError("health failed")
        return {"status": "ok"}

    monkeypatch.setattr(MODULE, "compose", compose)
    monkeypatch.setattr(MODULE, "request_json", request)
    with pytest.raises(MODULE.CapacityVerificationError, match=f"{failure} failed"):
        MODULE.recover_faults(["compose.yml"], ["chroma-1", "redis"], ["http://one"],
                              ["http://probe"], 1, hold_seconds=0)
    assert [call[-1] for call in calls if call[0] == "up"] == ["chroma-1", "redis"]


def test_fault_matrix_executes_every_group_and_excludes_hold_from_recovery(monkeypatch):
    calls = []
    clock = iter([10, 12, 20, 23])
    monkeypatch.setattr(MODULE.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(MODULE.time, "sleep", lambda seconds: calls.append(("sleep", seconds)))
    monkeypatch.setattr(MODULE, "compose", lambda _files, *args, **_kwargs: calls.append(args))

    monkeypatch.setattr(MODULE, "request_json", lambda _url: {"status": "ok", "chunks": [1]})
    monkeypatch.setattr(MODULE, "wait_http", lambda _url, **_kwargs: None)
    matrix = [["redis"], ["chroma-1", "redis"]]
    result = MODULE.recover_faults(["compose.yml"], [], ["http://one", "http://two"],
                                   ["http://probe"], 2, matrix, hold_seconds=7)
    assert [item["services"] for item in result] == matrix
    assert [item["recovery_seconds"] for item in result] == [2, 3]
    assert calls.count(("sleep", 7)) == 2


def test_load_rejects_successful_http_with_empty_retrieval(monkeypatch):
    monkeypatch.setattr(MODULE, "request_json", lambda _url: {"chunks": []})
    with pytest.raises(MODULE.CapacityVerificationError, match="no successful requests"):
        MODULE.load_test(["http://one/api/v1/knowledge/search?kb_id=one"], 2, 1, 0)


@pytest.mark.parametrize("urls,requests,duration", [([], 2, 0), (["one", "two"], 1, 0), (["one"], 1, -1)])
def test_load_requires_complete_url_coverage(urls, requests, duration):
    with pytest.raises(ValueError):
        MODULE.load_test(urls, requests, 1, duration)


def test_runtime_budget_bounds_requests_and_resets_after_failure(monkeypatch):
    clock = iter([10, 11, 12])
    monkeypatch.setattr(MODULE.time, "monotonic", lambda: next(clock))
    with pytest.raises(MODULE.CapacityVerificationError, match="budget exhausted"):
        with MODULE.runtime_budget(2):
            assert MODULE.remaining_timeout(30) == 1
            MODULE.remaining_timeout(30)
    assert MODULE.RUN_DEADLINE is None


def test_cleanup_retains_time_to_restart_after_budget_exhaustion(monkeypatch):
    calls = []
    monkeypatch.setattr(MODULE, "RUN_DEADLINE", 0)

    def compose(_files, *args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "stop":
            MODULE.remaining_timeout(30)
        assert kwargs["timeout"] == 30

    monkeypatch.setattr(MODULE, "compose", compose)
    with pytest.raises(MODULE.CapacityVerificationError, match="budget exhausted"):
        MODULE.recover_faults(["compose.yml"], ["redis"], ["http://one"], ["http://probe"], 1)
    assert calls[-1][0][-1] == "redis"
    assert calls[-1][0][0] == "up"


def test_operational_failure_report_retains_comparable_provenance(monkeypatch):
    monkeypatch.setattr(MODULE.Path, "read_bytes", lambda *_args: b"fixture")
    monkeypatch.setattr(MODULE, "wait_http", lambda *_args: (_ for _ in ()).throw(
        MODULE.CapacityVerificationError("not ready")))
    result = MODULE.run(arguments())
    assert result["status"] == "failed"
    assert result["quality_gate"]["failures"] == ["not ready"]
    assert result["provenance"]["configuration"]["runtime_timeout_seconds"] == 1200
    assert MODULE.RUN_DEADLINE is None


@pytest.mark.parametrize("matrix", ["", "redis,,chroma-1", "redis+", "+redis"])
def test_cli_rejects_empty_matrix_groups_and_writes_failed_evidence(tmp_path, monkeypatch, matrix):
    output = tmp_path / "capacity.json"
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--compose-file", "compose.yml", "--fault-matrix", matrix,
                                      "--report", str(output)])
    monkeypatch.setattr(MODULE, "seed_data", lambda *_args: pytest.fail("must not seed"))
    with pytest.raises(SystemExit) as error:
        MODULE.main()
    assert error.value.code == 1
    assert json.loads(output.read_text())["status"] == "failed"
