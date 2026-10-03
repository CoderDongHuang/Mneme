#!/usr/bin/env python3
"""Run configurable long-duration load and multi-fault recovery checks."""

from __future__ import annotations

import argparse
import concurrent.futures
from contextlib import contextmanager
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOKEN = "ci-internal-token-at-least-32-characters"
RUN_DEADLINE: float | None = None


class CapacityVerificationError(RuntimeError):
    pass


def remaining_timeout(limit: float) -> float:
    remaining = limit if RUN_DEADLINE is None else min(limit, RUN_DEADLINE - time.monotonic())
    if remaining <= 0:
        raise CapacityVerificationError("capacity runtime budget exhausted")
    return remaining


@contextmanager
def runtime_budget(seconds: float):
    global RUN_DEADLINE
    previous = RUN_DEADLINE
    RUN_DEADLINE = time.monotonic() + seconds
    try:
        yield
    finally:
        RUN_DEADLINE = previous


def pause(seconds: float) -> None:
    if seconds > remaining_timeout(max(seconds, 1)):
        raise CapacityVerificationError("capacity runtime budget exhausted before wait")
    time.sleep(seconds)


def wait_until(deadline: float) -> None:
    # Recheck the monotonic deadline after early timer wake-ups on Windows.
    while (remaining := deadline - time.monotonic()) > 0:
        pause(remaining)


def request_json(url: str, method: str = "GET", payload: dict | None = None) -> object:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Internal-Service-Token": TOKEN},
    )
    try:
        with urllib.request.urlopen(request, timeout=remaining_timeout(30)) as response:
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


def compose(compose_files: list[str], *args: str, timeout: float | None = None) -> str:
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
        timeout=remaining_timeout(120) if timeout is None else timeout,
    )
    return result.stdout


def wait_http(url: str, timeout: float = 240) -> None:
    deadline = time.monotonic() + remaining_timeout(timeout)
    while time.monotonic() < deadline:
        try:
            result = request_json(url)
            if url.endswith("/health/ready") and (
                not isinstance(result, dict) or result.get("status") != "ready"
                or result.get("components", {}).get("redis") != "up"
            ):
                raise CapacityVerificationError(f"dependencies are not ready: {url}")
            return
        except CapacityVerificationError:
            pause(min(2, max(0, deadline - time.monotonic())))
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
    if not urls or requests < len(urls) or not math.isfinite(duration_seconds) or duration_seconds < 0:
        raise ValueError("load requires URLs, enough requests to cover them, and a finite nonnegative duration")
    started = time.monotonic()
    latencies: list[float] = []
    errors = 0
    error_samples: list[str] = []

    def one(index: int) -> float:
        request_started = time.perf_counter()
        url = urls[index % len(urls)]
        result = request_json(url)
        if "/knowledge/search?" in url and (not isinstance(result, dict) or not result.get("chunks")):
            raise CapacityVerificationError(f"retrieval returned no chunks: {url}")
        return (time.perf_counter() - request_started) * 1000

    def collect(futures):
        nonlocal errors
        for future in futures:
            try:
                latencies.append(future.result())
            except Exception as error:
                errors += 1
                if len(error_samples) < 10:
                    error_samples.append(str(error))

    interval = duration_seconds / requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = set()
        for index in range(requests):
            wait_until(started + index * interval)
            if len(pending) >= concurrency:
                done, pending = concurrent.futures.wait(
                    pending, timeout=remaining_timeout(30),
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                if not done:
                    raise CapacityVerificationError("load workers did not complete within the request timeout")
                collect(done)
            pending.add(pool.submit(one, index))
        collect(pending)
        wait_until(started + duration_seconds)
    if not latencies:
        raise CapacityVerificationError("load test produced no successful requests")
    return {
        "requested": requests,
        "completed": len(latencies),
        "errors": errors,
        "error_samples": error_samples,
        "concurrency": concurrency,
        "target_duration_seconds": duration_seconds,
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
    fault_matrix: list[list[str]] | None = None,
    hold_seconds: float = 2.0,
    recovery_timeout: float = 240.0,
) -> list[dict]:
    matrix = fault_matrix if fault_matrix is not None else [services]
    if not matrix or any(not group or any(not service for service in group) or len(set(group)) != len(group) for group in matrix):
        raise ValueError("fault matrix must contain nonempty groups of distinct services")
    if rounds < len(matrix) or not agent_urls or not probe_urls:
        raise ValueError("fault rounds must cover the full matrix with health and retrieval probes")
    if not math.isfinite(hold_seconds) or hold_seconds < 0:
        raise ValueError("fault hold must be finite and nonnegative")
    results = []
    for round_number in range(1, rounds + 1):
        selected_services = matrix[(round_number - 1) % len(matrix)]
        attempted = []
        fault_error = None
        cleanup_errors = []
        try:
            for service in selected_services:
                attempted.append(service)
                compose(compose_files, "stop", service)
            pause(hold_seconds)
            for agent_url in agent_urls:
                result = request_json(f"{agent_url}/health")
                if not isinstance(result, dict) or result.get("status") != "ok":
                    raise CapacityVerificationError(f"healthy agent unavailable during fault round {round_number}")
        except Exception as error:
            fault_error = error
        finally:
            recovery_started = time.perf_counter()
            recovery_deadline = time.monotonic() + recovery_timeout
            for service in attempted:
                try:
                    # Reserve bounded cleanup time even when the measurement budget has expired.
                    compose(compose_files, "up", "-d", "--no-deps", "--force-recreate", service, timeout=30)
                except Exception as error:
                    cleanup_errors.append(f"{service}: {error}")
        if cleanup_errors:
            raise CapacityVerificationError(
                f"fault round {round_number}: {fault_error or 'restart failed'}; cleanup errors: {cleanup_errors}"
            ) from fault_error
        if fault_error:
            raise fault_error
        for agent_url in agent_urls:
            wait_http(f"{agent_url}/health/ready", timeout=max(0, recovery_deadline - time.monotonic()))
        for probe_url in probe_urls:
            result = request_json(probe_url)
            if not isinstance(result, dict) or not result.get("chunks"):
                raise CapacityVerificationError(
                    f"retrieval probe failed after fault round {round_number}: {probe_url}"
                )
        results.append({"round": round_number, "services": selected_services, "status": "passed", "recovery_seconds": round(time.perf_counter() - recovery_started, 2)})
    return results


def run(args: argparse.Namespace) -> dict:
    profile = [item for item in args.data_profile.split(",") if item]
    matrix = getattr(args, "fault_matrix", None)
    matrix = matrix if matrix is not None else [args.fault_services]
    max_recovery = getattr(args, "max_recovery_seconds", 240.0)
    hold_seconds = getattr(args, "fault_hold_seconds", 2.0)
    runtime_timeout = getattr(args, "runtime_timeout_seconds", 1200.0)
    for name, value in {"max_errors": args.max_errors, "max_p95_ms": args.max_p95_ms,
                        "max_recovery_seconds": max_recovery, "fault_hold_seconds": hold_seconds}.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")
    if (isinstance(runtime_timeout, bool) or not isinstance(runtime_timeout, (int, float))
            or not math.isfinite(runtime_timeout) or runtime_timeout <= 0):
        raise ValueError("runtime timeout must be finite and positive")
    if not profile or any(size not in {"small", "medium", "large"} for size in profile):
        raise ValueError("data profile must contain supported sizes")
    if (args.requests < len(profile) * 2 or args.concurrency < 1
            or not math.isfinite(args.duration_seconds) or args.duration_seconds < 0):
        raise ValueError("invalid load configuration or insufficient requests to cover both agents")
    if not matrix or any(not group or any(not service for service in group) or len(set(group)) != len(group) for group in matrix) or args.fault_rounds < len(matrix):
        raise ValueError("fault rounds must cover every nonempty matrix group")
    configuration = {
        "profile": profile, "requests": args.requests, "concurrency": args.concurrency,
        "duration_seconds": args.duration_seconds, "fault_rounds": args.fault_rounds,
        "fault_matrix": matrix, "fault_hold_seconds": hold_seconds,
        "max_errors": args.max_errors, "max_p95_ms": args.max_p95_ms,
        "max_recovery_seconds": max_recovery,
        "runtime_timeout_seconds": runtime_timeout,
        "inputs": {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                   for path in [*args.compose_file, "scripts/capacity_verification.py",
                                "python-agent/app/api/knowledge.py", "python-agent/main.py",
                                "python-agent/app/core/config.py",
                                *(f"test-fixtures/{name}" for name in
                                  ("rag-fixture.txt", "rag-fixture.md", "rag-fixture.docx"))]},
    }
    report = {
        "profile": profile, "fault_matrix": matrix,
        "provenance": {
            "schema_version": 1, "kind": "capacity", "report_id": uuid.uuid4().hex,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "repository": os.getenv("GITHUB_REPOSITORY"), "branch": os.getenv("GITHUB_REF_NAME"),
            "commit": os.getenv("GITHUB_SHA"), "run_id": os.getenv("GITHUB_RUN_ID"),
            "run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"), "configuration": configuration,
        },
    }
    try:
        with runtime_budget(runtime_timeout):
            report.update(_measure(args, profile, matrix, hold_seconds, max_recovery))
    except (CapacityVerificationError, subprocess.SubprocessError, OSError) as error:
        report.update(status="failed", quality_gate={"status": "failed", "failures": [str(error)]})
    return report


def _measure(args: argparse.Namespace, profile: list[str], matrix: list[list[str]],
             hold_seconds: float, max_recovery: float) -> dict:
    for agent_url in (args.agent_url, args.agent_url_2):
        wait_http(f"{agent_url}/health/ready")
    user_id, knowledge_bases = seed_data(args.agent_url, profile)
    load_urls = []
    for kb_id in knowledge_bases:
        query = urllib.parse.urlencode(
            {"user_id": user_id, "kb_id": kb_id, "query": "QZ-7294", "top_k": 3}
        )
        for agent_url in (args.agent_url, args.agent_url_2):
            load_urls.append(f"{agent_url}/api/v1/knowledge/search?{query}")
    load = load_test(load_urls, args.requests, args.concurrency, args.duration_seconds)
    faults = recover_faults(
        args.compose_file,
        args.fault_services,
        [args.agent_url, args.agent_url_2],
        load_urls,
        args.fault_rounds,
        matrix,
        hold_seconds,
        max_recovery,
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
    if load.get("requested") != args.requests:
        failures.append("load did not execute the configured request count")
    if load.get("duration_seconds", 0) + 0.01 < args.duration_seconds:
        failures.append("load did not cover the configured duration")
    if len(faults) != args.fault_rounds:
        failures.append("fault recovery did not complete every requested round")
    for index, fault in enumerate(faults):
        recovery = fault.get("recovery_seconds")
        if (fault.get("round") != index + 1 or fault.get("services") != matrix[index % len(matrix)]
                or fault.get("status") != "passed"):
            failures.append(f"fault round {index + 1} did not complete its matrix group")
        if (isinstance(recovery, bool) or not isinstance(recovery, (int, float))
                or not math.isfinite(recovery) or recovery < 0 or recovery > max_recovery):
            failures.append(f"fault round {index + 1} recovery exceeds {max_recovery} or is invalid")
    for key in ("p95_latency_ms", "completed", "requested", "errors"):
        value = load.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            failures.append(f"load metric {key} is invalid")
    return {
        "status": "failed" if failures else "passed",
        "profile": profile,
        "seed_identity": user_id,
        "knowledge_bases": knowledge_bases,
        "load": load,
        "fault_recovery": faults,
        "fault_matrix": matrix,
        "quality_gate": {
            "status": "failed" if failures else "passed",
            "max_errors": args.max_errors,
            "max_p95_ms": args.max_p95_ms,
            "max_recovery_seconds": max_recovery,
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
    parser.add_argument("--fault-rounds", type=int, default=5)
    parser.add_argument("--max-errors", type=int, default=0)
    parser.add_argument("--max-p95-ms", type=float, default=2000.0)
    parser.add_argument("--max-recovery-seconds", type=float, default=240.0)
    parser.add_argument("--fault-hold-seconds", type=float, default=2.0)
    parser.add_argument("--runtime-timeout-seconds", type=float, default=1200.0)
    parser.add_argument("--fault-services", default="chroma-2,redis", type=lambda value: [item.strip() for item in value.split(",")])
    parser.add_argument(
        "--fault-matrix",
        default="redis,chroma-1,chroma-2,chroma-1+redis,chroma-2+redis",
        type=lambda value: [[item.strip() for item in group.split("+")] for group in value.split(",")],
    )
    parser.add_argument("--data-profile", default="small,medium,large")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args)
    except (ValueError, CapacityVerificationError, subprocess.SubprocessError, OSError) as error:
        report = {"status": "failed", "quality_gate": {"status": "failed", "failures": [str(error)]}}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
