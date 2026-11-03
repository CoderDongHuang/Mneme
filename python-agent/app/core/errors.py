class MemoryIndexConflict(ValueError):
    """Memory vectors must be migrated before semantic reads or writes."""


class MemoryReadUnavailable(RuntimeError):
    """A required memory read failed; it must never be interpreted as empty."""
