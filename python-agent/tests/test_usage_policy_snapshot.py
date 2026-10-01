import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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
            "max_storage_bytes": 80, "max_knowledge_bases": 8,
            "trace_rows_total": 50, "trace_rows_window": 5,
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
    assert result["sample_count"] == 10
    assert result["evidence"]["mysql"]["trace_rows_total"] == 50
    assert result["evidence"]["mysql"]["trace_rows_window"] == 5
    assert result["evidence"]["mysql"]["aggregates_only"] is True


def test_build_snapshot_does_not_count_registered_users_as_usage():
    aggregates = {
        "users": 12,
        "active_sessions": 0,
        "trace_rows_total": 1000,
        "trace_rows_window": 0,
        "learning_observations": 0,
        "llm_request_series": 0,
        "llm_daily_cost_usd": 0,
        "max_storage_bytes": 0,
        "max_knowledge_bases": 0,
        "idle_sessions": 0,
        "retention_rate": 0,
        "llm_cost_key": "mneme:llm:cost:2026-09-30",
        "llm_cost_present": False,
    }
    with pytest.raises(ValueError, match="no measurable samples"):
        MODULE.build_snapshot(
            aggregates,
            {
                "tenant_storage_quota_bytes": 1024,
                "tenant_knowledge_base_quota": 10,
                "trace_row_quota": 100,
                "measurement_window_seconds": 60,
                "metrics_url": "http://metrics",
            },
            "2026-09-30T00:00:00+00:00",
        )


def test_build_snapshot_does_not_count_cumulative_request_series_as_windowed_usage():
    aggregates = {
        "users": 12, "active_sessions": 0, "trace_rows_total": 0,
        "trace_rows_window": 0, "learning_observations": 0,
        "llm_request_series": 3, "llm_daily_cost_usd": 1, "max_storage_bytes": 0,
        "max_knowledge_bases": 0, "idle_sessions": 0, "retention_rate": 0,
        "llm_cost_key": "key", "llm_cost_present": True,
    }
    with pytest.raises(ValueError, match="no measurable samples"):
        MODULE.build_snapshot(aggregates, {
            "tenant_storage_quota_bytes": 1, "tenant_knowledge_base_quota": 1,
            "trace_row_quota": 1, "measurement_window_seconds": 60, "metrics_url": "x",
        }, "2026-09-30T00:00:00+00:00")


def test_build_snapshot_rejects_empty_observation_set():
    aggregates = {
        "users": 0, "active_sessions": 0, "idle_sessions": 0, "max_storage_bytes": 0,
        "max_knowledge_bases": 0, "trace_rows_total": 0,
        "trace_rows_window": 0, "learning_observations": 0,
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


@pytest.fixture
def snapshot_inputs():
    return (
        {
            "users": 2, "active_sessions": 4, "idle_sessions": 3,
            "max_storage_bytes": 80, "max_knowledge_bases": 8,
            "trace_rows_total": 150, "trace_rows_window": 2,
            "learning_observations": 10, "retention_rate": 0.7,
            "llm_daily_cost_usd": 1.25, "llm_cost_present": True,
            "llm_cost_key": "mneme:llm:cost:2026-09-30", "llm_request_series": 3,
        },
        {
            "tenant_storage_quota_bytes": 100, "tenant_knowledge_base_quota": 10,
            "trace_row_quota": 100, "measurement_window_seconds": 3600,
            "metrics_url": "http://metrics",
        },
    )


def test_snapshot_preserves_over_quota_occupancy(snapshot_inputs):
    result = MODULE.build_snapshot(*snapshot_inputs, "2026-09-30T12:00:00Z")
    assert result["trace_usage_ratio"] == 1.5
    assert result["sample_count"] == 10
    assert result["evidence"]["mysql"]["trace_occupancy_basis"] == "all_retained_rows"
    assert result["environment"] == "unspecified"
    assert result["evidence"]["redis"]["cost_basis"] == "reservation_estimate"


@pytest.mark.parametrize("field,value", [
    ("users", -1), ("active_sessions", 1.5), ("idle_sessions", 5),
    ("trace_rows_total", float("nan")), ("trace_rows_window", 151),
    ("learning_observations", float("inf")), ("max_knowledge_bases", -1),
    ("llm_request_series", True), ("max_storage_bytes", float("inf")),
    ("llm_daily_cost_usd", -1), ("llm_daily_cost_usd", float("nan")),
    ("retention_rate", -0.1), ("retention_rate", 1.1),
    ("llm_cost_present", "false"), ("llm_cost_present", False),
])
def test_snapshot_rejects_invalid_aggregates(snapshot_inputs, field, value):
    aggregates, settings = snapshot_inputs
    aggregates[field] = value
    with pytest.raises(ValueError):
        MODULE.build_snapshot(aggregates, settings, "2026-09-30T12:00:00Z")


@pytest.mark.parametrize("field,value", [
    ("tenant_storage_quota_bytes", 0), ("tenant_knowledge_base_quota", -1),
    ("trace_row_quota", float("inf")), ("trace_row_quota", 1.5),
    ("measurement_window_seconds", float("nan")), ("measurement_window_seconds", 0),
])
def test_snapshot_rejects_invalid_settings(snapshot_inputs, field, value):
    aggregates, settings = snapshot_inputs
    settings[field] = value
    with pytest.raises(ValueError, match=field):
        MODULE.build_snapshot(aggregates, settings, "2026-09-30T12:00:00Z")


@pytest.fixture
def collector_args():
    return SimpleNamespace(
        window_seconds=3600, idle_seconds=1800, trace_row_quota=100,
        session_ttl_hours=24, trace_retention_days=30, tenant_storage_quota_mb=2048,
        tenant_knowledge_base_quota=100, llm_daily_budget_usd=10,
        mysql_host="mysql", mysql_port=3306, mysql_database="mneme", mysql_user="reader",
        mysql_password="", redis_host="redis", redis_port=6379, redis_db=0, redis_password="",
        metrics_url="http://metrics", environment="production", cost_scope="deployment-a",
    )


@pytest.mark.parametrize("field,value", [
    ("window_seconds", 0), ("window_seconds", float("inf")),
    ("idle_seconds", 3601), ("idle_seconds", -1), ("trace_row_quota", 0),
    ("llm_daily_budget_usd", float("nan")), ("tenant_storage_quota_mb", -1),
])
def test_collector_rejects_invalid_settings_before_io(collector_args, field, value):
    setattr(collector_args, field, value)
    with pytest.raises(ValueError):
        MODULE.collect(collector_args)


def test_collector_queries_total_and_windowed_traces_separately(monkeypatch, collector_args):
    captured = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return captured

    class Cursor:
        calls = []
        closed = False

        def execute(self, sql, params):
            self.calls.append((sql, params))
            if sql == "SELECT COUNT(*) FROM agent_trace":
                self.value = 95
            elif "FROM agent_trace WHERE" in sql:
                self.value = 2
            elif "FROM auth_session" in sql:
                self.value = 1
            elif sql == "SELECT COUNT(*) FROM user":
                self.value = 2
            else:
                self.value = 0

        def fetchone(self):
            return (self.value,)

        def close(self):
            self.closed = True

    cursor = Cursor()
    connection = SimpleNamespace(cursor=lambda: cursor, close=lambda: None)
    keys = []

    class Redis:
        closed = False

        def ping(self):
            return True

        def get(self, key):
            keys.append(key)
            return "9.5"

        def close(self):
            self.closed = True

    cost_store = Redis()

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'# TYPE mneme_llm_requests_total counter\nmneme_llm_requests_total{provider="primary"} 500\n'

    monkeypatch.setattr(MODULE, "datetime", Clock)
    connector = SimpleNamespace(connect=lambda **kwargs: connection)
    monkeypatch.setitem(sys.modules, "mysql", SimpleNamespace(connector=connector))
    monkeypatch.setitem(sys.modules, "mysql.connector", connector)
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=lambda **kwargs: cost_store))
    monkeypatch.setattr(MODULE, "urlopen", lambda *args, **kwargs: Response())
    usage, config = MODULE.collect(collector_args)
    assert usage["trace_usage_ratio"] == 0.95
    assert usage["sample_count"] == 2
    assert usage["evidence"]["mysql"]["trace_rows_window"] == 2
    assert usage["evidence"]["prometheus"]["llm_request_series"] == 1
    assert keys == ["mneme:llm:cost:2026-09-30"]
    assert usage["cost_period_start"] == "2026-09-30T00:00:00+00:00"
    assert usage["cost_period_end"] == captured.isoformat()
    assert usage["measurement_window_start"] == "2026-09-30T11:00:00+00:00"
    assert config["llm_daily_budget_usd"] == 10
    assert cursor.closed and cost_store.closed
    trace_sql, params = next(call for call in cursor.calls if "FROM agent_trace WHERE" in call[0])
    assert "created_at < %s" in trace_sql
    assert params == (datetime(2026, 9, 30, 11), datetime(2026, 9, 30, 12))
