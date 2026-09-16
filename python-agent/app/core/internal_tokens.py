import hashlib
import hmac
import threading
from datetime import datetime, timezone

from app.core.config import settings


class InternalTokenState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._current = settings.internal_service_token
        self._previous = settings.internal_service_token_previous
        self._rotated_at = ""

    def accepts(self, supplied: str) -> bool:
        if not supplied:
            return False
        with self._lock:
            if not self._rotated_at and settings.internal_service_token != self._current:
                self._current = settings.internal_service_token
                self._previous = settings.internal_service_token_previous
            return hmac.compare_digest(supplied, self._current) or (
                bool(self._previous) and hmac.compare_digest(supplied, self._previous)
            )

    def rotate(self, next_token: str) -> dict:
        if len(next_token) < 32:
            raise ValueError("内部服务令牌至少需要 32 个字符")
        with self._lock:
            self._previous = self._current
            self._current = next_token
            self._rotated_at = datetime.now(timezone.utc).isoformat()
            return self._status_unlocked()

    def status(self) -> dict:
        with self._lock:
            return self._status_unlocked()

    def _status_unlocked(self) -> dict:
        return {
            "current_fingerprint": hashlib.sha256(self._current.encode()).hexdigest()[:16],
            "previous_configured": bool(self._previous),
            "rotated_at": self._rotated_at,
        }


internal_tokens = InternalTokenState()
