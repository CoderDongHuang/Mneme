#!/usr/bin/env python3
"""Gate release decisions on the latest result and its regression trend."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _number(value: object) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


MODEL_METRICS = {
    "rag": ("faithfulness", "answer_relevance"),
    "quiz": ("grounding", "clarity", "answerability"),
    "embedding": ("pair_accuracy", "mean_margin"),
}


def metrics(report: dict, kind: str = "capacity") -> dict[str, float]:
    if kind in MODEL_METRICS:
        source = report.get("real_llm_evaluation", {}) if kind != "embedding" else report
        return {
            key: -value for key in MODEL_METRICS[kind]
            if (value := _number(source.get(key))) is not None
        }
    load = report.get("load", {})
    fault_recovery = report.get("fault_recovery", [])
    if isinstance(report.get("metrics"), dict):
        return {
            key: value for key, raw in report["metrics"].items()
            if (value := _number(raw)) is not None
        }
    if isinstance(report.get("summary"), dict):
        return {
            key: value for key, raw in report["summary"].items()
            if (value := _number(raw)) is not None
        }
    recovery = [
        float(item["recovery_seconds"])
        for item in fault_recovery
        if isinstance(item, dict) and _number(item.get("recovery_seconds")) is not None
    ]
    result: dict[str, float] = {}
    for key in ("p95_latency_ms", "errors", "completed", "requested"):
        value = _number(load.get(key))
        if value is not None:
            result[key] = value
    if recovery:
        result["max_recovery_seconds"] = max(recovery)
        result["mean_recovery_seconds"] = sum(recovery) / len(recovery)
        result["fault_rounds_completed"] = float(len(recovery))
    return result


def evaluate(reports: list[dict], max_regressions: dict[str, float], allow_single: bool = False, kind: str = "capacity") -> dict:
    if len(reports) < 2 and not allow_single:
        raise ValueError("至少需要当前报告和上一期报告才能计算趋势")
    latest = reports[-1]
    previous = reports[-2] if len(reports) >= 2 else None
    latest_metrics = metrics(latest, kind)
    previous_metrics = metrics(previous, kind) if previous else {}
    trend = {
        key: round(latest_metrics[key] - previous_metrics[key], 6)
        for key in latest_metrics
        if key in previous_metrics
    }
    failures = []
    if latest.get("status") not in {None, "passed", "completed"}:
        failures.append(f"latest report status is {latest.get('status')}")
    if kind in MODEL_METRICS:
        for report in reports:
            if report.get("quality_gate", {}).get("status") != "passed":
                failures.append("model quality gate did not pass")
            if kind != "embedding" and report.get("real_llm_evaluation", {}).get("status") != "completed":
                failures.append("real model evaluation is incomplete")
        if previous and previous.get("dataset") != latest.get("dataset"):
            failures.append("dataset changed; trend requires matching dataset revisions")
    for key, limit in max_regressions.items():
        if key not in latest_metrics or (previous and key not in previous_metrics):
            failures.append(f"required metric {key} is missing")
        elif key in trend and trend[key] > limit:
            failures.append(f"{key} regression {trend[key]:.6f} exceeds {limit}")
    return {
        "status": "failed" if failures else "passed" if previous else "insufficient_history",
        "report_count": len(reports),
        "latest": latest_metrics,
        "previous": previous_metrics,
        "trend": trend,
        "max_regressions": max_regressions,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, nargs="+", required=True)
    parser.add_argument("--max-p95-regression-ms", type=float, default=250.0)
    parser.add_argument("--max-recovery-regression-seconds", type=float, default=30.0)
    parser.add_argument("--max-error-regression", type=float, default=0.0)
    parser.add_argument("--allow-single", action="store_true")
    parser.add_argument("--kind", choices=("capacity", *MODEL_METRICS), default="capacity")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    limits = (
        {key: 0.05 for key in MODEL_METRICS[args.kind]}
        if args.kind in MODEL_METRICS else {
            "p95_latency_ms": args.max_p95_regression_ms,
            "max_recovery_seconds": args.max_recovery_regression_seconds,
            "errors": args.max_error_regression,
        }
    )
    result = evaluate(
        reports,
        limits,
        args.allow_single,
        args.kind,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
