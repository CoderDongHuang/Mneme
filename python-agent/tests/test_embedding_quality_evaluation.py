import importlib.util
from pathlib import Path

from scripts.quality_policy import CostBudget


SCRIPT = Path(__file__).parents[1] / "scripts" / "evaluate_embedding_quality.py"
SPEC = importlib.util.spec_from_file_location("evaluate_embedding_quality", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def test_embedding_report_scores_pair_separation(monkeypatch):
    monkeypatch.setattr(
        MODULE,
        "embeddings",
        lambda _texts: [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
    )
    manifest = {
        "dataset_id": "test",
        "version": "v1",
        "embedding_cases": [{"id": "one", "anchor": "a", "positive": "b", "negative": "c"}],
    }
    report = MODULE.evaluate(manifest, CostBudget(0.01, 0.3, 0.0))
    assert report["samples"] == 1
    assert report["pair_accuracy"] == 1.0
    assert report["mean_margin"] > 0


def test_embedding_thresholds_report_regression():
    failures = MODULE.apply_thresholds(
        {"pair_accuracy": 0.5}, {"pair_accuracy": {"min": 1.0}}
    )
    assert failures == ["pair_accuracy=0.5 is below 1.0"]
