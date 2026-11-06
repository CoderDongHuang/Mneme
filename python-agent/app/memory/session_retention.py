"""Small SQL-only expiry sweeps; no model, Redis or Qdrant dependency."""
from threading import Lock

from app.core.logging import setup_logger, memory_log_fields
from app.knowledge.generations import generation_store
from app.memory.session_history import expire_user

logger = setup_logger("session_retention")


class SessionHistoryRetention:
    def __init__(self, store=None, *, batch_size=100):
        if type(batch_size) is not int or not 1 <= batch_size <= 1000:
            raise ValueError("Invalid history retention batch size")
        self.store = store or generation_store
        self.batch_size = batch_size
        self._after = None
        self._lock = Lock()

    def run_batch(self):
        # APScheduler also limits concurrent instances. This guard protects
        # direct operational calls; separate replicas serialize via SQL.
        with self._lock:
            result = {"scanned": 0, "expired": 0, "failed": 0}
            try:
                users = self.store.user_page(self._after, limit=self.batch_size)
            except Exception as error:
                logger.warning("error_type=%s %s", type(error).__name__,
                               memory_log_fields("history_retention_scan", "failed"))
                return {**result, "failed": 1}
            for user_id in users:
                result["scanned"] += 1
                try:
                    with self.store.locked(user_id) as state:
                        count = expire_user(state)
                    result["expired"] += count  # Count only acknowledged commits.
                except Exception as error:
                    result["failed"] += 1
                    # No exception body/traceback: SQL/JSON can contain history.
                    logger.warning("error_type=%s %s", type(error).__name__,
                                   memory_log_fields("history_retention", "failed", user_id=user_id))
            # A bad user cannot block everyone behind it. Retry it next cycle.
            # A restart begins a fresh cycle; the cursor is intentionally not a
            # deletion receipt and stores no private history or session IDs.
            self._after = users[-1] if len(users) == self.batch_size else None
            if result["expired"] or result["failed"]:
                logger.info("scanned=%d expired=%d failed=%d %s", *result.values(),
                            memory_log_fields("history_retention_batch", "completed" if not result["failed"] else "partial"))
            return result


session_history_retention = SessionHistoryRetention()
