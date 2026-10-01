import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
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


@pytest.fixture
def measured_usage():
    return {
        "captured_at": "2026-09-30T12:00:00Z", "sample_count": 12,
        "measurement_window_seconds": 86400, "source": "mneme-aggregate-collector",
        "environment": "production", "cost_scope": "deployment-a/providers-primary-and-fallback",
        "cost_period_start": "2026-09-30T00:00:00Z", "cost_period_end": "2026-09-30T12:00:00Z",
        "evidence": {"redis": {"daily_cost_key": "mneme:llm:cost:2026-09-30", "value_present": True}},
        "llm_daily_cost_usd": 9.5, "storage_usage_ratio": 0.85, "trace_usage_ratio": 0.2,
        "session_idle_ratio": 0.85, "knowledge_base_usage_ratio": 0.9,
        "learning_observations": 10, "retention_rate": 0.9,
    }


@pytest.fixture
def billing_export():
    return {
        "schema_version": 1,
        "source": {"kind": "provider_billing_export", "reference": "sanitized-export-123"},
        "environment": "production", "cost_scope": "deployment-a/providers-primary-and-fallback",
        "currency": "USD", "period_start": "2026-09-30T00:00:00Z",
        "period_end": "2026-09-30T12:00:00Z", "exported_at": "2026-09-30T12:30:00Z",
        "complete": True, "actual_cost_usd": 9.4,
    }


NOW = datetime(2026, 9, 30, 13, tzinfo=timezone.utc)


def test_billing_reconciliation_is_explicit_and_does_not_change_settings(measured_usage, billing_export):
    config = {"llm_daily_budget_usd": 10, "session_ttl_hours": 24}
    before = deepcopy((measured_usage, billing_export, config))
    report = MODULE.run(measured_usage, config, now=NOW, billing=billing_export)
    reconciliation = report["billing_reconciliation"]
    assert reconciliation["status"] == "calibrated"
    assert reconciliation["scope"] == "llm_cost_only"
    assert reconciliation["absolute_difference_usd"] == pytest.approx(0.1)
    assert reconciliation["relative_difference"] == pytest.approx(0.1 / 9.4)
    assert reconciliation["billing_cost_scope"] == measured_usage["cost_scope"]
    assert reconciliation["billing_exported_at"] == "2026-09-30T12:30:00+00:00"
    assert reconciliation["reasons"] == []
    assert report["policy"]["budget_ratio"] == 0.95  # Still uses the reservation counter.
    assert report["production_policy_verified"] is False
    assert report["configuration_changed"] is False
    assert report["measured_usage"]["retention_rate"] == 0.9
    assert (measured_usage, billing_export, config) == before


def test_billing_label_without_export_never_calibrates(measured_usage):
    measured_usage["evidence"]["billing"] = "operator-export"
    result = MODULE.run(measured_usage, {}, now=NOW)
    assert result["billing_reconciliation"]["status"] == "unverified"
    assert result["billing_reconciliation"]["reasons"] == ["billing_not_supplied"]


@pytest.mark.parametrize("field,value,reason", [
    ("actual_cost_usd", 20, "cost_difference_exceeds_tolerance"),
    ("cost_scope", "other-account", "cost_scope_mismatch_or_missing"),
    ("period_start", "2026-09-29T00:00:00Z", "cost_interval_mismatch"),
    ("period_end", "2026-09-30T11:00:00Z", "cost_interval_mismatch"),
    ("environment", "test", "nonproduction_or_unknown_environment"),
    ("complete", False, "billing_interval_incomplete"),
    ("actual_cost_usd", 0, "positive_cost_evidence_required"),
    ("source", {"kind": "test_fixture", "reference": "fixture"}, "not_provider_billing_export"),
])
def test_billing_mismatches_stay_unverified(measured_usage, billing_export, field, value, reason):
    billing_export[field] = value
    result = MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)["billing_reconciliation"]
    assert result["status"] == "unverified"
    assert reason in result["reasons"]


@pytest.mark.parametrize("change,reason", [
    ({"cost_scope": None}, "cost_scope_mismatch_or_missing"),
    ({"environment": "unspecified"}, "nonproduction_or_unknown_environment"),
    ({"source": "test-fixture"}, "estimated_cost_source_unverified"),
    ({"cost_period_start": None}, "estimated_cost_interval_missing"),
    ({"evidence": {"redis": {"value_present": False}}}, "estimated_cost_evidence_missing"),
    ({"evidence": {"redis": {"value_present": True, "daily_cost_key": "wrong"}}}, "estimated_cost_key_mismatch"),
])
def test_missing_estimate_provenance_stays_unverified(measured_usage, billing_export, change, reason):
    measured_usage.update(change)
    result = MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)["billing_reconciliation"]
    assert result["status"] == "unverified"
    assert reason in result["reasons"]


@pytest.mark.parametrize("field,value", [
    ("actual_cost_usd", float("nan")), ("actual_cost_usd", float("inf")),
    ("actual_cost_usd", -1), ("actual_cost_usd", True), ("currency", "EUR"),
    ("complete", "true"), ("schema_version", 2), ("schema_version", True),
    ("period_start", "2026-09-30T12:00:00Z"),
    ("period_start", "2026-09-30T00:00:00"), ("period_end", "invalid"),
    ("exported_at", "2026-09-30T11:00:00Z"), ("exported_at", "2099-01-01T00:00:00Z"),
    ("source", {}), ("source", "invoice"), ("cost_scope", "  "),
    ("source", {"kind": "provider_billing_export", "reference": "  "}),
])
def test_malformed_billing_fails_validation(measured_usage, billing_export, field, value):
    billing_export[field] = value
    with pytest.raises(ValueError, match="billing"):
        MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)


def test_missing_billing_fields_fail_validation(measured_usage, billing_export):
    del billing_export["actual_cost_usd"]
    with pytest.raises(ValueError, match="missing fields"):
        MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)


def test_equivalent_timezones_and_zero_spend(measured_usage, billing_export):
    billing_export["period_start"] = "2026-09-30T08:00:00+08:00"
    assert MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)["billing_reconciliation"]["status"] == "calibrated"
    billing_export["actual_cost_usd"] = measured_usage["llm_daily_cost_usd"] = 0
    result = MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)["billing_reconciliation"]
    assert result["status"] == "unverified"
    assert result["relative_difference"] is None
    assert "positive_cost_evidence_required" in result["reasons"]


@pytest.mark.parametrize("field,value", [
    ("sample_count", float("nan")), ("sample_count", 1.5), ("sample_count", True),
    ("sample_count", -1), ("measurement_window_seconds", float("inf")),
    ("measurement_window_seconds", 1.5),
    ("measurement_window_seconds", -1), ("llm_daily_cost_usd", -1),
    ("learning_observations", 13), ("retention_rate", float("nan")),
])
def test_report_rejects_invalid_measurements(measured_usage, field, value):
    measured_usage[field] = value
    with pytest.raises(ValueError, match=field):
        MODULE.run(measured_usage, {}, now=NOW)


def test_cli_accepts_optional_billing_and_preserves_input_files(tmp_path, measured_usage, billing_export):
    captured = datetime.now(timezone.utc)
    if captured.hour == 0 and captured.minute == 0:
        pytest.skip("Need a nonempty UTC cost interval")
    measured_usage["captured_at"] = captured.isoformat()
    start = captured.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    measured_usage["cost_period_start"] = billing_export["period_start"] = start
    measured_usage["cost_period_end"] = billing_export["period_end"] = captured.isoformat()
    measured_usage["evidence"]["redis"]["daily_cost_key"] = f"mneme:llm:cost:{captured.date().isoformat()}"
    billing_export["exported_at"] = captured.isoformat()
    inputs = {"usage": measured_usage, "config": {"llm_daily_budget_usd": 10}, "billing": billing_export}
    paths = {name: tmp_path / f"{name}.json" for name in inputs}
    for name, payload in inputs.items():
        paths[name].write_text(json.dumps(payload), encoding="utf-8")
    originals = {name: path.read_bytes() for name, path in paths.items()}
    for include_billing in (False, True):
        output = tmp_path / f"report-{include_billing}.json"
        command = [sys.executable, str(SCRIPT), "--usage", str(paths["usage"]), "--config", str(paths["config"]),
                   "--report", str(output), "--history-dir", str(tmp_path / "history")]
        if include_billing:
            command.extend(["--billing", str(paths["billing"])])
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        report = json.loads(output.read_text(encoding="utf-8"))
        assert json.loads(completed.stdout) == report
        assert report["billing_reconciliation"]["status"] == ("calibrated" if include_billing else "unverified")
    assert {name: path.read_bytes() for name, path in paths.items()} == originals
    history = list((tmp_path / "history").rglob("*.json"))
    assert len(history) == 2
    assert {json.loads(path.read_text(encoding="utf-8"))["billing_reconciliation"]["status"] for path in history} == {"calibrated", "unverified"}


@pytest.mark.parametrize("estimate,actual,status", [
    (11, 10, "calibrated"), (11.01, 10, "unverified"),
    (0.10, 0.05, "calibrated"), (0.101, 0.05, "unverified"),
])
def test_billing_tolerance_boundaries(measured_usage, billing_export, estimate, actual, status):
    measured_usage["llm_daily_cost_usd"] = estimate
    billing_export["actual_cost_usd"] = actual
    assert MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)["billing_reconciliation"]["status"] == status


@pytest.mark.parametrize("change", [
    {"cost_period_end": "2026-09-30T13:00:00Z"},
    {"cost_period_start": "2026-09-30T12:00:00Z"},
    {"cost_period_start": "2026-09-30T01:00:00Z"},
    {"cost_period_start": "2026-09-29T00:00:00Z"},
])
def test_invalid_estimate_intervals_fail_even_without_billing(measured_usage, change):
    measured_usage.update(change)
    with pytest.raises(ValueError, match="estimated cost interval"):
        MODULE.run(measured_usage, {}, now=NOW)


def test_history_is_append_only_and_corruption_is_not_overwritten(tmp_path, measured_usage, billing_export):
    unverified = MODULE.run(measured_usage, {}, now=NOW)
    first = MODULE.save_history(unverified, tmp_path)
    original = first.read_bytes()
    assert MODULE.save_history(unverified, tmp_path) == first
    calibrated = MODULE.run(measured_usage, {}, now=NOW, billing=billing_export)
    second = MODULE.save_history(calibrated, tmp_path)
    assert first != second
    assert first.parent.name == "2026-09-30"
    assert first.read_bytes() == original
    first.write_text("damaged entry", encoding="utf-8")
    with pytest.raises(ValueError, match="inconsistent"):
        MODULE.save_history(unverified, tmp_path)
    assert first.read_text(encoding="utf-8") == "damaged entry"


def test_cli_rejects_input_output_collision_without_writing(tmp_path):
    config = tmp_path / "config.json"
    config.write_text('{"llm_daily_budget_usd": 10}', encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--usage", str(tmp_path / "missing-usage.json"),
         "--config", str(config), "--report", str(config), "--history-dir", str(tmp_path / "history")],
        capture_output=True, text=True,
    )
    assert completed.returncode != 0
    assert "must differ" in completed.stderr
    assert config.read_text(encoding="utf-8") == '{"llm_daily_budget_usd": 10}'
    assert not (tmp_path / "history").exists()
