"""SQL-authoritative session history and delivery receipts.

The caller holds account_session; history, receipt and revision commit together.
Redis is a disposable mirror. No model/provider work runs in this transaction.
"""
import hashlib
import json
import math
from datetime import timedelta

from app.core.config import settings
from app.core.time import utc_now
from app.memory.session_scope import advance_revision_for_key, session_deleted
from app.models.chat import Message


def session_key(session_id):
    return hashlib.sha256(session_id.encode()).hexdigest()


def _entries(state):
    entries = state.get("session_histories", {})
    if not isinstance(entries, dict):
        raise ValueError("会话持久历史损坏") from None
    return entries


def bucket(state, session_id):
    return _bucket_for_key(state, session_key(session_id), utc_now().timestamp())


def _bucket_for_key(state, key, now):
    value = _entries(state).get(key)
    if value is None:
        return None
    if isinstance(value, dict) and set(value) == {"expired"} and value["expired"] is True:
        return value
    try:
        if not isinstance(value, dict) or set(value) != {"messages", "deliveries", "expires_at"}:
            raise ValueError
        expiry = value["expires_at"]
        if type(expiry) not in (int, float) or not math.isfinite(expiry):
            raise ValueError
        if not isinstance(value["messages"], list) or not isinstance(value["deliveries"], dict):
            raise ValueError
        for receipt_key, digest in value["deliveries"].items():
            if any(not isinstance(item, str) or len(item) != 64 or any(c not in "0123456789abcdef" for c in item)
                   for item in (receipt_key, digest)):
                raise ValueError
        for item in value["messages"]:
            if not isinstance(item, dict) or set(item) != set(Message.model_fields):
                raise ValueError
            Message.model_validate(item, strict=True)
    except Exception:
        # ValidationError can contain private field values. Never propagate it.
        raise ValueError("会话持久历史损坏") from None
    if expiry <= now:
        value = {"expired": True}
        advance_revision_for_key(state, key)
        state["session_histories"][key] = value
    return value


def expire_user(state, *, now=None):
    """Caller owns the account transaction; rollback the whole user on error.

    Keep expired markers and revision fences: removing the bucket would allow
    an unmigrated legacy Redis mirror to be imported on the next request.
    """
    if not isinstance(state, dict):
        raise ValueError("会话持久历史损坏") from None
    now = utc_now().timestamp() if now is None else now
    expired = 0
    for key, value in _entries(state).items():
        if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("会话持久历史损坏") from None
        was_expired = value == {"expired": True}
        current = _bucket_for_key(state, key, now)
        if current == {"expired": True} and not was_expired:
            expired += 1
    return expired


def messages(value):
    return [Message.model_validate(item) for item in value.get("messages", [])]


def save(state, session_id, history):
    previous = bucket(state, session_id)
    state.setdefault("session_histories", {})[session_key(session_id)] = {
        "messages": [message.model_dump() for message in history],
        "deliveries": dict((previous or {}).get("deliveries", {})),
        "expires_at": (utc_now() + timedelta(hours=settings.SESSION_TTL_HOURS)).timestamp(),
    }


def delivery(message, delivery_id):
    if not isinstance(delivery_id, str) or not delivery_id.strip() or len(delivery_id) > 64:
        raise ValueError("会话消息投递标识无效")
    def digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    return digest([message.role, delivery_id]), digest([message.role, message.content])


def already_delivered(state, session_id, message, delivery_id):
    key, digest = delivery(message, delivery_id)
    previous = (bucket(state, session_id) or {}).get("deliveries", {}).get(key)
    if previous is not None and previous != digest:
        raise ValueError("同一投递标识的消息内容发生变化")
    return previous is not None


def record_delivery(state, session_id, message, delivery_id):
    key, digest = delivery(message, delivery_id)
    state["session_histories"][session_key(session_id)]["deliveries"][key] = digest


def clear(state, session_id):
    _entries(state)  # Reject corrupt state rather than hiding residuals.
    if state.get("deleted") or session_deleted(state, session_id):
        state.get("session_histories", {}).pop(session_key(session_id), None)
    else:
        # An explicitly cleared live session must never reimport an old mirror.
        state.setdefault("session_histories", {})[session_key(session_id)] = {"expired": True}


def count_user(user_id):
    from app.knowledge.generations import generation_store
    # Raw accounting: expiry/deletion filters must not hide retained data.
    return len(_entries(generation_store.snapshot(user_id)))
