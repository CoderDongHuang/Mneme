import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[2] / "scripts" / "quality_trend.py"
SPEC = importlib.util.spec_from_file_location("quality_trend", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def report(p95, recovery, errors=0, status="passed"):
    return {
        "status": status,
        "load": {"p95_latency_ms": p95, "errors": errors},
        "fault_recovery": [{"recovery_seconds": recovery}],
    }


def test_trend_passes_with_stable_metrics():
    result = MODULE.evaluate(
        [report(100, 10), report(120, 15)],
        {"p95_latency_ms": 25, "max_recovery_seconds": 10, "errors": 0},
    )
    assert result["status"] == "passed"
    assert result["trend"]["p95_latency_ms"] == 20


def test_trend_rejects_regression_and_single_report():
    with pytest.raises(ValueError):
        MODULE.evaluate([report(100, 10)], {})
    assert MODULE.evaluate([report(100, 10)], {}, allow_single=True)["status"] == "insufficient_history"
    result = MODULE.evaluate(
        [report(100, 10), report(500, 50, errors=1)],
        {"p95_latency_ms": 25, "max_recovery_seconds": 10, "errors": 0},
    )
    assert result["status"] == "failed"
    assert len(result["failures"]) == 3


def test_trend_rejects_missing_required_metric():
    result = MODULE.evaluate(
        [report(100, 10), {"status": "passed", "load": {"errors": 0}}],
        {"p95_latency_ms": 25, "max_recovery_seconds": 10, "errors": 0},
    )
    assert result["status"] == "failed"
    assert "required metric p95_latency_ms is missing" in result["failures"]


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -float("inf")])
def test_trend_rejects_non_finite_metrics(invalid):
    result = MODULE.evaluate(
        [report(100, 10), report(invalid, 10)],
        {"p95_latency_ms": 25, "max_recovery_seconds": 10, "errors": 0},
    )
    assert result["status"] == "failed"
    assert "required metric p95_latency_ms is missing" in result["failures"]


def test_real_model_trend_requires_same_dataset_and_actual_scores():
    base = {"dataset": {"version": "v1"}, "quality_gate": {"status": "passed"},
            "real_llm_evaluation": {"status": "completed", "faithfulness": 0.9, "answer_relevance": 0.9}}
    current = {"dataset": {"version": "v1"}, "quality_gate": {"status": "passed"},
               "real_llm_evaluation": {"status": "completed", "faithfulness": 0.8, "answer_relevance": 0.9}}
    limits = {"faithfulness": 0.05, "answer_relevance": 0.05}
    assert MODULE.evaluate([base, current], limits, kind="rag")["status"] == "failed"
    current["dataset"] = {"version": "v2"}
    assert any("dataset changed" in failure for failure in MODULE.evaluate([base, current], limits, kind="rag")["failures"])
    current["real_llm_evaluation"].pop("faithfulness")
    assert any("required metric" in failure for failure in MODULE.evaluate([base, current], limits, kind="rag")["failures"])


@pytest.mark.parametrize("invalid", [-1, float("nan"), float("inf"), -float("inf"), True])
def test_regression_thresholds_must_be_finite_and_nonnegative(invalid):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        MODULE.evaluate([report(100, 10), report(100, 10)], {"p95_latency_ms": invalid})


@pytest.mark.parametrize("status", [None, "failed", "running", "insufficient_history"])
def test_every_capacity_run_must_have_success_status(status):
    result = MODULE.evaluate([report(100, 10, status=status), report(100, 10), report(100, 10)], {})
    assert result["status"] == "failed"
    assert any("report 1 status" in failure for failure in result["failures"])


def test_all_history_metrics_and_gate_failures_are_validated():
    oldest = report(float("nan"), 10)
    oldest["quality_gate"] = {"status": "passed", "failures": ["load failed"]}
    result = MODULE.evaluate([oldest, report(100, 10), report(100, 10)], {"p95_latency_ms": 1})
    assert result["status"] == "failed"
    assert "required metric p95_latency_ms is missing" in result["failures"]
    assert any("quality gate did not pass" in failure for failure in result["failures"])


def with_provenance(value, run_id):
    value["provenance"] = {
        "schema_version": 1, "kind": "capacity", "report_id": f"report-{run_id}",
        "repository": "owner/mneme", "branch": "main", "run_id": str(run_id),
        "configuration": {"requests": 600, "duration_seconds": 120},
    }
    return value


@pytest.mark.parametrize("key,value", [
    ("branch", "other"), ("repository", "other/mneme"),
    ("configuration", {"requests": 100}), ("kind", "rag"), ("schema_version", 2),
    ("report_id", "report-1"), ("run_id", "1"),
])
def test_provenance_prevents_incomparable_or_self_comparison(key, value):
    base = with_provenance(report(100, 10), 1)
    current = with_provenance(report(100, 10), 2)
    current["provenance"][key] = value
    assert MODULE.evaluate([base, current], {})["status"] == "failed"


def test_missing_provenance_and_capacity_workload_changes_fail():
    base = with_provenance(report(100, 10), 1)
    assert MODULE.evaluate([base, report(100, 10)], {})["status"] == "failed"
    base = report(100, 10)
    base["profile"] = ["small"]
    current = deepcopy(base)
    current["profile"] = ["large"]
    assert MODULE.evaluate([base, current], {})["status"] == "failed"


def test_missing_model_dataset_revision_fails_even_for_bootstrap():
    value = {"quality_gate": {"status": "passed"}, "samples": 2,
             "pair_accuracy": 1, "mean_margin": 0.5}
    result = MODULE.evaluate([value], {}, allow_single=True, kind="embedding")
    assert result["status"] == "failed"
    assert "dataset revision is missing" in result["failures"]


def test_model_history_sample_and_threshold_changes_are_not_comparable():
    base = {"dataset": {"sha256": "revision"}, "quality_gate": {"status": "passed", "thresholds": {"min": 0.8}},
            "real_llm_evaluation": {"status": "completed", "samples": 8, "faithfulness": 0.9, "answer_relevance": 0.9}}
    current = deepcopy(base)
    current["real_llm_evaluation"]["samples"] = 1
    assert MODULE.evaluate([base, current], {}, kind="rag")["status"] == "failed"
    current = deepcopy(base)
    current["quality_gate"]["thresholds"] = {"min": 0.7}
    assert MODULE.evaluate([base, current], {}, kind="rag")["status"] == "failed"


def run_cli(tmp_path, values, *options):
    paths = []
    for index, value in enumerate(values):
        path = tmp_path / f"run-{index}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        paths.append(str(path))
    output = tmp_path / "trend.json"
    process = subprocess.run([sys.executable, str(SCRIPT), "--reports", *paths, "--report", str(output), *options],
                             text=True, capture_output=True)
    return process, json.loads(output.read_text()) if output.exists() else None


def test_cli_selects_comparable_history_and_preserves_failed_baseline(tmp_path):
    incompatible = with_provenance(report(100, 10), 3)
    incompatible["provenance"]["configuration"] = {"requests": 1}
    base = with_provenance(report(100, 10, status="failed"), 2)
    current = with_provenance(report(100, 10), 4)
    process, result = run_cli(tmp_path, [incompatible, base, current], "--select-history")
    assert process.returncode == 1
    assert result["status"] == "failed"
    assert result["sources"][0]["run_id"] == "2"
    assert len(result["discarded_history"]) == 1


@pytest.mark.parametrize("mode,expected_code", [("--select-history", 1), ("--allow-single", 1), ("--bootstrap", 0)])
def test_cli_only_explicit_bootstrap_allows_insufficient_history(tmp_path, mode, expected_code):
    process, result = run_cli(tmp_path, [with_provenance(report(100, 10), 1)], mode)
    assert process.returncode == expected_code
    assert result["status"] == "insufficient_history"
    assert result["trend"] == {}


def test_bootstrap_cannot_hide_failed_real_report(tmp_path):
    process, result = run_cli(tmp_path, [report(100, 10, status="failed")], "--bootstrap")
    assert process.returncode == 1
    assert result["status"] == "failed"


def test_cli_refuses_duplicate_paths_and_relabeling_provenance(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(with_provenance(report(100, 10), 1)), encoding="utf-8")
    for arguments in [
        ["--reports", str(path), str(path), "--report", str(tmp_path / "trend.json")],
        ["--reports", str(path), "--record-provenance", "--configuration", '{"requests":600}'],
    ]:
        process = subprocess.run([sys.executable, str(SCRIPT), *arguments], text=True, capture_output=True)
        assert process.returncode != 0
    assert json.loads(path.read_text())["provenance"]["run_id"] == "1"


def test_provenance_records_input_hashes_and_ci_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("GITHUB_REF_NAME", "main")
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report(100, 10)), encoding="utf-8")
    dataset = tmp_path / "dataset.json"
    dataset.write_text("[]", encoding="utf-8")
    process = subprocess.run([sys.executable, str(SCRIPT), "--reports", str(path), "--record-provenance",
                              "--configuration", '{"requests":600}', "--provenance-input", str(dataset)],
                             capture_output=True, text=True)
    assert process.returncode == 0, process.stderr
    source = json.loads(path.read_text())["provenance"]
    assert source["run_id"] == "123"
    assert source["branch"] == "main"
    assert len(source["configuration"]["inputs"][dataset.as_posix()]) == 64


def test_regression_uses_unrounded_delta_at_threshold_boundary():
    result = MODULE.evaluate([report(100, 10), report(100.0000004, 10)], {"p95_latency_ms": 0})
    assert result["status"] == "failed"


@pytest.mark.parametrize("kind", ["rag", "quiz", "embedding"])
def test_real_model_bootstrap_then_second_run_passes_trend(tmp_path, kind):
    evaluation = {key: 0.9 for key in MODULE.MODEL_METRICS[kind]}
    evaluation["samples"] = 2
    value = {"dataset": {"sha256": "dataset-revision"}, "quality_gate": {"status": "passed"}}
    if kind == "embedding":
        value.update(evaluation, model="text-embedding-v3")
    else:
        value["real_llm_evaluation"] = {**evaluation, "status": "completed"}
    base = with_provenance(value, 1)
    base["provenance"]["kind"] = kind
    first, baseline = run_cli(tmp_path, [base], "--bootstrap", "--kind", kind)
    assert first.returncode == 0
    assert baseline["status"] == "insufficient_history"
    current = deepcopy(base)
    current["provenance"].update(report_id="report-2", run_id="2")
    second, trend = run_cli(tmp_path, [base, current], "--select-history", "--kind", kind)
    assert second.returncode == 0, second.stderr
    assert trend["status"] == "passed"
    assert all(delta == 0 for delta in trend["trend"].values())
