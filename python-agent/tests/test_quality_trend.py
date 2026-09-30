import importlib.util
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
