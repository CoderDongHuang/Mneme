import json
import sqlite3
import time
import hashlib
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.core.config import settings
from app.storage.mysql import connection as mysql_connection


class AgentTraceStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or settings.agent_trace_store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    @property
    def shared(self) -> bool:
        return settings.auxiliary_store_backend == "mysql"

    def _init_db(self) -> None:
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS agent_trace (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        user_id VARCHAR(128) NOT NULL, session_id VARCHAR(128) NOT NULL,
                        node VARCHAR(255) NOT NULL, status VARCHAR(32) NOT NULL,
                        duration_ms DOUBLE NOT NULL DEFAULT 0, payload_json JSON NOT NULL,
                        error VARCHAR(1000) NOT NULL DEFAULT '', created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        INDEX idx_agent_trace_session (user_id, session_id, id)
                    )
                """)
                cursor.close()
            self.prune(settings.agent_trace_retention_days)
            return
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_trace (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    node TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration_ms REAL NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_trace_session
                ON agent_trace(user_id, session_id, id)
                """
            )
        self.prune(settings.agent_trace_retention_days)

    def record(
        self,
        user_id: str,
        session_id: str,
        node: str,
        status: str,
        payload: dict[str, Any] | None = None,
        duration_ms: float = 0,
        error: str = "",
    ) -> None:
        safe_payload = self._redact(payload or {})
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute(
                    "INSERT INTO agent_trace(user_id,session_id,node,status,duration_ms,payload_json,error) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (user_id, session_id, node, status, round(float(duration_ms), 3), json.dumps(safe_payload, ensure_ascii=False, sort_keys=True), error[:1000]),
                )
                cursor.close()
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agent_trace(user_id,session_id,node,status,duration_ms,payload_json,error)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    user_id,
                    session_id,
                    node,
                    status,
                    round(float(duration_ms), 3),
                    json.dumps(safe_payload, ensure_ascii=False, sort_keys=True),
                    error[:1000],
                ),
            )

    def _redact(self, value: Any, field: str = "") -> Any:
        sensitive = {
            item.strip().lower()
            for item in settings.agent_trace_redact_fields.split(",")
            if item.strip()
        }
        normalized = field.lower()
        if normalized and any(token in normalized for token in sensitive):
            raw = str(value).encode("utf-8", errors="replace")
            return {"redacted": True, "sha256": hashlib.sha256(raw).hexdigest()[:16], "length": len(raw)}
        if isinstance(value, dict):
            return {str(key): self._redact(item, str(key)) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._redact(item, field) for item in value]
        return value

    @contextmanager
    def span(
        self,
        user_id: str,
        session_id: str,
        node: str,
        payload: dict[str, Any] | None = None,
    ) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        except Exception as error:
            self.record(
                user_id,
                session_id,
                node,
                "error",
                payload,
                (time.perf_counter() - started) * 1000,
                str(error),
            )
            raise
        else:
            self.record(
                user_id,
                session_id,
                node,
                "ok",
                payload,
                (time.perf_counter() - started) * 1000,
            )

    def list_session(
        self, user_id: str, session_id: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                cursor.execute("SELECT id,user_id,session_id,node,status,duration_ms,payload_json,error,created_at FROM agent_trace WHERE user_id=%s AND session_id=%s ORDER BY id DESC LIMIT %s", (user_id, session_id, limit))
                rows = cursor.fetchall()
                cursor.close()
            return [self._shared_row(row) for row in rows]
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id,user_id,session_id,node,status,duration_ms,payload_json,error,created_at
                FROM agent_trace
                WHERE user_id=? AND session_id=?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, session_id, limit),
            ).fetchall()
        traces = []
        for row in rows:
            traces.append(
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "session_id": row["session_id"],
                    "node": row["node"],
                    "status": row["status"],
                    "duration_ms": row["duration_ms"],
                    "payload": json.loads(row["payload_json"]),
                    "error": row["error"],
                    "created_at": row["created_at"],
                }
            )
        return traces

    @staticmethod
    def _shared_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = row["payload_json"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return {
            key: (str(value) if key == "created_at" else value)
            for key, value in row.items()
            if key != "payload_json"
        } | {"payload": payload}

    def prune(self, retention_days: int) -> int:
        days = max(1, int(retention_days))
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM agent_trace WHERE created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)", (days,))
                count = cursor.rowcount
                cursor.close()
                return max(0, count)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM agent_trace WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            return cursor.rowcount

    def delete_user(self, user_id: str) -> int:
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM agent_trace WHERE user_id=%s", (str(user_id),))
                count = cursor.rowcount
                cursor.close()
                return max(0, count)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM agent_trace WHERE user_id=?", (str(user_id),)
            )
            return max(0, cursor.rowcount)


agent_trace_store = AgentTraceStore()
