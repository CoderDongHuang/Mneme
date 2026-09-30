import importlib.util
from datetime import datetime
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "collect_usage_policy_snapshot.py"
SPEC = importlib.util.spec_from_file_location("collect_usage_policy_snapshot", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_build_snapshot_uses_aggregate_ratios_and_evidence():
    result = MODULE.build_snapshot(
        {
            "users": 2, "active_sessions": 4, "idle_sessions": 3,
            "max_storage_bytes": 80, "max_knowledge_bases": 8, "traces": 50,
            "learning_observations": 10, "retention_rate": 0.7,
            "llm_daily_cost_usd": 1.25, "llm_cost_present": True,
            "llm_cost_key": "mneme:llm:cost:2026-09-30", "llm_request_series": 3,
        },
        {
            "tenant_storage_quota_bytes": 100, "tenant_knowledge_base_quota": 10,
            "trace_row_quota": 100, "measurement_window_seconds": 3600,
            "metrics_url": "http://metrics",
        },
        "2026-09-30T00:00:00+00:00",
    )
    assert result["storage_usage_ratio"] == 0.8
    assert result["session_idle_ratio"] == 0.75
    assert result["knowledge_base_usage_ratio"] == 0.8
    assert result["trace_usage_ratio"] == 0.5
    assert result["evidence"]["mysql"]["aggregates_only"] is True


def test_build_snapshot_rejects_empty_observation_set():
    aggregates = {
        "users": 0, "active_sessions": 0, "idle_sessions": 0, "max_storage_bytes": 0,
        "max_knowledge_bases": 0, "traces": 0, "learning_observations": 0,
        "retention_rate": 0, "llm_daily_cost_usd": 0, "llm_cost_present": False,
        "llm_cost_key": "key", "llm_request_series": 0,
    }
    with pytest.raises(ValueError, match="no measurable samples"):
        MODULE.build_snapshot(aggregates, {
            "tenant_storage_quota_bytes": 1, "tenant_knowledge_base_quota": 1,
            "trace_row_quota": 1, "measurement_window_seconds": 1, "metrics_url": "x",
        }, "2026-09-30T00:00:00+00:00")


def test_query_scalar_passes_datetime_cutoff_without_database_timezone_conversion():
    class Cursor:
        def __init__(self):
            self.call = None

        def execute(self, sql, params):
            self.call = (sql, params)

        def fetchone(self):
            return (7,)

    cursor = Cursor()
    cutoff = datetime(2026, 9, 29, 0, 0)
    assert MODULE.query_scalar(cursor, "SELECT COUNT(*) WHERE created_at >= %s", (cutoff,)) == 7
    assert cursor.call == ("SELECT COUNT(*) WHERE created_at >= %s", (cutoff,))
