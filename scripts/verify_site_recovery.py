#!/usr/bin/env python3
"""Destructive acceptance of the host executor; use ONLY a disposable Compose stack."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

from full_stack_verification import (
    Client, ROOT, VerificationError, assert_deleted, mysql, new_user,
    python_state, wait_http, wait_task,
)


def run(args):
    token = os.environ.get("RECOVERY_WORKER_TOKEN", "")
    admin = os.environ.get("ADMIN_API_TOKEN", "")
    if len(token) < 32 or len(admin) < 32:
        raise VerificationError("Set independent RECOVERY_WORKER_TOKEN and ADMIN_API_TOKEN (32+ characters)")
    directory = ROOT / "backups" / "worker-acceptance"
    directory.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, str(ROOT / "scripts/recovery_worker.py"),
               "--host", "0.0.0.0", "--port", str(args.port), "--directory", str(directory)]
    for compose in args.compose_file:
        command.extend(["--compose-file", compose])
    log = (directory / "worker.log").open("wb")
    process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)

    def request(client, path, body=None, credential=None):
        headers = {"Content-Type": "application/json"}
        if credential:
            headers["X-Admin-Token"] = credential
        req = urllib.request.Request(args.base_url + "/api/v1/admin/recovery/site" + path,
                                     headers=headers, data=None if body is None else json.dumps(body).encode())
        try:
            with client.opener.open(req, timeout=180) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            if error.code != 403:
                print(f"Site API {path}: {error.code}: {error.read().decode()}", flush=True)
            raise
        if result.get("code", 200) != 200:
            raise VerificationError(str(result))
        return result.get("data", result)

    def host(path="", body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{args.port}/site" + path,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                                     data=None if body is None else json.dumps(body).encode())
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)

    def completed(job):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            record = next(item for item in host()["jobs"] if item["id"] == job["id"])
            if record["status"] == "completed":
                return record
            if record["status"] in {"failed", "interrupted"}:
                raise VerificationError(f"Host job {record['id']} failed; inspect {directory / 'jobs'}")
            time.sleep(2)
        raise VerificationError("Host recovery job timed out")

    try:
        for _ in range(30):
            try:
                host()
                break
            except OSError:
                if process.poll() is not None:
                    raise VerificationError("Host executor exited; inspect worker.log") from None
                time.sleep(1)
        client, marker = new_user(args.base_url, args.compose_file, "worker_restore", with_document=True)
        try:
            request(client, "", credential=admin)
            raise VerificationError("Ordinary account accessed site recovery")
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise
        mysql(args.compose_file, f"UPDATE user SET role='admin' WHERE id={marker['user_id']}")
        try:
            request(client, "")
            raise VerificationError("Admin accessed site recovery without second credential")
        except urllib.error.HTTPError as error:
            if error.code != 403:
                raise
        before = {item["name"] for item in request(client, "", credential=admin)["archives"]}
        backup = completed(request(client, "/jobs", {"action": "backup", "confirmation": "BACKUP SITE"}, admin))
        wait_http(args.base_url + "/actuator/health")
        archives = {item["name"] for item in host()["archives"]} - before
        if len(archives) != 1:
            raise VerificationError("Expected exactly one new verified archive")
        archive = archives.pop()
        preview = request(client, "/preview", {"archive": archive}, admin)
        if not preview["verified"] or not preview["compatible"]:
            raise VerificationError("Archive preview failed")
        try:
            request(client, "/jobs", {"action": "restore", "confirmation": "RESTORE SITE", "archive": archive, "sha256": "stale"}, admin)
            raise VerificationError("Changed archive digest accepted")
        except urllib.error.HTTPError as error:
            if error.code != 400:
                raise
        # Delete real source account and verify all storage layers before restoring it.
        operation = client.request("DELETE", "/api/v1/profile/account")["operation_id"]
        wait_task(args.compose_file, operation, {"completed"})
        assert_deleted(args.compose_file, marker, operation)
        operator, operator_marker = new_user(args.base_url, args.compose_file, "worker_operator")
        mysql(args.compose_file, f"UPDATE user SET role='admin' WHERE id={operator_marker['user_id']}")
        restore = completed(request(operator, "/jobs", {"action": "restore", "confirmation": "RESTORE SITE", "archive": archive, "sha256": preview["sha256"]}, admin))
        wait_http(args.base_url + "/actuator/health")
        restored = Client(args.base_url)
        restored.request("POST", "/api/v1/auth/login", {"username": marker["username"], "password": marker["password"]})
        bases = restored.request("GET", "/api/v1/knowledge/base/list")
        if marker["kb_id"] not in {int(item["id"]) for item in bases}:
            raise VerificationError("Restored knowledge base missing")
        documents = restored.request("GET", f"/api/v1/knowledge/base/{marker['kb_id']}/documents")
        if marker["document_id"] not in {int(item["id"]) for item in documents} or not python_state(args.compose_file, marker["user_id"])["collections"]:
            raise VerificationError("Restored document or vector index missing")
        session = restored.request("POST", "/api/v1/sessions", {"title": "Worker restored RAG"})
        stream = restored.stream(session["id"], marker["kb_id"])
        if "QZ-7294" not in stream or '"sources": []' in stream:
            raise VerificationError("Restored RAG or citations failed")
        if restore.get("report", {}).get("status") != "completed" or not restore.get("checkpoint"):
            raise VerificationError("Restore report or rollback checkpoint missing")
        report = {"status": "completed", "archive": archive, "backup_job": backup["id"],
                  "restore_job": restore["id"], "restore": restore["report"],
                  "checks": ["ordinary-user-403", "admin-credential-403", "digest-rejection", "real-backup", "cross-storage-deletion", "real-restore", "login", "document", "vectors", "answer-and-citations", "rollback-checkpoint"]}
        (directory / "acceptance.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report))
    finally:
        process.terminate()
        process.wait(timeout=20)
        log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-disposable-stack", action="store_true", required=True)
    parser.add_argument("--compose-file", action="append", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--port", type=int, default=8091)
    run(parser.parse_args())
