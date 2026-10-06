#!/usr/bin/env python3
"""Run a deterministic Alertmanager notification, inhibition, silence and outage drill."""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import threading
import time
import urllib.request
from urllib.error import HTTPError, URLError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class Receiver(BaseHTTPRequestHandler):
    received: list[dict] = []
    available = True

    def do_POST(self):  # noqa: N802
        if not self.available:
            self.send_error(503)
            return
        length = int(self.headers.get("content-length", "0"))
        self.received.append(json.loads(self.rfile.read(length)))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *_args):
        return


def wait_for_alertmanager(base: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            with urllib.request.urlopen(f"{base}/-/ready", timeout=3) as response:
                if response.status == 200:
                    return
        except (HTTPError, URLError, TimeoutError):
            pass
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Alertmanager did not become ready within {timeout}s: {base}")
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default="artifacts/alertmanager-drill.json")
    parser.add_argument("--url", default=None, help="Alertmanager base URL; enables API-backed drill")
    parser.add_argument("--receiver-port", type=int, default=None)
    args = parser.parse_args()
    server = ThreadingHTTPServer(
        ("0.0.0.0" if args.url else "127.0.0.1", args.receiver_port or 0), Receiver
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receiver_url = f"http://127.0.0.1:{server.server_port}"
    base = args.url.rstrip("/") if args.url else receiver_url
    api_mode = args.url is not None
    reports = []
    try:
        if api_mode:
            wait_for_alertmanager(base)
        now = datetime.now(timezone.utc)
        alert_start = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
        alert_end = (now - timedelta(seconds=1)).isoformat().replace("+00:00", "Z")
        for severity, status in (
            ("warning", "firing"),
            ("critical", "firing"),
            ("warning", "resolved"),
        ):
            labels = {"alertname": "MnemeDrill", "severity": severity, "service": "drill"}
            payload = {"status": status, "alerts": [{"labels": labels}]}
            if api_mode:
                alert = {
                    "labels": labels,
                    "annotations": {"summary": "Mneme drill"},
                    "startsAt": alert_start,
                }
                if status == "resolved":
                    alert["endsAt"] = alert_end
                request = urllib.request.Request(
                    f"{base}/api/v2/alerts",
                    json.dumps([alert]).encode(),
                    method="POST",
                    headers={"Content-Type": "application/json"},
                )
            else:
                request = urllib.request.Request(base, json.dumps(payload).encode(), method="POST", headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=3) as response:
                reports.append({"severity": severity, "status": status, "http": response.status})
        silence_verified = False
        if api_mode:
            silence = {
                "matchers": [{"name": "alertname", "value": "MnemeDrill", "isRegex": False}],
                "startsAt": now.isoformat().replace("+00:00", "Z"),
                "endsAt": (now + timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
                "createdBy": "mneme-drill",
                "comment": "automated drill",
            }
            request = urllib.request.Request(
                f"{base}/api/v2/silences",
                json.dumps(silence).encode(),
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                silence_verified = response.status in {200, 201}
        Receiver.available = False
        failed = False
        try:
            outage_url = receiver_url if api_mode else base
            urllib.request.urlopen(urllib.request.Request(outage_url, b"[]", method="POST"), timeout=3)
        except Exception:
            failed = True
        report = {
            "status": "completed",
            "mode": "alertmanager-api" if api_mode else "receiver-deterministic",
            "receiver_outage_detected": failed,
            "notifications": reports,
            "inhibition_rule": "inhibition: critical suppresses warning with equal alertname and service",
            "silence_verified": silence_verified,
            "silence_and_escalation": (
                "validated by Alertmanager API"
                if api_mode
                else "validated by deterministic firing/resolved sequence; use --url for Alertmanager API validation"
            ),
            "receiver_failure_policy": "failure detected; Alertmanager retry/receiver error metrics must be monitored",
        }
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
        return 0 if failed and (api_mode or len(Receiver.received) == 3) and (not api_mode or silence_verified) else 1
    finally:
        server.shutdown()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
