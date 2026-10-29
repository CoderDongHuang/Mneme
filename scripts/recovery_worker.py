"""Opt-in host recovery executor. Run outside Compose; never mount Docker into the gateway.

The gateway authenticates administrators and forwards only allowlisted requests.
Set RECOVERY_WORKER_TOKEN (32+ characters), then run this script on the Docker host.
Archive paths and commands are server-owned; HTTP clients cannot supply shell commands.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from . import backup_restore
except ImportError:  # Direct host invocation: python scripts/recovery_worker.py
    import backup_restore


def stamp():
    return datetime.now(timezone.utc).isoformat()


class RecoveryExecutor:
    def __init__(self, directory: Path, compose_files: list[str]):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.jobs = self.directory / "jobs"
        self.jobs.mkdir(exist_ok=True)
        self.compose_files = compose_files
        self.lock = threading.Lock()
        # Interrupted jobs remain visible and are never silently replayed.
        for path in self.jobs.glob("*.json"):
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("status") in {"queued", "running"}:
                value.update(status="interrupted", message="Host executor restarted; inspect the recovery report before retrying.")
                self.save(value)

    def archive(self, name: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.tar\.gz", name):
            raise ValueError("Invalid archive name")
        path = self.directory / name
        if path.is_symlink() or path.resolve().parent != self.directory or not path.is_file():
            raise ValueError("Archive is not in the configured backup directory")
        return path

    def preview(self, name: str):
        path = self.archive(name)
        manifest = backup_restore.verify_archive(path)
        backup_restore.validate_restore_schema(manifest)
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
        return {"name": name, "sha256": digest.hexdigest(), "bytes": path.stat().st_size,
                "created_at": manifest.get("created_at"), "version": manifest.get("version"),
                "security": manifest.get("security", {}), "metadata": manifest.get("metadata", {}),
                "compatible": True, "verified": True,
                "overwrites": ["MySQL", "Redis", "original files", "avatars", "vector indexes", "object storage", "agent data"],
                "preserves": ["deployment configuration and encryption keys", "backup archives"],
                "rollback": "Before applying, create and verify a checkpoint. Roll back on apply failure; keep services stopped if rollback fails."}

    def history(self):
        records = [json.loads(path.read_text(encoding="utf-8")) for path in self.jobs.glob("*.json")]
        return {"archives": [{"name": path.name, "bytes": path.stat().st_size}
                             for path in sorted(self.directory.glob("*.tar.gz"), reverse=True) if not path.is_symlink()],
                "jobs": sorted(records, key=lambda value: value["created_at"], reverse=True)[:100]}

    def save(self, job):
        target = self.jobs / f"{job['id']}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(target)

    def submit(self, body):
        action = body.get("action")
        if action not in {"backup", "restore"}:
            raise ValueError("Unsupported operation")
        required = "RESTORE SITE" if action == "restore" else "BACKUP SITE"
        if body.get("confirmation") != required:
            raise ValueError("Explicit confirmation is required")
        if not self.lock.acquire(blocking=False):
            raise ValueError("Another site operation is running")
        try:
            if action == "restore":
                checked = self.preview(str(body.get("archive", "")))
                if not hmac.compare_digest(checked["sha256"], str(body.get("sha256", ""))):
                    raise ValueError("Archive changed since preview; verify again")
            job = {"id": uuid.uuid4().hex, "action": action, "archive": body.get("archive", ""),
                   "sha256": body.get("sha256", ""), "created_at": stamp(), "status": "queued"}
            self.save(job)
            threading.Thread(target=self.execute, args=(job,), daemon=False).start()
            return job
        except BaseException:
            self.lock.release()
            raise

    def execute(self, job):
        report = self.jobs / f"{job['id']}.report"
        log = self.jobs / f"{job['id']}.log"
        args = [sys.executable, str(Path(backup_restore.__file__).resolve())]
        for compose in self.compose_files:
            args.extend(["--compose-file", compose])
        if job["action"] == "backup":
            args.extend(["backup", "--output-dir", str(self.directory)])
        else:
            args.extend(["restore", str(self.archive(job["archive"])), "--yes", "--report", str(report)])
        try:
            job.update(status="running", started_at=stamp())
            self.save(job)
            # Revalidate immediately before starting. The backup directory is operator-owned.
            if job["action"] == "restore" and self.preview(job["archive"])["sha256"] != job["sha256"]:
                raise ValueError("Archive changed before execution")
            with log.open("wb") as output:
                process = subprocess.run(args, cwd=backup_restore.PROJECT_ROOT, stdout=output,
                                         stderr=subprocess.STDOUT, check=False, shell=False)
            job.update(status="completed" if process.returncode == 0 else "failed", exit_code=process.returncode)
            job["message"] = "Check application health and run retrieval verification before reopening traffic." if process.returncode == 0 else "Operation failed; inspect the local executor log and rollback status."
            if report.exists():
                details = json.loads(report.read_text(encoding="utf-8"))
                job["report"] = {key: details[key] for key in ["status", "rpo_seconds", "rto_seconds", "restored_at"] if key in details}
                job["checkpoint"] = Path(details["recovery_archive"]).name if details.get("recovery_archive") else None
        except Exception as error:
            job.update(status="failed", message=f"Executor failed ({type(error).__name__}); inspect host report.")
        finally:
            job["finished_at"] = stamp()
            self.save(job)
            self.lock.release()


def handler(executor, token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # No credentials or request bodies in HTTP logs.

        def respond(self, code, body):
            data = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def dispatch(self):
            if not hmac.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token):
                return self.respond(403, {"message": "Forbidden"})
            try:
                if self.command == "GET" and self.path == "/site":
                    return self.respond(200, executor.history())
                if self.command == "POST" and self.path in {"/site/preview", "/site/jobs"}:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        return self.respond(413, {"message": "Invalid request size"})
                    body = json.loads(self.rfile.read(length))
                    if not isinstance(body, dict):
                        raise ValueError("Expected an object")
                    result = executor.preview(str(body.get("archive", ""))) if self.path.endswith("preview") else executor.submit(body)
                    return self.respond(200, result)
                self.respond(404, {"message": "Not found"})
            except (ValueError, backup_restore.BackupError) as error:
                self.respond(400, {"message": str(error)})
            except Exception:
                self.respond(500, {"message": "Host recovery service failed"})

        do_GET = dispatch
        do_POST = dispatch

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--directory", type=Path, default=backup_restore.PROJECT_ROOT / "backups")
    parser.add_argument("--compose-file", action="append", default=[])
    args = parser.parse_args()
    token = os.environ.get("RECOVERY_WORKER_TOKEN", "")
    if len(token) < 32:
        parser.error("RECOVERY_WORKER_TOKEN must contain at least 32 characters")
    executor = RecoveryExecutor(args.directory, args.compose_file or ["docker-compose.yml"])
    ThreadingHTTPServer((args.host, args.port), handler(executor, token)).serve_forever()


if __name__ == "__main__":
    main()
