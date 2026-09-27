"""Collect a small, repeatable operational trend report from Prometheus metrics."""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from prometheus_client.parser import text_string_to_metric_families


def _families(payload: str):
    return {family.name: family for family in text_string_to_metric_families(payload)}


def _counter(families: dict, name: str) -> float:
    family = families.get(name.removesuffix("_total")) or families.get(name)
    if family is None:
        return 0.0
    return sum(float(sample.value) for sample in family.samples)


def snapshot(payload: str) -> dict:
    families = _families(payload)
    request_family = families.get("mneme_python_http_requests")
    paths = set()
    request_series = 0
    unmatched_series = 0
    if request_family:
        request_series = len(request_family.samples)
        for sample in request_family.samples:
            path = sample.labels.get("path", "")
            paths.add(path)
            if path == "unmatched":
                unmatched_series += 1

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "input_rejections_total": _counter(families, "mneme_input_rejections_total"),
        "http_request_series": request_series,
        "http_unique_paths": len(paths),
        "http_unmatched_series": unmatched_series,
        "reflection_lease_acquisitions_total": _counter(
            families, "mneme_reflection_lease_acquisitions_total"
        ),
        "reflection_lease_contentions_total": _counter(
            families, "mneme_reflection_lease_contentions_total"
        ),
        "reflection_lease_takeovers_total": _counter(
            families, "mneme_reflection_lease_takeovers_total"
        ),
    }


def _rate(first: dict, last: dict, field: str) -> float:
    started = datetime.fromisoformat(first["captured_at"])
    ended = datetime.fromisoformat(last["captured_at"])
    seconds = max(1.0, (ended - started).total_seconds())
    return max(0.0, float(last[field]) - float(first[field])) / seconds * 60.0


def collect(url: str, samples: int, interval: float, max_series: int, max_paths: int) -> dict:
    if samples < 2:
        raise ValueError("samples must be at least 2 to calculate a trend")
    snapshots = []
    for index in range(samples):
        with urlopen(url, timeout=10) as response:
            snapshots.append(snapshot(response.read().decode("utf-8")))
        if index + 1 < samples and interval > 0:
            time.sleep(interval)

    first, last = snapshots[0], snapshots[-1]
    failures = []
    if last["http_request_series"] > max_series:
        failures.append(
            f"HTTP metric series {last['http_request_series']} exceeds {max_series}"
        )
    if last["http_unique_paths"] > max_paths:
        failures.append(
            f"HTTP metric paths {last['http_unique_paths']} exceeds {max_paths}"
        )
    return {
        "status": "failed" if failures else "passed",
        "samples": snapshots,
        "latest": last,
        "thresholds": {"max_http_series": max_series, "max_http_paths": max_paths},
        "trend": {
            "input_rejection_rate_per_minute": _rate(
                first, last, "input_rejections_total"
            ),
            "http_request_series_delta": last["http_request_series"]
            - first["http_request_series"],
            "http_unique_paths_delta": last["http_unique_paths"]
            - first["http_unique_paths"],
            "reflection_lease_contentions_delta": last[
                "reflection_lease_contentions_total"
            ]
            - first["reflection_lease_contentions_total"],
            "reflection_lease_takeovers_delta": last[
                "reflection_lease_takeovers_total"
            ]
            - first["reflection_lease_takeovers_total"],
        },
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8001/metrics")
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--max-series", type=int, default=200)
    parser.add_argument("--max-paths", type=int, default=100)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = collect(args.url, args.samples, args.interval, args.max_series, args.max_paths)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
