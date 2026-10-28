"""Compare a quality report with a committed baseline and retain failures."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


DEFAULT_METRICS = (
    "recall@5",
    "mrr",
    "top_evidence_term_support",
    "top_evidence_precision",
    "evidence_hit_recall",
    "no_answer_evidence_absence",
    "faithfulness_proxy",
    "citation_precision",
    "citation_recall",
    "abstention_proxy",
    "real_llm_evaluation.faithfulness",
    "real_llm_evaluation.answer_relevance",
    "real_llm_evaluation.grounding",
    "real_llm_evaluation.clarity",
    "real_llm_evaluation.answer_point_coverage",
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
    for path in ("schema_version", "dataset.version", "dataset.sha256", "configuration.embedding_model", "configuration.top_k",
                 "configuration.no_answer_scoring_version", "configuration.focus_gate_enabled"):
        before, after = _get(baseline, path), _get(candidate, path)
        if before is not None and after != before:
            failures.append(f"{path} changed; reports are not comparable")
    baseline_has_model = _get(baseline, "real_llm_evaluation.status") == "completed"
    candidate_has_model = _get(candidate, "real_llm_evaluation.status") == "completed"
    if baseline_has_model and not candidate_has_model:
        failures.append("candidate is missing the baseline's real model evaluation")
    if baseline_has_model and candidate_has_model:
        for path in ("configuration.chat_models.configured", "configuration.chat_models.primary",
                     "configuration.chat_models.fallback", "configuration.qa_prompt_sha256",
                     "configuration.verification_prompt_sha256", "configuration.answer_point_scoring_version"):
            if _get(baseline, path) != _get(candidate, path):
                failures.append(f"{path} changed; model reports are not comparable")
    if _get(baseline, "configuration.retrieval") != _get(candidate, "configuration.retrieval"):
        failures.append("configuration.retrieval changed; reports are not comparable")
    for name in DEFAULT_METRICS:
        before = _get(baseline, name)
        after = _get(candidate, name)
        if before is None:
            continue
        if after is None:
            failures.append(f"missing candidate metric: {name}")
            continue
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in (before, after)):
            failures.append(f"{name} is not finite numeric evidence")
            continue
        delta = round(float(after) - float(before), 4)
        metrics[name] = {"baseline": float(before), "candidate": float(after), "delta": delta}
        if delta < -max_regression:
            failures.append(f"{name} regressed by {abs(delta):.4f}")

    baseline_version = _get(baseline, "dataset.version") or _get(baseline, "dataset_version")
    candidate_version = _get(candidate, "dataset.version") or _get(candidate, "dataset_version")
    if not metrics:
        failures.append("no comparable metrics")
    return {
        "status": "failed" if failures else "passed",
        "comparison_scope": "retrieval_and_model" if baseline_has_model else "retrieval_only",
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
