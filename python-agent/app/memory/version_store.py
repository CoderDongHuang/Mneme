import json
import sqlite3
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.storage.mysql import connection as mysql_connection


class MemoryVersionStore:
    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path or settings.memory_version_store_path)
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
                    CREATE TABLE IF NOT EXISTS memory_version (
                        id BIGINT AUTO_INCREMENT PRIMARY KEY,
                        memory_id VARCHAR(128) NOT NULL, user_id VARCHAR(128) NOT NULL,
                        version INT NOT NULL, action VARCHAR(64) NOT NULL, content LONGTEXT NOT NULL,
                        metadata_json JSON NOT NULL, created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uk_memory_version (memory_id, version),
                        INDEX idx_memory_version_owner (user_id, memory_id, version)
                    )
                """)
                cursor.close()
            self.prune(settings.memory_version_retention_days)
            return
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS memory_version (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(memory_id, version)
                )
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_memory_version_owner
                ON memory_version(user_id, memory_id, version DESC)
                """
            )
        self.prune(settings.memory_version_retention_days)

    def snapshot(self, memory: dict[str, Any] | None, action: str) -> int | None:
        if not memory:
            return None
        memory_id = str(memory.get("id", ""))
        user_id = str(memory.get("user_id", ""))
        if not memory_id or not user_id:
            return None
        metadata = {
            key: value
            for key, value in memory.items()
            if key not in {"id", "content"} and value is not None
        }
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor()
                lock_name = f"mneme-memory-version:{memory_id}"[:64]
                cursor.execute("SELECT GET_LOCK(%s, 10)", (lock_name,))
                if cursor.fetchone()[0] != 1:
                    cursor.close()
                    raise RuntimeError("无法取得记忆版本写入锁")
                try:
                    cursor.execute("SELECT COALESCE(MAX(version), 0) FROM memory_version WHERE memory_id=%s", (memory_id,))
                    version = int(cursor.fetchone()[0]) + 1
                    cursor.execute("INSERT INTO memory_version(memory_id,user_id,version,action,content,metadata_json) VALUES(%s,%s,%s,%s,%s,%s)", (memory_id, user_id, version, action, str(memory.get("content", "")), json.dumps(metadata, ensure_ascii=False, sort_keys=True)))
                    return version
                finally:
                    cursor.execute("SELECT RELEASE_LOCK(%s)", (lock_name,))
                    cursor.close()
        with self._connect() as connection:
            current = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM memory_version WHERE memory_id=?",
                (memory_id,),
            ).fetchone()[0]
            version = int(current) + 1
            connection.execute(
                """
                INSERT INTO memory_version(memory_id,user_id,version,action,content,metadata_json)
                VALUES(?,?,?,?,?,?)
                """,
                (
                    memory_id,
                    user_id,
                    version,
                    action,
                    str(memory.get("content", "")),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            return version

    def list_versions(self, user_id: str, memory_id: str) -> list[dict[str, Any]]:
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                cursor.execute("SELECT id,memory_id,user_id,version,action,content,metadata_json,created_at FROM memory_version WHERE user_id=%s AND memory_id=%s ORDER BY version DESC", (user_id, memory_id))
                rows = cursor.fetchall()
                cursor.close()
            return [self._shared_row(row) for row in rows]
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id,memory_id,user_id,version,action,content,metadata_json,created_at
                FROM memory_version
                WHERE user_id=? AND memory_id=?
                ORDER BY version DESC
                """,
                (user_id, memory_id),
            ).fetchall()
        return [self._row(row) for row in rows]

    def get_version(
        self, user_id: str, memory_id: str, version: int | None = None
    ) -> dict[str, Any] | None:
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                if version is None:
                    cursor.execute("SELECT id,memory_id,user_id,version,action,content,metadata_json,created_at FROM memory_version WHERE user_id=%s AND memory_id=%s ORDER BY version DESC LIMIT 1", (user_id, memory_id))
                else:
                    cursor.execute("SELECT id,memory_id,user_id,version,action,content,metadata_json,created_at FROM memory_version WHERE user_id=%s AND memory_id=%s AND version=%s", (user_id, memory_id, version))
                row = cursor.fetchone()
                cursor.close()
            return self._shared_row(row) if row else None
        params: tuple[Any, ...]
        if version is None:
            sql = """
                SELECT id,memory_id,user_id,version,action,content,metadata_json,created_at
                FROM memory_version
                WHERE user_id=? AND memory_id=?
                ORDER BY version DESC
                LIMIT 1
            """
            params = (user_id, memory_id)
        else:
            sql = """
                SELECT id,memory_id,user_id,version,action,content,metadata_json,created_at
                FROM memory_version
                WHERE user_id=? AND memory_id=? AND version=?
            """
            params = (user_id, memory_id, version)
        with self._connect() as connection:
            row = connection.execute(sql, params).fetchone()
        return self._row(row) if row else None

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        metadata = json.loads(row["metadata_json"])
        return {
            "id": row["id"],
            "memory_id": row["memory_id"],
            "user_id": row["user_id"],
            "version": row["version"],
            "action": row["action"],
            "content": row["content"],
            "metadata": metadata,
            "created_at": row["created_at"],
        }

    @staticmethod
    def _shared_row(row: dict[str, Any]) -> dict[str, Any]:
        metadata = row["metadata_json"]
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        return {
            key: (str(value) if key == "created_at" else value)
            for key, value in row.items()
            if key != "metadata_json"
        } | {"metadata": metadata}

    def prune(self, retention_days: int) -> int:
        days = max(1, int(retention_days))
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM memory_version WHERE created_at < DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s DAY)", (days,))
                count = cursor.rowcount
                cursor.close()
                return max(0, count)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memory_version WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            return cursor.rowcount

    def delete_user(self, user_id: str) -> int:
        if self.shared:
            with mysql_connection() as connection:
                cursor = connection.cursor()
                cursor.execute("DELETE FROM memory_version WHERE user_id=%s", (str(user_id),))
                count = cursor.rowcount
                cursor.close()
                return max(0, count)
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM memory_version WHERE user_id=?", (str(user_id),)
            )
            return max(0, cursor.rowcount)


memory_version_store = MemoryVersionStore()
