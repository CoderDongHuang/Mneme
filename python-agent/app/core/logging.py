import json
import logging
import re
import sys
import hashlib
from contextvars import ContextVar
from typing import TextIO

from app.core.config import settings


trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


def log_identifier(value: str) -> str:
    """Stable correlation without exposing externally supplied identifiers."""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:24] if value else ""


def memory_log_fields(
    operation: str, result: str, *, user_id: str = "", memory_id: str = "",
    category: str = "", content: str = "", source_session_id: str = "",
) -> str:
    """Allowlist metadata; content is used only to compute its length.

    Legacy memory IDs may embed a user ID, so hash them too. Operators can hash
    the ID from an authorized detail view to correlate a diagnostic record.
    """
    return json.dumps({
        "operation": operation, "result": result,
        "user_id_hash": log_identifier(user_id),
        "memory_id_hash": log_identifier(memory_id),
        "category": category if category in {"preference", "weak_point", "progress"} else "unknown",
        "content_length": len(content),
        "source_session_id_hash": log_identifier(source_session_id),
    }, ensure_ascii=False)


def redact_log(value: str) -> str:
    # Known server secrets, bearer tokens and email addresses are never diagnostic output.
    for field in ("deepseek_api_key", "dashscope_api_key", "internal_service_token",
                  "internal_service_token_previous", "admin_api_token", "mysql_password", "redis_password"):
        secret = str(getattr(settings, field, "") or "")
        if len(secret) >= 4:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)Bearer\s+[^\s,;\"']+", "Bearer [REDACTED]", value)
    value = re.sub(r"(?i)(api[_-]?key|password|token|secret)(\s*['\"]?\s*[:=]\s*['\"]?)[^\s,;}\"']+", r"\1\2[REDACTED]", value)
    return re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[EMAIL]", value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": redact_log(record.getMessage()),
            "timestamp": self.formatTime(record),
            "trace_id": trace_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = redact_log(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_utf8_stream(stream: TextIO) -> TextIO:
    encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
    if encoding not in {"utf8", "utf8sig"} and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, OSError, ValueError):
            pass
    return stream


def setup_logger(name: str) -> logging.Logger:
    configure_utf8_stream(sys.stdout)
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(configure_utf8_stream(sys.stderr))
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    return logger
