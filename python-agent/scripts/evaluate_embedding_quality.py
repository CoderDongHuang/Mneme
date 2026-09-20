"""Evaluate real embedding separation on sanitized target-domain pairs."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path


AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

from app.utils.embedding import embeddings  # noqa: E402
from scripts.quality_policy import CostBudget, require_sanitized  # noqa: E402


def cosine(left: list[float], right: list[float]) -> float:
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return sum(a * b for a, b in zip(left, right)) / (denominator or 1.0)


def evaluate(manifest: dict, budget: CostBudget) -> dict:
    cases = manifest.get("embedding_cases", [])
    require_sanitized(cases)
    details = []
    for index, case in enumerate(cases, start=1):
        texts = [case["anchor"], case["positive"], case["negative"]]
        budget.reserve(
            input_tokens=max(1, sum(len(text) for text in texts) // 2),
            output_tokens=0,
            label=f"Embedding 样本 {index}",
        )
        anchor, positive, negative = embeddings(texts)
        positive_similarity = cosine(anchor, positive)
        negative_similarity = cosine(anchor, negative)
        margin = positive_similarity - negative_similarity
        details.append(
            {
                "id": case["id"],
                "positive_similarity": round(positive_similarity, 4),
                "negative_similarity": round(negative_similarity, 4),
                "margin": round(margin, 4),
                "passed": margin > 0,
            }
        )
    return {
        "dataset": {"name": manifest["dataset_id"], "version": manifest["version"]},
        "model": embeddings.name() if hasattr(embeddings, "name") else "test-embedding",
        "samples": len(details),
        "pair_accuracy": round(sum(item["passed"] for item in details) / max(1, len(details)), 4),
        "mean_margin": round(sum(item["margin"] for item in details) / max(1, len(details)), 4),
        "reserved_cost": round(budget.reserved_usd, 6),
        "max_cost": budget.max_usd,
        "details": details,
        "failed_examples": [item for item in details if not item["passed"]],
    }


def apply_thresholds(report: dict, thresholds: dict) -> list[str]:
    failures = []
    for metric, rule in thresholds.items():
        value = float(report.get(metric, 0.0))
        if "min" in rule and value < float(rule["min"]):
            failures.append(f"{metric}={value} is below {rule['min']}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--thresholds", type=Path, required=True)
    parser.add_argument("--input-cost-per-million", type=float, required=True)
    parser.add_argument("--max-estimated-cost", type=float, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    thresholds = json.loads(args.thresholds.read_text(encoding="utf-8"))
    report = evaluate(
        manifest,
        CostBudget(args.max_estimated_cost, args.input_cost_per_million, 0.0),
    )
    failures = apply_thresholds(report, thresholds)
    report["quality_gate"] = {"status": "failed" if failures else "passed", "thresholds": thresholds, "failures": failures}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
