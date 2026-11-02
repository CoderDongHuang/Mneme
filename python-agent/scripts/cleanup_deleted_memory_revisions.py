"""Idempotent upgrade cleanup; only legacy keys of durably deleted accounts."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory.cache_revision import memory_cache_revision  # noqa: E402


if __name__ == "__main__":
    print("Deleted legacy memory revision keys:", memory_cache_revision.cleanup_deleted_revisions())
