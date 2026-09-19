import json
import logging
import sys
from contextvars import ContextVar
from typing import TextIO

from app.core.config import settings


trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record),
            "trace_id": trace_id_var.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
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
