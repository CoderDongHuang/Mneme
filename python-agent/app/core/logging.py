import logging
import json
from .config import settings

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
            "timestamp": self.formatTime(record),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry, ensure_ascii=False)

def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL))
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)
    return logger
