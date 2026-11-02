"""User-scoped processing consent; storage failures must not enable cloud calls."""
import sqlite3
from pathlib import Path
from app.core.config import settings
from app.storage.mysql import connection as mysql_connection
from app.knowledge.generations import generation_store, StaleGeneration


class PrivacyStore:
    def __init__(self, path: str | None = None):
        self.path = Path(path or str(Path(settings.agent_trace_store_path).with_name("privacy.sqlite3")))

    def _local(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE IF NOT EXISTS user_privacy (user_id TEXT PRIMARY KEY, cloud_allowed INTEGER NOT NULL, trace_days INTEGER NOT NULL)")
        return conn

    def get(self, user_id: str) -> dict:
        if generation_store.snapshot(user_id).get("deleted"):
            # Erasing a policy must not restore its default cloud consent.
            return {"cloud_allowed": False, "trace_days": settings.agent_trace_retention_days}
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT cloud_allowed,trace_days FROM user_privacy WHERE user_id=%s", (str(user_id),))
                row = cursor.fetchone()
                cursor.close()
        else:
            with self._local() as conn:
                row = conn.execute("SELECT cloud_allowed,trace_days FROM user_privacy WHERE user_id=?", (str(user_id),)).fetchone()
        return {"cloud_allowed": bool(row["cloud_allowed"]) if row else True,
                "trace_days": min(int(row["trace_days"]) if row else settings.agent_trace_retention_days, settings.agent_trace_retention_days)}

    def save(self, user_id: str, cloud_allowed: bool, trace_days: int) -> dict:
        if not isinstance(cloud_allowed, bool) or not 1 <= trace_days <= settings.agent_trace_retention_days:
            raise ValueError("invalid privacy policy")
        with generation_store.locked(user_id) as state:
            if state.get("deleted"):
                raise StaleGeneration("账号已删除，拒绝保存隐私设置")
            self._save(user_id, cloud_allowed, trace_days)
        return self.get(user_id)

    def _save(self, user_id: str, cloud_allowed: bool, trace_days: int) -> None:
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("INSERT INTO user_privacy(user_id,cloud_allowed,trace_days) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE cloud_allowed=VALUES(cloud_allowed),trace_days=VALUES(trace_days)", (str(user_id), cloud_allowed, trace_days))
                cursor.close()
        else:
            with self._local() as conn:
                conn.execute("INSERT INTO user_privacy VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET cloud_allowed=excluded.cloud_allowed,trace_days=excluded.trace_days", (str(user_id), cloud_allowed, trace_days))

    def delete(self, user_id: str) -> None:
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM user_privacy WHERE user_id=%s", (str(user_id),))
                cursor.close()
        else:
            with self._local() as conn:
                conn.execute("DELETE FROM user_privacy WHERE user_id=?", (str(user_id),))
        if self.count_user(user_id) != 0:
            raise RuntimeError("隐私设置删除后仍有残留")

    def count_user(self, user_id: str) -> int:
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT COUNT(*) FROM user_privacy WHERE user_id=%s", (str(user_id),))
                    return int(cursor.fetchone()[0])
                finally:
                    cursor.close()
        with self._local() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM user_privacy WHERE user_id=?", (str(user_id),)).fetchone()[0])


    def policies(self) -> list[dict]:
        if settings.auxiliary_store_backend == "mysql":
            with mysql_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT user_id,trace_days FROM user_privacy")
                rows = cursor.fetchall()
                cursor.close()
        else:
            with self._local() as conn:
                rows = conn.execute("SELECT user_id,trace_days FROM user_privacy").fetchall()
        return [dict(row) for row in rows]


privacy_store = PrivacyStore()


def require_cloud_processing(user_id: str) -> None:
    if generation_store.snapshot(user_id).get("deleted"):
        raise StaleGeneration("账号已删除，拒绝外部模型处理")
    if not privacy_store.get(user_id)["cloud_allowed"]:
        raise PermissionError("用户已禁止外部模型处理，需在数据与隐私中授权")
