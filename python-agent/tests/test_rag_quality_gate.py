import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate_rag.py"
SPEC = importlib.util.spec_from_file_location("evaluate_rag", SCRIPT)
assert SPEC and SPEC.loader
evaluate_rag = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluate_rag)


def test_quality_gate_reports_all_failed_thresholds():
    failures = evaluate_rag.apply_thresholds(
        {"recall@5": 0.8, "p95_latency_ms": 300},
        {"recall@5": {"min": 0.9}, "p95_latency_ms": {"max": 250}},
    )
    assert failures == [
        "recall@5=0.8 is below 0.9",
        "p95_latency_ms=300.0 exceeds 250",
    ]


def test_quality_gate_rejects_missing_metrics():
    assert evaluate_rag.apply_thresholds({}, {"mrr": {"min": 0.8}}) == [
        "missing metric: mrr"
    ]
