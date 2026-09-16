import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.core.config import settings


class AgentTraceStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or settings.agent_trace_store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
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
        safe_payload = payload or {}
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


agent_trace_store = AgentTraceStore()
