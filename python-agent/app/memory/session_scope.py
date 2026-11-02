"""Short synchronous account transactions shared by session cache layers.

Never hold this scope over a model call, await or executor submission. Reentry
is thread-local so copying a request ContextVar cannot bypass a database lock.
"""
from contextlib import contextmanager
from hashlib import sha256
from threading import local
from uuid import uuid4

from app.knowledge.generations import generation_store, StaleGeneration

_current = local()


@contextmanager
def account_session(user_id="default", *, cleanup=False):
    user_id = str(user_id)
    active = getattr(_current, "active", None)
    if active is not None:
        owner, state = active
        if owner != user_id:
            raise RuntimeError("会话事务不允许切换账号")
        if state.get("deleted") and not cleanup:
            raise StaleGeneration("账号已删除，拒绝访问会话记忆")
        yield state
        return
    with generation_store.locked(user_id) as state:
        if state.get("deleted") and not cleanup:
            raise StaleGeneration("账号已删除，拒绝访问会话记忆")
        _current.active = (user_id, state)
        try:
            yield state
        finally:
            del _current.active


def cache_key(user_id, session_id):
    # Retain the old standalone default namespace for internal callers. Actual
    # HTTP/runtime paths always supply the authenticated account explicitly.
    return session_id if str(user_id) == "default" else (str(user_id), session_id)


def session_revision(state, session_id):
    revisions = state.get("session_memory_revisions", {})
    if not isinstance(revisions, dict):
        raise ValueError("会话缓存版本损坏")
    revision = revisions.get(sha256(session_id.encode()).hexdigest(), "")
    if not isinstance(revision, str) or (revision and (
        len(revision) != 32 or any(char not in "0123456789abcdef" for char in revision)
    )):
        raise ValueError("会话缓存版本损坏")
    return revision


def advance_revision(state, session_id):
    session_revision(state, session_id)  # Fail closed on corrupt state.
    # Non-reusable token: a Redis write followed by a DB rollback must never
    # accidentally match the next committed write after a cache outage.
    revision = uuid4().hex
    state.setdefault("session_memory_revisions", {})[sha256(session_id.encode()).hexdigest()] = revision
    return revision
