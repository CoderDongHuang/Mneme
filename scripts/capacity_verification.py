#!/usr/bin/env python3
"""Run configurable long-duration load and multi-fault recovery checks."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ci-internal-token-at-least-32-characters"


class CapacityVerificationError(RuntimeError):
    pass


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Internal-Service-Token": TOKEN},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            value = json.loads(response.read() or b"null")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
        raise CapacityVerificationError(f"request failed: {method} {url}: {error}") from error
    if isinstance(value, dict) and value.get("code") not in {None, 200}:
        raise CapacityVerificationError(f"request failed: {method} {url}: {value}")
    return value.get("data", value) if isinstance(value, dict) else value


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(len(ordered) * fraction) - 1)
    return ordered[min(len(ordered) - 1, index)]


def compose(compose_files: list[str], *args: str) -> str:
    command = ["docker", "compose"]
    for compose_file in compose_files:
        command.extend(["-f", compose_file])
    command.extend(args)
    result = subprocess.run(
        command,
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout


def wait_http(url: str, timeout: int = 240) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request_json(url)
            return
        except CapacityVerificationError:
            time.sleep(2)
    raise CapacityVerificationError(f"service did not become ready: {url}")


def seed_data(agent_url: str, profile: list[str]) -> tuple[str, list[str]]:
    user_id = f"capacity-{uuid.uuid4().hex[:12]}"
    fixture_by_profile = {
        "small": "rag-fixture.txt",
        "medium": "rag-fixture.md",
        "large": "rag-fixture.docx",
    }
    documents_by_profile = {"small": 1, "medium": 10, "large": 50}
    knowledge_bases = []
    for index, size in enumerate(profile):
        fixture = fixture_by_profile.get(size)
        if not fixture:
            raise CapacityVerificationError(f"unsupported data profile: {size}")
        kb_id = f"capacity-{size}-{index}"
        for document_index in range(documents_by_profile[size]):
            request_json(
                f"{agent_url}/api/v1/knowledge/internal/ingest",
                "POST",
                {
                    "user_id": user_id,
                    "kb_id": kb_id,
                    "file_path": f"/test-fixtures/{fixture}",
                    "document_id": f"doc-{kb_id}-{document_index}",
                },
            )
        knowledge_bases.append(kb_id)
    return user_id, knowledge_bases


def load_test(urls: list[str], requests: int, concurrency: int, duration_seconds: int) -> dict:
    if requests < 1 or concurrency < 1:
        raise ValueError("requests 和 concurrency 必须为正数")
    started = time.monotonic()
    latencies: list[float] = []
    errors = 0

    def one(index: int) -> float:
        request_started = time.perf_counter()
        request_json(urls[index % len(urls)])
        return (time.perf_counter() - request_started) * 1000

    submitted = 0
    batches = max(1, math.ceil(requests / (concurrency * 2)))
    batch_interval = max(0.0, duration_seconds / batches)
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        while submitted < requests:
            batch_started = time.monotonic()
            batch_size = min(concurrency * 2, requests - submitted)
            futures = [pool.submit(one, submitted + index) for index in range(batch_size)]
            submitted += batch_size
            for future in futures:
                try:
                    latencies.append(future.result())
                except Exception:
                    errors += 1
            remaining = batch_interval - (time.monotonic() - batch_started)
            if remaining > 0:
                time.sleep(remaining)
    if not latencies:
        raise CapacityVerificationError("load test produced no successful requests")
    return {
        "requested": requests,
        "completed": len(latencies),
        "errors": errors,
        "concurrency": concurrency,
        "duration_seconds": round(time.monotonic() - started, 2),
        "mean_latency_ms": round(statistics.mean(latencies), 2),
        "p95_latency_ms": round(percentile(latencies, 0.95), 2),
        "p99_latency_ms": round(percentile(latencies, 0.99), 2),
    }


def recover_faults(
    compose_files: list[str],
    services: list[str],
    agent_urls: list[str],
    probe_urls: list[str],
    rounds: int,
) -> list[dict]:
    results = []
    for round_number in range(1, rounds + 1):
        stopped_at = time.perf_counter()
        for service in services:
            compose(compose_files, "stop", service)
        for agent_url in agent_urls:
            if not request_json(f"{agent_url}/health").get("status") == "ok":
                raise CapacityVerificationError(f"healthy agent unavailable during fault round {round_number}")
        for service in services:
            compose(compose_files, "up", "-d", "--force-recreate", service)
        for agent_url in agent_urls:
            wait_http(f"{agent_url}/health/ready")
        for probe_url in probe_urls:
            result = request_json(probe_url)
            if not result.get("chunks"):
                raise CapacityVerificationError(
                    f"retrieval probe failed after fault round {round_number}: {probe_url}"
                )
        results.append({"round": round_number, "services": services, "recovery_seconds": round(time.perf_counter() - stopped_at, 2)})
    return results


def run(args: argparse.Namespace) -> dict:
    profile = [item for item in args.data_profile.split(",") if item]
    user_id, knowledge_bases = seed_data(args.agent_url, profile)
    load_urls = []
    for index, kb_id in enumerate(knowledge_bases):
        query = urllib.parse.urlencode(
            {"user_id": user_id, "kb_id": kb_id, "query": "QZ-7294", "top_k": 3}
        )
        agent_url = args.agent_url if index % 2 == 0 else args.agent_url_2
        load_urls.append(f"{agent_url}/api/v1/knowledge/search?{query}")
    load = load_test(load_urls, args.requests, args.concurrency, args.duration_seconds)
    faults = recover_faults(
        args.compose_file,
        args.fault_services,
        [args.agent_url, args.agent_url_2],
        load_urls,
        args.fault_rounds,
    )
    failures = []
    if load["completed"] != load["requested"]:
        failures.append(
            f"completed={load['completed']} does not match requested={load['requested']}"
        )
    if load["errors"] > args.max_errors:
        failures.append(f"errors={load['errors']} exceeds {args.max_errors}")
    if load["p95_latency_ms"] > args.max_p95_ms:
        failures.append(
            f"p95_latency_ms={load['p95_latency_ms']} exceeds {args.max_p95_ms}"
        )
    return {
        "status": "failed" if failures else "passed",
        "profile": profile,
        "seed_identity": user_id,
        "knowledge_bases": knowledge_bases,
        "load": load,
        "fault_recovery": faults,
        "quality_gate": {
            "max_errors": args.max_errors,
            "max_p95_ms": args.max_p95_ms,
            "failures": failures,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compose-file", action="append", required=True)
    parser.add_argument("--agent-url", default="http://127.0.0.1:8001")
    parser.add_argument("--agent-url-2", default="http://127.0.0.1:8002")
    parser.add_argument("--requests", type=int, default=600)
    parser.add_argument("--concurrency", type=int, default=24)
    parser.add_argument("--duration-seconds", type=int, default=120)
    parser.add_argument("--fault-rounds", type=int, default=3)
    parser.add_argument("--max-errors", type=int, default=0)
    parser.add_argument("--max-p95-ms", type=float, default=2000.0)
    parser.add_argument("--fault-services", default="chroma-2,redis", type=lambda value: [item for item in value.split(",") if item])
    parser.add_argument("--data-profile", default="small,medium,large")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = run(args)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
