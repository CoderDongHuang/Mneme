import importlib.util
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
            "llm_daily_cost_usd": 9.5,
            "storage_usage_ratio": 0.85,
            "trace_usage_ratio": 0.2,
            "session_idle_ratio": 0.85,
            "knowledge_base_usage_ratio": 0.9,
            "learning_observations": 10,
            "retention_rate": 0.9,
        },
        {"llm_daily_budget_usd": 10, "session_ttl_hours": 24},
    )
    assert report["source"] == "operator-measured-snapshot"
    assert report["policy"]["status"] == "action_required"
    assert {"idle_sessions", "knowledge_base_quota_near_limit"} <= {
        item["code"] for item in report["policy"]["recommendations"]
    }
