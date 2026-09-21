import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "slo_verification.py"
SPEC = importlib.util.spec_from_file_location("slo_verification", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_snapshot_calculates_availability_and_histogram_p95():
    metrics = {
        "mneme_python_http_requests_total": [
            ({"status": "200"}, 95.0),
            ({"status": "500"}, 5.0),
        ],
        "mneme_python_http_request_duration_seconds_bucket": [
            ({"le": "0.5"}, 70.0),
            ({"le": "1.0"}, 94.0),
            ({"le": "2.0"}, 100.0),
        ],
    }
    report = MODULE.snapshot(metrics)
    assert report["availability"] == 0.95
    assert report["errors"] == 5
    assert report["p95_seconds"] == 2.0


def test_versioned_slo_policy_matches_alert_and_recovery_assets():
    root = Path(__file__).parents[2]
    policy = json.loads((root / "observability" / "slo.json").read_text(encoding="utf-8"))
    rules = (root / "observability" / "prometheus" / "rules" / "mneme-slo.yml").read_text(encoding="utf-8")
    recovery = (root / ".github" / "workflows" / "disaster-recovery.yml").read_text(encoding="utf-8")

    assert policy["targets"]["availability"] == 0.995
    assert policy["targets"]["backup_rpo_hours"] == 24
    assert "MnemeAvailabilityBudgetBurn" in rules
    assert "MnemeGatewayLatencyBudgetBurn" in rules
    assert "schedule:" in recovery and "restore-report.json" in recovery
