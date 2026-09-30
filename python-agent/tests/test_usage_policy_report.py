import importlib.util
from datetime import datetime, timezone
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "usage_policy_report.py"
SPEC = importlib.util.spec_from_file_location("usage_policy_report", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_usage_report_requires_measured_inputs():
    with pytest.raises(ValueError, match="missing measured fields"):
        MODULE.run({}, {})
    report = MODULE.run(
        {
            "captured_at": "2026-09-29T00:00:00Z",
            "sample_count": 12,
            "measurement_window_seconds": 86400,
            "evidence": {"prometheus": "test-fixture", "billing": "operator-export"},
            "llm_daily_cost_usd": 9.5,
            "storage_usage_ratio": 0.85,
            "trace_usage_ratio": 0.2,
            "session_idle_ratio": 0.85,
            "knowledge_base_usage_ratio": 0.9,
            "learning_observations": 10,
            "retention_rate": 0.9,
        },
        {"llm_daily_budget_usd": 10, "session_ttl_hours": 24},
        now=datetime(2026, 9, 30, tzinfo=timezone.utc),
    )
    assert report["source"] == "operator-measured-snapshot"
    assert report["policy"]["status"] == "action_required"
    assert {"idle_sessions", "knowledge_base_quota_near_limit"} <= {
        item["code"] for item in report["policy"]["recommendations"]
    }


def test_usage_report_rejects_unverifiable_snapshot():
    incomplete = {
        "captured_at": "2026-09-29T00:00:00Z",
        "llm_daily_cost_usd": 0,
        "storage_usage_ratio": 0,
        "trace_usage_ratio": 0,
        "session_idle_ratio": 0,
        "knowledge_base_usage_ratio": 0,
        "learning_observations": 1,
        "retention_rate": 0.5,
    }
    with pytest.raises(ValueError, match="sample_count"):
        MODULE.run(incomplete, {}, now=datetime(2026, 9, 30, tzinfo=timezone.utc))
    usage = {
        **incomplete,
        "sample_count": 1,
        "measurement_window_seconds": 60,
        "evidence": {"prometheus": "test"},
    }
    usage["captured_at"] = "2099-01-01T00:00:00Z"
    with pytest.raises(ValueError, match="future"):
        MODULE.run(usage, {}, now=datetime(2026, 9, 30, tzinfo=timezone.utc))
    usage["captured_at"] = "2026-09-29T00:00:00Z"
    usage["measurement_window_seconds"] = 60
    with pytest.raises(ValueError, match="older than"):
        MODULE.run(usage, {}, now=datetime(2026, 9, 30, tzinfo=timezone.utc))
