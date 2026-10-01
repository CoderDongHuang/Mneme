#!/usr/bin/env python3
"""Gate release decisions on the latest result and its regression trend."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        return number if math.isfinite(number) else None
    return None


def nonnegative(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError("threshold must be finite and nonnegative")
    return number


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


def provenance(kind: str, configuration: dict) -> dict:
    return {
        "schema_version": 1,
        "kind": kind,
        "report_id": uuid.uuid4().hex,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "repository": os.getenv("GITHUB_REPOSITORY"),
        "branch": os.getenv("GITHUB_REF_NAME"),
        "commit": os.getenv("GITHUB_SHA"),
        "run_id": os.getenv("GITHUB_RUN_ID"),
        "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "configuration": configuration,
    }


def comparison_failures(previous: dict, latest: dict, kind: str) -> list[str]:
    failures = []
    before, after = previous.get("provenance"), latest.get("provenance")
    if before is not None or after is not None:
        if not isinstance(before, dict) or not isinstance(after, dict):
            return ["report provenance is missing"]
        for value in (before, after):
            if value.get("schema_version") != 1 or value.get("kind") != kind:
                failures.append("report provenance schema or kind is invalid")
            if not value.get("report_id") or not value.get("configuration"):
                failures.append("report provenance identity or configuration is missing")
        for key in ("repository", "branch", "configuration"):
            if before.get(key) != after.get(key):
                failures.append(f"{key} changed; reports are not comparable")
        for key in ("report_id", "run_id"):
            if before.get(key) and before.get(key) == after.get(key):
                failures.append(f"self-comparison: same {key}")
    if previous.get("seed_identity") and previous.get("seed_identity") == latest.get("seed_identity"):
        failures.append("self-comparison: same seed_identity")
    if kind in MODEL_METRICS:
        for report in (previous, latest):
            dataset = report.get("dataset")
            if not isinstance(dataset, dict) or not (dataset.get("sha256") or dataset.get("version")):
                failures.append("dataset revision is missing")
        if previous.get("dataset") != latest.get("dataset"):
            failures.append("dataset changed; trend requires matching dataset revisions")
        for key in ("model", "samples", "thresholds"):
            def field(report):
                if key == "thresholds":
                    return report.get("quality_gate", {}).get(key)
                source = report if kind == "embedding" else report.get("real_llm_evaluation", {})
                return source.get(key)
            if field(previous) != field(latest):
                failures.append(f"{key} changed; reports are not comparable")
    elif before is None and after is None:
        for key in ("profile", "fault_matrix", "configuration"):
            if previous.get(key) != latest.get(key):
                failures.append(f"{key} changed; reports are not comparable")
        for key in ("requested", "concurrency"):
            if previous.get("load", {}).get(key) != latest.get("load", {}).get(key):
                failures.append(f"load {key} changed; reports are not comparable")
    return failures


def evaluate(reports: list[dict], max_regressions: dict[str, float], allow_single: bool = False, kind: str = "capacity") -> dict:
    if not reports:
        raise ValueError("at least one report is required")
    if any(not isinstance(report, dict) for report in reports):
        raise ValueError("reports must be JSON objects")
    if kind not in ("capacity", *MODEL_METRICS):
        raise ValueError(f"unsupported report kind: {kind}")
    for key, limit in max_regressions.items():
        if _number(limit) is None or limit < 0:
            raise ValueError(f"{key} threshold must be finite and nonnegative")
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
    for index, report in enumerate(reports):
        if not isinstance(report, dict):
            raise ValueError("reports must be JSON objects")
        status = report.get("status")
        if status not in {"passed", "completed"} and (kind == "capacity" or status is not None):
            failures.append(f"report {index + 1} status is {status}")
        gate = report.get("quality_gate", {})
        if gate.get("failures") or gate.get("status") not in {None, "passed"}:
            failures.append(f"report {index + 1} quality gate did not pass")
        source = report.get("provenance")
        if source is not None and (not isinstance(source, dict) or source.get("schema_version") != 1
                                   or source.get("kind") != kind or not source.get("report_id")
                                   or not source.get("configuration")):
            failures.append("report provenance is invalid")
        if kind in MODEL_METRICS:
            if report.get("quality_gate", {}).get("status") != "passed":
                failures.append("model quality gate did not pass")
            if kind != "embedding" and report.get("real_llm_evaluation", {}).get("status") != "completed":
                failures.append("real model evaluation is incomplete")
            dataset = report.get("dataset")
            if not isinstance(dataset, dict) or not (dataset.get("sha256") or dataset.get("version")):
                failures.append("dataset revision is missing")
            evaluation = report if kind == "embedding" else report.get("real_llm_evaluation", {})
            if "samples" in evaluation and (_number(evaluation["samples"]) is None or evaluation["samples"] <= 0):
                failures.append("model evaluation has no valid samples")
        else:
            for fault in report.get("fault_recovery", []):
                if (not isinstance(fault, dict) or _number(fault.get("recovery_seconds")) is None
                        or fault["recovery_seconds"] < 0 or fault.get("status") not in {None, "passed"}):
                    failures.append("fault recovery is incomplete or invalid")
            for key, value in metrics(report, kind).items():
                if value < 0:
                    failures.append(f"capacity metric {key} is negative")
        for key in set(max_regressions) | set(MODEL_METRICS.get(kind, ())):
            if key not in metrics(report, kind):
                failures.append(f"required metric {key} is missing")
        if index < len(reports) - 1:
            failures.extend(comparison_failures(report, latest, kind))
    for key, limit in max_regressions.items():
        if key in trend and latest_metrics[key] - previous_metrics[key] > limit:
            failures.append(f"{key} regression {trend[key]:.6f} exceeds {limit}")
    return {
        "status": "failed" if failures else "passed" if previous else "insufficient_history",
        "report_count": len(reports),
        "latest": latest_metrics,
        "previous": previous_metrics,
        "trend": trend,
        "max_regressions": max_regressions,
        "failures": failures,
        "sources": [report.get("provenance") for report in reports],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, nargs="+", required=True)
    parser.add_argument("--max-p95-regression-ms", type=nonnegative, default=250.0)
    parser.add_argument("--max-recovery-regression-seconds", type=nonnegative, default=30.0)
    parser.add_argument("--max-error-regression", type=nonnegative, default=0.0)
    parser.add_argument("--allow-single", action="store_true")
    parser.add_argument("--bootstrap", action="store_true", help="Validate and collect one baseline without passing a trend")
    parser.add_argument("--select-history", action="store_true", help="Select the newest comparable prior report (newest first)")
    parser.add_argument("--record-provenance", action="store_true")
    parser.add_argument("--provenance-input", type=Path, action="append", default=[])
    parser.add_argument("--configuration", type=json.loads, default={})
    parser.add_argument("--kind", choices=("capacity", *MODEL_METRICS), default="capacity")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
    if args.record_provenance:
        if len(reports) != 1 or not isinstance(args.configuration, dict) or not args.configuration:
            parser.error("recording provenance requires one report and a nonempty configuration object")
        if reports[0].get("provenance"):
            parser.error("report already has provenance; refusing to relabel existing evidence")
        configuration = {
            **args.configuration,
            "inputs": {path.as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in args.provenance_input},
        }
        reports[0]["provenance"] = provenance(args.kind, configuration)
        args.reports[0].write_text(json.dumps(reports[0], ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        return 0
    if args.report is None:
        parser.error("--report is required for trend evaluation")
    if len({path.resolve() for path in args.reports}) != len(args.reports):
        parser.error("self-comparison: report paths must be distinct")
    if args.bootstrap and (len(reports) != 1 or args.select_history):
        parser.error("bootstrap requires exactly one current report")
    discarded = []
    selected_paths = args.reports
    if args.select_history:
        latest = reports[-1]
        selected_paths = [args.reports[-1]]
        selected = []
        for path, candidate in zip(args.reports[:-1], reports[:-1]):
            reasons = comparison_failures(candidate, latest, args.kind)
            if not reasons:
                selected = [candidate]
                selected_paths.insert(0, path)
                break
            discarded.append({"path": str(path), "reasons": reasons})
        reports = [*selected, latest]
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
        args.allow_single or args.bootstrap or args.select_history,
        args.kind,
    )
    result["report_paths"] = [str(path) for path in selected_paths]
    result["discarded_history"] = discarded
    result["bootstrap"] = args.bootstrap
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" or (args.bootstrap and result["status"] == "insufficient_history") else 1


if __name__ == "__main__":
    raise SystemExit(main())
