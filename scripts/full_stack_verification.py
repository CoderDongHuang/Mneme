#!/usr/bin/env python3
"""Full-stack deletion fault injection and backup/restore drills."""

from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "test-fixtures" / "rag-fixture.txt"


class VerificationError(RuntimeError):
    pass


def compose(files: list[str], *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = ["docker", "compose"]
    for file in files:
        command.extend(("-f", file))
    command.extend(args)
    return subprocess.run(
        command, cwd=ROOT, check=check, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def wait_http(url: str, timeout: int = 180) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    raise VerificationError(f"service did not become ready: {url}")


class Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def request(self, method: str, path: str, payload: dict | None = None) -> object:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"} if data is not None else {}
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=180) as response:
                body = response.read()
        except urllib.error.HTTPError as error:
            raise VerificationError(
                f"{method} {path} failed ({error.code}): {error.read().decode(errors='replace')}"
            ) from error
        if not body:
            return None
        parsed = json.loads(body)
        if isinstance(parsed, dict) and parsed.get("code") not in {None, 200}:
            raise VerificationError(f"{method} {path} failed: {parsed}")
        return parsed.get("data", parsed) if isinstance(parsed, dict) else parsed

    def upload(self, kb_id: object) -> dict:
        boundary = f"----mneme-{uuid.uuid4().hex}"
        content = FIXTURE.read_bytes()
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"kbId\"\r\n\r\n{kb_id}\r\n".encode(),
            (
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                'filename="rag-fixture.txt"\r\nContent-Type: text/plain\r\n\r\n'
            ).encode(),
            content,
            f"\r\n--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(
            self.base_url + "/api/v1/knowledge/document/upload",
            data=b"".join(parts), method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with self.opener.open(request, timeout=180) as response:
                parsed = json.loads(response.read())
        except urllib.error.HTTPError as error:
            raise VerificationError(
                f"upload failed ({error.code}): {error.read().decode(errors='replace')}"
            ) from error
        return parsed["data"]

    def stream(self, session_id: object, kb_id: object | None = None) -> str:
        payload = {
            "session_id": str(session_id),
            "message": "星桥计划的核心识别码是什么？请引用资料。",
            "knowledge_base_ids": [] if kb_id is None else [str(kb_id)],
        }
        data = json.dumps(payload).encode()
        request = urllib.request.Request(
            self.base_url + "/api/v1/chat/stream", data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(request, timeout=180) as response:
            return response.read().decode("utf-8")


def mysql(files: list[str], sql: str) -> str:
    result = compose(
        files, "exec", "-T", "mysql", "sh", "-c",
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -N -B -uroot "$MYSQL_DATABASE" -e "$1"',
        "mneme-query", sql,
    )
    return result.stdout.strip()


def wait_document(client: Client, document_id: object, timeout: int = 150) -> dict:
    deadline = time.monotonic() + timeout
    latest = {}
    while time.monotonic() < deadline:
        latest = client.request("GET", f"/api/v1/knowledge/document/{document_id}/status")
        if latest.get("status") == "ready":
            return latest
        if latest.get("status") == "failed":
            raise VerificationError(f"document ingestion failed: {latest}")
        time.sleep(2)
    raise VerificationError(f"document did not become ready: {latest}")


def new_user(
    base_url: str, files: list[str], prefix: str, with_document: bool = False
) -> tuple[Client, dict]:
    suffix = uuid.uuid4().hex[:12]
    password = f"Mneme_{suffix}!Aa1"
    client = Client(base_url)
    auth = client.request(
        "POST", "/api/v1/auth/register",
        {"username": f"{prefix}_{suffix}", "password": password},
    )
    state = {
        "user_id": int(auth["userId"]), "username": auth["username"], "password": password
    }
    session = client.request("POST", "/api/v1/sessions", {"title": "P0 verification"})
    state["session_id"] = int(session["id"])
    if with_document:
        kb = client.request("POST", "/api/v1/knowledge/base", {"name": "P0 KB", "description": "CI"})
        document = client.upload(kb["id"])
        document = wait_document(client, document["id"])
        state.update({"kb_id": int(kb["id"]), "document_id": int(document["id"])})
        state["file_path"] = mysql(
            files, f"SELECT file_path FROM knowledge_document WHERE id={state['document_id']}"
        )
        stream = client.stream(state["session_id"], state["kb_id"])
        if "QZ-7294" not in stream or '"sources": []' in stream:
            raise VerificationError("full-stack RAG stream did not contain answer and citations")
        client.request("POST", "/api/v1/memory/write", {
            "category": "preference", "content": "P0 删除验收记忆", "topic": "verification"
        })
    else:
        stream = client.stream(state["session_id"])
        if "QZ-7294" not in stream:
            raise VerificationError("deterministic stream did not complete")
    return client, state


def enqueue_db(files: list[str], user_id: int) -> str:
    operation_id = f"ci-{uuid.uuid4().hex}"
    mysql(files, f"""
        UPDATE user SET status='deleting' WHERE id={user_id};
        INSERT INTO account_deletion_task(
          operation_id,user_id,status,current_step,attempt_count,next_attempt_at
        ) VALUES('{operation_id}',{user_id},'pending','queued',0,NOW());
    """)
    return operation_id


def task_status(files: list[str], operation_id: str) -> tuple[str, str]:
    raw = mysql(
        files,
        "SELECT status,current_step FROM account_deletion_task "
        f"WHERE operation_id='{operation_id}'",
    )
    parts = raw.split("\t")
    return (parts[0], parts[1] if len(parts) > 1 else "")


def wait_task(files: list[str], operation_id: str, expected: set[str], timeout: int = 180) -> tuple[str, str]:
    deadline = time.monotonic() + timeout
    latest = ("missing", "")
    while time.monotonic() < deadline:
        latest = task_status(files, operation_id)
        if latest[0] in expected:
            return latest
        if latest[0] == "failed":
            raise VerificationError(f"deletion task exhausted retries: {operation_id} {latest}")
        time.sleep(1)
    raise VerificationError(f"deletion task timeout: {operation_id} {latest}")


def python_state(files: list[str], user_id: int) -> dict:
    code = f"""
import json, sqlite3
from pathlib import Path
from app.knowledge.vector_store import vector_store
from app.memory.memory_store import memory_store
def count(path, table):
    p=Path(path)
    if not p.exists(): return 0
    with sqlite3.connect(p) as db:
        return db.execute(f'SELECT COUNT(*) FROM {{table}} WHERE user_id=?', ('{user_id}',)).fetchone()[0]
print('MNEME_STATE='+json.dumps({{
 'collections': len(vector_store.list_user_collections('{user_id}')),
 'memories': memory_store.count_user_memories('{user_id}'),
 'versions': count('/app/data/memory_versions.sqlite3','memory_version'),
 'traces': count('/app/data/agent_traces.sqlite3','agent_trace'),
 'session_file': Path('/app/data/sessions/{user_id}.json').exists(),
}}))
"""
    output = compose(files, "exec", "-T", "python-agent", "python", "-c", code).stdout
    marker = next((line for line in output.splitlines() if line.startswith("MNEME_STATE=")), None)
    if marker is None:
        raise VerificationError(f"could not inspect Python state: {output}")
    return json.loads(marker.split("=", 1)[1])


def assert_deleted(files: list[str], state: dict, operation_id: str) -> None:
    user_id = state["user_id"]
    status, _ = task_status(files, operation_id)
    if status != "completed":
        raise VerificationError(f"deletion task is not complete: {operation_id} {status}")
    checks = {
        "user": f"SELECT COUNT(*) FROM user WHERE id={user_id}",
        "knowledge_base": f"SELECT COUNT(*) FROM knowledge_base WHERE user_id={user_id}",
        "chat_session": f"SELECT COUNT(*) FROM chat_session WHERE user_id={user_id}",
        "pending_memory": f"SELECT COUNT(*) FROM pending_memory WHERE user_id={user_id}",
        "processing_task": f"SELECT COUNT(*) FROM processing_task WHERE user_id={user_id}",
    }
    leftovers = {}
    for name, sql in checks.items():
        count = mysql(files, sql)
        if count != "0":
            leftovers[name] = count
    if leftovers:
        raise VerificationError(f"MySQL user data remains: {leftovers}")
    redis_value = compose(
        files, "exec", "-T", "redis", "redis-cli", "EXISTS",
        f"mneme:session:{state['session_id']}",
    ).stdout.strip()
    if redis_value != "0":
        raise VerificationError(f"Redis session remains for {state['session_id']}")
    py_state = python_state(files, user_id)
    if any(py_state.values()):
        raise VerificationError(f"Python/Chroma state remains: {py_state}")
    if state.get("file_path", "").startswith("s3://"):
        digest = hashlib.sha256(state["file_path"].encode()).hexdigest()[:24]
        cache = ROOT / "data" / "files" / ".object-cache"
        if cache.is_dir() and any(path.name.startswith(digest + "-") for path in cache.iterdir()):
            raise VerificationError(f"materialized object cache remains for user {user_id}")
    if (ROOT / "data" / "files" / str(user_id)).exists():
        raise VerificationError(f"local user files remain for user {user_id}")
    minio_root = ROOT / "data" / "minio"
    needle = f"users/{user_id}/"
    if minio_root.exists() and any(needle in path.as_posix() + "/" for path in minio_root.rglob("*")):
        raise VerificationError(f"MinIO objects remain for user {user_id}")


def deletion_drill(args: argparse.Namespace) -> None:
    client, chroma_user = new_user(
        args.base_url, args.compose_file, "p0_chroma", with_document=True
    )
    compose(args.compose_file, "stop", "chroma")
    operation = client.request("DELETE", "/api/v1/profile/account")["operation_id"]
    wait_task(args.compose_file, operation, {"retry"}, timeout=150)
    compose(args.compose_file, "start", "chroma")
    wait_task(args.compose_file, operation, {"completed"})
    assert_deleted(args.compose_file, chroma_user, operation)

    minio_client, minio_user = new_user(
        args.base_url, args.compose_file, "p0_minio", with_document=True
    )
    compose(args.compose_file, "stop", "minio")
    operation = minio_client.request("DELETE", "/api/v1/profile/account")["operation_id"]
    retry = wait_task(args.compose_file, operation, {"retry"}, timeout=150)
    if retry[1] != "session_cleanup":
        raise VerificationError(f"MinIO failure occurred at unexpected step: {retry}")
    compose(args.compose_file, "start", "minio")
    wait_task(args.compose_file, operation, {"completed"})
    assert_deleted(args.compose_file, minio_user, operation)

    _, redis_user = new_user(args.base_url, args.compose_file, "p0_redis")
    compose(args.compose_file, "stop", "redis")
    operation = enqueue_db(args.compose_file, redis_user["user_id"])
    retry = wait_task(args.compose_file, operation, {"retry"}, timeout=150)
    if retry[1] != "memory_cleanup":
        raise VerificationError(f"Redis failure occurred at unexpected step: {retry}")
    compose(args.compose_file, "start", "redis")
    wait_task(args.compose_file, operation, {"completed"})
    assert_deleted(args.compose_file, redis_user, operation)

    _, restart_user = new_user(args.base_url, args.compose_file, "p0_restart")
    compose(args.compose_file, "stop", "java-gateway")
    operation = enqueue_db(args.compose_file, restart_user["user_id"])
    compose(args.compose_file, "start", "java-gateway")
    wait_http(args.base_url + "/actuator/health")
    wait_task(args.compose_file, operation, {"completed"})
    assert_deleted(args.compose_file, restart_user, operation)
    print(json.dumps({
        "status": "completed",
        "scenarios": ["chroma", "minio", "redis", "java-restart"],
    }))


def backup_restore_drill(args: argparse.Namespace) -> None:
    client, marker = new_user(
        args.base_url, args.compose_file, "p0_restore", with_document=True
    )
    backup_dir = ROOT / "backups" / "ci"
    before = set(backup_dir.glob("*.tar.gz")) if backup_dir.exists() else set()
    command = [sys.executable, str(ROOT / "scripts" / "backup_restore.py")]
    for file in args.compose_file:
        command.extend(("--compose-file", file))
    subprocess.run([*command, "backup", "--output-dir", str(backup_dir)], cwd=ROOT, check=True)
    archives = set(backup_dir.glob("*.tar.gz")) - before
    if len(archives) != 1:
        raise VerificationError(f"expected one backup archive, found {sorted(archives)}")
    archive = archives.pop()
    wait_http(args.base_url + "/actuator/health")
    operation = client.request("DELETE", "/api/v1/profile/account")["operation_id"]
    wait_task(args.compose_file, operation, {"completed"})
    assert_deleted(args.compose_file, marker, operation)
    report = backup_dir / "restore-report.json"
    subprocess.run(
        [*command, "restore", str(archive), "--yes", "--report", str(report)],
        cwd=ROOT, check=True,
    )
    wait_http(args.base_url + "/actuator/health")
    restored = Client(args.base_url)
    restored.request("POST", "/api/v1/auth/login", {
        "username": marker["username"],
        "password": marker["password"],
    })
    if mysql(args.compose_file, f"SELECT COUNT(*) FROM user WHERE id={marker['user_id']}") != "1":
        raise VerificationError("restored MySQL marker user is missing")
    bases = restored.request("GET", "/api/v1/knowledge/base/list")
    if marker["kb_id"] not in {int(item["id"]) for item in bases}:
        raise VerificationError("restored knowledge base is not available through the API")
    documents = restored.request(
        "GET", f"/api/v1/knowledge/base/{marker['kb_id']}/documents"
    )
    if marker["document_id"] not in {int(item["id"]) for item in documents}:
        raise VerificationError("restored document is not available through the API")
    if not python_state(args.compose_file, marker["user_id"])["collections"]:
        raise VerificationError("restored Chroma collection is missing")
    session = restored.request("POST", "/api/v1/sessions", {"title": "restored RAG"})
    stream = restored.stream(session["id"], marker["kb_id"])
    if "QZ-7294" not in stream or '"sources": []' in stream:
        raise VerificationError("restored RAG answer or citations are unavailable")
    if not report.is_file() or json.loads(report.read_text())["status"] != "completed":
        raise VerificationError("restore report is missing or incomplete")
    print(json.dumps({"status": "completed", "archive": str(archive), "report": str(report)}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("deletion", "backup-restore"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--compose-file", action="append", default=[])
    args = parser.parse_args()
    if not args.compose_file:
        args.compose_file = ["docker-compose.yml"]
    return args


if __name__ == "__main__":
    ARGS = parse_args()
    try:
        if ARGS.command == "deletion":
            deletion_drill(ARGS)
        else:
            backup_restore_drill(ARGS)
    except (VerificationError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
