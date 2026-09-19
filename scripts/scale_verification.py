#!/usr/bin/env python3
"""Exercise Mneme's multi-instance topology and emit acceptance evidence."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import http.cookiejar
import json
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = "docker-compose.scale-ci.yml"
TOKEN = "ci-internal-token-at-least-32-characters"


class VerificationError(RuntimeError):
    pass


def request_json(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    opener=None,
) -> object:
    data = None if payload is None else json.dumps(payload).encode()
    merged = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=data, method=method, headers=merged)
    open_request = opener.open if opener is not None else urllib.request.urlopen
    try:
        with open_request(request, timeout=90) as response:
            body = json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        raise VerificationError(
            f"{method} {url} returned HTTP {error.code}: {response_body}"
        ) from error
    if isinstance(body, dict) and body.get("code") not in {None, 200}:
        raise VerificationError(f"{method} {url} failed: {body}")
    return body.get("data", body) if isinstance(body, dict) else body


def wait_http(url: str, timeout: int = 240) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request_json(url)
            return
        except (OSError, urllib.error.URLError, json.JSONDecodeError):
            time.sleep(2)
    raise VerificationError(f"service did not become ready: {url}")


def shard(user_id: str, kb_id: str) -> int:
    digest = hashlib.sha256(f"{user_id}:{kb_id}".encode()).hexdigest()
    return int(digest[:12], 16) % 2


def compose(*args: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return result.stdout


def _restart_vector_shard(service: str = "chroma-2", agent_port: int = 8002) -> None:
    compose("up", "-d", "--force-recreate", service)
    wait_http(f"http://127.0.0.1:{agent_port}/health/ready")


def _jaeger_traces(response: object) -> list[dict]:
    if isinstance(response, dict):
        response = response.get("data", [])
    if not isinstance(response, list):
        return []
    return [trace for trace in response if isinstance(trace, dict)]


def agent(path: str, method: str = "GET", payload: dict | None = None, port: int = 8001):
    return request_json(
        f"http://127.0.0.1:{port}{path}", method, payload,
        {"X-Internal-Service-Token": TOKEN},
    )


def distributed_vectors(user_id: str) -> list[str]:
    kb_by_shard: dict[int, str] = {}
    for candidate in range(100):
        kb_id = f"scale-kb-{candidate}"
        kb_by_shard.setdefault(shard(user_id, kb_id), kb_id)
        if len(kb_by_shard) == 2:
            break
    if len(kb_by_shard) != 2:
        raise VerificationError("could not select knowledge bases for both shards")
    for kb_id in kb_by_shard.values():
        result = agent("/api/v1/knowledge/internal/ingest", "POST", {
            "user_id": user_id,
            "kb_id": kb_id,
            "file_path": "/test-fixtures/rag-fixture.txt",
            "document_id": f"doc-{kb_id}",
        })
        if result["chunks"] < 1:
            raise VerificationError(f"ingestion produced no chunks: {result}")
    first_stats = agent("/api/v1/knowledge/admin/stats")
    second_stats = agent("/api/v1/knowledge/admin/stats", port=8002)
    if any(item["chunks"] < 1 for item in first_stats["shards"]):
        raise VerificationError(f"both shards were not populated: {first_stats}")
    if first_stats["shards"] != second_stats["shards"]:
        raise VerificationError("Python instances disagree about vector shard state")
    for kb_id in kb_by_shard.values():
        query = urllib.parse.urlencode({
            "user_id": user_id, "kb_id": kb_id, "query": "QZ-7294", "top_k": 3,
        })
        result = agent(f"/api/v1/knowledge/search?{query}", port=8002)
        if not result["chunks"] or "QZ-7294" not in result["chunks"][0]["content"]:
            raise VerificationError(f"cross-instance retrieval failed for {kb_id}")

    failed_kb = kb_by_shard[1]
    healthy_kb = kb_by_shard[0]
    compose("stop", "chroma-2")
    healthy_query = urllib.parse.urlencode({
        "user_id": user_id, "kb_id": healthy_kb, "query": "QZ-7294", "top_k": 3,
    })
    if not agent(f"/api/v1/knowledge/search?{healthy_query}", port=8002)["chunks"]:
        raise VerificationError("healthy shard stopped serving during peer failure")
    _restart_vector_shard()
    recovery_query = urllib.parse.urlencode({
        "user_id": user_id, "kb_id": failed_kb, "query": "QZ-7294", "top_k": 3,
    })
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            if agent(f"/api/v1/knowledge/search?{recovery_query}", port=8002)["chunks"]:
                break
        except Exception:
            pass
        time.sleep(2)
    else:
        raise VerificationError("failed vector shard did not recover")
    return list(kb_by_shard.values())


def cache_revision(user_id: str) -> None:
    bump = "from app.memory.cache_revision import memory_cache_revision as r; print(r.bump('" + user_id + "'))"
    current = "from app.memory.cache_revision import memory_cache_revision as r; print(r.current('" + user_id + "'))"
    before = int(compose("exec", "-T", "python-agent-1", "python", "-c", bump).splitlines()[-1])
    observed = int(compose("exec", "-T", "python-agent-2", "python", "-c", current).splitlines()[-1])
    if observed < before:
        raise VerificationError(f"cache revision did not propagate: {before} -> {observed}")


def gateway_client(port: int):
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def notification_broadcast() -> tuple[str, str, object]:
    suffix = uuid.uuid4().hex[:10]
    username = f"scale_{suffix}"
    password = f"Scale_{suffix}!Aa1"
    client1 = gateway_client(8080)
    auth = request_json(
        "http://127.0.0.1:8080/api/v1/auth/register", "POST",
        {"username": username, "password": password}, opener=client1,
    )
    client2 = gateway_client(8081)
    request_json(
        "http://127.0.0.1:8081/api/v1/auth/login", "POST",
        {"username": username, "password": password}, opener=client2,
    )
    received = threading.Event()
    error: list[str] = []

    def listen() -> None:
        try:
            request = urllib.request.Request(
                "http://127.0.0.1:8081/api/v1/notifications/stream"
            )
            with client2.open(request, timeout=30) as response:
                event = ""
                for raw in response:
                    line = raw.decode().strip()
                    if line.startswith("event:"):
                        event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and event == "task" and "scale-broadcast" in line:
                        received.set()
                        return
        except Exception as exc:
            error.append(str(exc))

    thread = threading.Thread(target=listen, daemon=True)
    thread.start()
    time.sleep(2)
    message = json.dumps({
        "origin": "scale-verifier",
        "user_id": int(auth["userId"]),
        "event": {"id": 999999999, "status": "scale-broadcast", "event_type": "task"},
    }, separators=(",", ":"))
    compose("exec", "-T", "redis", "redis-cli", "PUBLISH", "mneme:notifications", message)
    if not received.wait(15):
        raise VerificationError(f"cross-instance notification was not delivered: {error}")
    return str(auth["userId"]), username, client1


def trace_chain(username: str, knowledge_bases: list[str], client) -> str:
    session = request_json(
        "http://127.0.0.1:8080/api/v1/sessions", "POST", {"title": "scale trace"}, opener=client
    )
    trace_id = uuid.uuid4().hex
    request_json(
        "http://127.0.0.1:8080/api/v1/chat", "POST",
        {
            "session_id": str(session["id"]),
            "message": "QZ-7294 是什么？",
            "knowledge_base_ids": knowledge_bases,
        },
        {"traceparent": f"00-{trace_id}-{uuid.uuid4().hex[:16]}-01"},
        client,
    )
    deadline = time.monotonic() + 45
    observed_services: set[str] = set()
    observed_operations: set[str] = set()
    while time.monotonic() < deadline:
        try:
            response = request_json(f"http://127.0.0.1:16686/api/traces/{trace_id}")
            traces = _jaeger_traces(response)
            if traces:
                spans = traces[0].get("spans", [])
                operations = {item.get("operationName") for item in spans}
                processes = traces[0].get("processes", {})
                services = {item.get("serviceName") for item in processes.values()}
                observed_services.update(item for item in services if item)
                observed_operations.update(item for item in operations if item)
                if (
                    "mneme-java-gateway-1" in services
                    and "mneme-python-agent-1" in services
                    and "mneme.retrieval" in operations
                    and "mneme.llm.invoke" in operations
                ):
                    return trace_id
        except Exception:
            pass
        time.sleep(2)
    raise VerificationError(
        f"Jaeger did not receive the complete trace {trace_id} for {username}; "
        f"services={sorted(observed_services)}, operations={sorted(observed_operations)}"
    )


def concurrent_baseline() -> dict:
    def timed(index: int) -> float:
        started = time.perf_counter()
        request_json(f"http://127.0.0.1:{8001 + index % 2}/health")
        return (time.perf_counter() - started) * 1000

    errors = 0
    latencies = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(timed, index) for index in range(60)]
        for future in futures:
            try:
                latencies.append(future.result())
            except Exception:
                errors += 1
    p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
    if errors or p95 > 2000:
        raise VerificationError(f"concurrency baseline failed: errors={errors}, p95={p95:.2f}ms")
    return {"requests": 60, "errors": errors, "p95_latency_ms": round(p95, 2)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=ROOT / "artifacts/scale-report.json")
    args = parser.parse_args()
    for url in (
        "http://127.0.0.1:8001/health", "http://127.0.0.1:8002/health",
        "http://127.0.0.1:8080/actuator/health", "http://127.0.0.1:8081/actuator/health",
        "http://127.0.0.1:16686/api/services",
    ):
        wait_http(url)
    user_id, username, client = notification_broadcast()
    knowledge_bases = distributed_vectors(user_id)
    cache_revision(user_id)
    trace_id = trace_chain(username, knowledge_bases, client)
    report = {
        "status": "passed",
        "vector_shards": 2,
        "python_instances": 2,
        "java_instances": 2,
        "knowledge_bases": knowledge_bases,
        "cache_revision": "propagated",
        "notification_broadcast": "delivered",
        "recovery": "passed",
        "trace_id": trace_id,
        "concurrency": concurrent_baseline(),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
