"""Atomic session metadata with durable per-account deletion fencing.

Files remain a single-host cache. Replicas require shared storage as well as
the MySQL account lock; the lock alone does not replicate local files.
"""
import json
import os
import tempfile
import threading
from hashlib import sha256
from contextlib import contextmanager
from datetime import timedelta

from app.core.config import settings
from app.core.logging import setup_logger
from app.core.time import utc_now, parse_utc
from app.knowledge.generations import generation_store, StaleGeneration
from app.memory.session_scope import require_active_session, session_deleted

logger = setup_logger("session_store")
DATA_DIR = settings.session_data_path
SESSION_TTL_DAYS = 30


class SessionStore:
    def __init__(self, data_dir: str = DATA_DIR):
        self._data_dir = data_dir
        self._lock = threading.RLock()
        os.makedirs(self._data_dir, exist_ok=True)

    def _get_file_path(self, user_id: str) -> str:
        safe_name = user_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self._data_dir, f"{safe_name}.json")

    def _load(self, user_id):
        # Corruption is not empty: overwriting could lose the cleanup scope.
        try:
            with open(self._get_file_path(user_id), encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        if not isinstance(data, dict) or any(
            not isinstance(key, str) or not key or len(key) > 128 or not isinstance(value, dict)
            for key, value in data.items()
        ):
            raise ValueError("会话清理清单损坏，无法确认范围")
        for info in data.values():
            receipts = info.get("message_deliveries", {})
            if not isinstance(receipts, dict) or any(
                not isinstance(key, str) or len(key) != 64
                or any(char not in "0123456789abcdef" for char in key) or value is not True
                for key, value in receipts.items()
            ):
                raise ValueError("会话计数回执损坏，拒绝重复计数")
        return data

    def owns_legacy_cache(self, user_id, session_id):
        """Strict legacy ownership read inside the caller's account scope.

        Do not enter another generation transaction: cache reads already hold
        the shared account lock. No TTL pruning or manifest writes occur here.
        """
        with self._lock:
            info = self._load(str(user_id)).get(session_id)
            return isinstance(info, dict) and str(info.get("user_id", "")) == str(user_id)

    @contextmanager
    def _changing(self, user_id, session_id=None):
        # Serialize the complete read/modify/write across store instances.
        # No model or network call runs under this short account-row lock.
        with generation_store.locked(user_id) as state, self._lock:
            if state.get("deleted"):
                raise StaleGeneration("账号已删除，拒绝写入会话清单")
            if session_id is not None:
                require_active_session(state, session_id)
            yield state

    def _save(self, user_id, data):
        """Compatibility entry point: direct writes also obey the fence."""
        with self._changing(user_id) as state:
            for session_id in data:
                require_active_session(state, session_id)
            self._write(user_id, data)

    def _write(self, user_id, data):
        """Atomic publication; failed writes preserve the previous manifest."""
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._data_dir,
                                             prefix=".session-", suffix=".tmp", delete=False) as handle:
                temporary = handle.name
                json.dump(data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._get_file_path(user_id))
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _delivery_key(delivery_id, role):
        if not isinstance(delivery_id, str) or len(delivery_id) > 64 or (delivery_id and not delivery_id.strip()):
            raise ValueError("会话投递编号无效")
        return sha256(json.dumps([role, delivery_id], separators=(",", ":")).encode()).hexdigest() if delivery_id else None

    def register_session(self, user_id: str, session_id: str, title: str = "", message_count: int = 0,
                         *, delivery_id: str = ""):
        delivery = self._delivery_key(delivery_id, "user")
        with self._changing(user_id, session_id):
            data = self._load(user_id)
            if delivery and delivery in data.get(session_id, {}).get("message_deliveries", {}):
                return
            now = utc_now().isoformat()
            if session_id in data:
                existing = data[session_id]
                existing["message_count"] = message_count or existing.get("message_count", 0) + 1
                existing["last_updated"] = now
                if title and existing.get("title", "").startswith("新对话"):
                    existing["title"] = title
            else:
                data[session_id] = {
                    "user_id": user_id, "title": title or "新对话",
                    "message_count": max(message_count, 1), "created_at": now, "last_updated": now,
                }
            if delivery:
                # Count and receipt share the atomic file publication. A lost
                # acknowledgement or a new worker cannot increment this turn again.
                data[session_id].setdefault("message_deliveries", {})[delivery] = True
            self._write(user_id, data)

    def update_title(self, user_id: str, session_id: str, title: str):
        with self._changing(user_id, session_id):
            data = self._load(user_id)
            if session_id in data:
                data[session_id]["title"] = title[:50]
                data[session_id]["last_updated"] = utc_now().isoformat()
                self._write(user_id, data)

    def increment_message_count(self, user_id: str, session_id: str, *, delivery_id: str = "", commit_guard=None):
        delivery = self._delivery_key(delivery_id, "assistant")
        with self._changing(user_id, session_id) as state:
            if commit_guard is not None:
                commit_guard(state)
            data = self._load(user_id)
            if session_id in data:
                if delivery and delivery in data[session_id].get("message_deliveries", {}):
                    return
                data[session_id]["message_count"] = data[session_id].get("message_count", 0) + 1
                data[session_id]["last_updated"] = utc_now().isoformat()
                if delivery:
                    data[session_id].setdefault("message_deliveries", {})[delivery] = True
                self._write(user_id, data)

    def get_sessions(self, user_id: str) -> list[dict]:
        with generation_store.locked(user_id) as state, self._lock:
            if state.get("deleted"):
                return []
            data = self._load(user_id)
            cutoff = utc_now() - timedelta(days=SESSION_TTL_DAYS)
            expired = []
            for sid, info in data.items():
                try:
                    if parse_utc(info.get("last_updated", "")) < cutoff:
                        expired.append(sid)
                except (ValueError, TypeError):
                    pass
            for sid in expired:
                del data[sid]
            if expired:
                self._write(user_id, data)
            sessions = [{"id": sid, "title": info.get("title", "新对话"),
                         "message_count": info.get("message_count", 0),
                         "last_updated": info.get("last_updated", "")} for sid, info in data.items()
                        if not session_deleted(state, sid)]

            def updated_at(session):
                try:
                    return parse_utc(session["last_updated"]).timestamp()
                except (ValueError, TypeError):
                    return float("-inf")

            sessions.sort(key=updated_at, reverse=True)
            return sessions

    def delete_session(self, user_id: str, session_id: str):
        with self._changing(user_id, session_id):
            data = self._load(user_id)
            if session_id in data:
                del data[session_id]
                self._write(user_id, data)

    def purge_deleted_session(self, user_id: str, session_id: str):
        """Cleanup only, after the permanent session fence has committed."""
        with generation_store.locked(user_id) as state, self._lock:
            if not session_deleted(state, session_id):
                raise ValueError("会话清理需要持久删除围栏")
            data = self._load(user_id)
            if session_id in data:
                del data[session_id]
                self._write(user_id, data)
            if session_id in self._load(user_id):
                raise OSError("会话清单清理后仍有残留")

    def delete_user(self, user_id: str):
        file_path = self._get_file_path(user_id)
        with generation_store.locked(user_id), self._lock:
            try:
                if os.path.exists(file_path):
                    os.unlink(file_path)
                if os.path.lexists(file_path):
                    raise OSError("用户会话文件删除后仍有残留")
            except OSError as error:
                logger.error("用户会话文件删除失败: %s", type(error).__name__)
                raise

    def cleanup_session_ids(self, user_id: str) -> list[str]:
        """Raw strict enumeration, including expired sessions, after tombstone."""
        with generation_store.locked(user_id), self._lock:
            return list(self._load(user_id))

    def get_session_count(self, user_id: str) -> int:
        with generation_store.locked(user_id) as state, self._lock:
            return 0 if state.get("deleted") else sum(not session_deleted(state, sid) for sid in self._load(user_id))


session_store = SessionStore()
