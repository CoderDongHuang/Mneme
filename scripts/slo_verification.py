#!/usr/bin/env python3
"""Collect a bounded Prometheus-compatible SLO snapshot and enforce targets."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path


def scrape(url: str) -> dict[str, list[tuple[dict[str, str], float]]]:
    with urllib.request.urlopen(url, timeout=10) as response:
        lines = response.read().decode().splitlines()
    metrics: dict[str, list[tuple[dict[str, str], float]]] = {}
    for line in lines:
        if not line or line.startswith("#") or " " not in line:
            continue
        name, raw = line.rsplit(" ", 1)
        labels: dict[str, str] = {}
        if "{" in name:
            name, label_text = name.split("{", 1)
            for item in label_text.rstrip("}").split(","):
                if item and "=" in item:
                    key, value = item.split("=", 1)
                    labels[key] = value.strip('"')
        try:
            metrics.setdefault(name, []).append((labels, float(raw)))
        except ValueError:
            continue
    return metrics


def snapshot(metrics: dict[str, list[tuple[dict[str, str], float]]]) -> dict:
    rows = metrics.get("mneme_python_http_requests_total", [])
    total = sum(value for _, value in rows)
    errors = sum(value for labels, value in rows if labels.get("status", "").startswith("5"))
    bucket_totals: dict[float, float] = {}
    for labels, value in metrics.get("mneme_python_http_request_duration_seconds_bucket", []):
        if "le" in labels and labels["le"] != "+Inf":
            bound = float(labels["le"])
            bucket_totals[bound] = bucket_totals.get(bound, 0.0) + value
    buckets = sorted(bucket_totals.items())
    p95 = buckets[-1][0] if buckets else 0.0
    if buckets and total:
        threshold = total * 0.95
        p95 = next((bound for bound, count in buckets if count >= threshold), buckets[-1][0])
    return {"requests": total, "errors": errors, "availability": (total - errors) / total if total else 1.0, "p95_seconds": p95}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001/metrics")
    parser.add_argument("--duration-seconds", type=int, default=30)
    parser.add_argument("--interval-seconds", type=int, default=5)
    parser.add_argument("--slo", type=Path, default=Path("observability/slo.json"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    snapshots = []
    deadline = time.monotonic() + max(0, args.duration_seconds)
    while not snapshots or time.monotonic() < deadline:
        snapshots.append(snapshot(scrape(args.url)))
        if time.monotonic() < deadline:
            time.sleep(max(1, args.interval_seconds))
    target = json.loads(args.slo.read_text(encoding="utf-8"))["targets"]
    latest = snapshots[-1]
    failures = []
    if latest["availability"] < target["availability"]:
        failures.append("availability below target")
    if latest["p95_seconds"] > target["http_p95_seconds"]:
        failures.append("p95 latency above target")
    report = {"status": "failed" if failures else "passed", "samples": snapshots, "latest": latest, "targets": target, "failures": failures}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
