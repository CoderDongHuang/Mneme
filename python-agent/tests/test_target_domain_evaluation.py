import importlib.util
from pathlib import Path


ROOT = Path(__file__).parents[1]


def _load(name: str, relative: str):
    path = Path(__file__).parents[1] / "scripts" / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_target_domain_manifest_is_versioned_and_meets_sample_floor():
    module = _load("validate_evaluation_dataset", "validate_evaluation_dataset.py")
    report = module.validate(ROOT / "evaluation" / "target_domain_manifest.json")
    assert report["status"] == "passed"
    assert report["version"] == "2026.09.20-v1"
    assert report["counts"] == {"rag": 12, "quiz": 6, "document_ai": 3, "embedding": 4}


def test_quality_report_comparison_keeps_failed_examples():
    module = _load("compare_quality_reports", "compare_quality_reports.py")
    report = module.compare(
        {"dataset": {"version": "old"}, "recall@5": 1.0, "mrr": 1.0},
        {"dataset": {"version": "new"}, "recall@5": 0.98, "mrr": 0.8, "failed_examples": [{"id": "case-2"}]},
        max_regression=0.05,
    )
    assert report["status"] == "failed"
    assert report["candidate_version"] == "new"
    assert report["failed_examples"] == [{"id": "case-2"}]
    assert "mrr regressed" in report["failures"][0]
