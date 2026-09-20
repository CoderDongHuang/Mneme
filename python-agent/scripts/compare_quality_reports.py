"""Compare a quality report with a committed baseline and retain failures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_METRICS = (
    "recall@5",
    "mrr",
    "faithfulness_proxy",
    "citation_precision",
    "citation_recall",
    "abstention_proxy",
    "real_llm_evaluation.faithfulness",
    "real_llm_evaluation.answer_relevance",
    "real_llm_evaluation.grounding",
    "real_llm_evaluation.clarity",
)


def _get(value: dict[str, Any], path: str) -> Any:
    current: Any = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def compare(baseline: dict, candidate: dict, max_regression: float = 0.05) -> dict:
    metrics = {}
    failures = []
    for name in DEFAULT_METRICS:
        before = _get(baseline, name)
        after = _get(candidate, name)
        if before is None or after is None:
            continue
        delta = round(float(after) - float(before), 4)
        metrics[name] = {"baseline": float(before), "candidate": float(after), "delta": delta}
        if delta < -max_regression:
            failures.append(f"{name} regressed by {abs(delta):.4f}")

    baseline_version = _get(baseline, "dataset.version") or _get(baseline, "dataset_version")
    candidate_version = _get(candidate, "dataset.version") or _get(candidate, "dataset_version")
    return {
        "status": "failed" if failures else "passed",
        "baseline_version": baseline_version,
        "candidate_version": candidate_version,
        "max_regression": max_regression,
        "metrics": metrics,
        "failed_examples": candidate.get("failed_examples", candidate.get("issues", [])),
        "failures": failures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-regression", type=float, default=0.05)
    args = parser.parse_args()
    report = compare(
        json.loads(args.baseline.read_text(encoding="utf-8")),
        json.loads(args.candidate.read_text(encoding="utf-8")),
        args.max_regression,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
