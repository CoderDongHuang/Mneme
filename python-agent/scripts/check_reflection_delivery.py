"""Real Redis atomic reflection counter and delivery replay acceptance.

Uses exact unique QA users/keys; never changes a production stream or setting.
"""
import concurrent.futures
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.memory.reflection_scheduler import ReflectionScheduler  # noqa: E402
from reflection_qa import remove_probe_users  # noqa: E402


def check():
    user = "reflection-delivery-qa-" + uuid.uuid4().hex
    other = user + "-other"
    first, second = ReflectionScheduler(), ReflectionScheduler()
    client = first._redis
    scopes = [(user, "session", "turn"), (user, "other-session", "turn"),
              (user, "session", "other-turn"), (other, "session", "turn"),
              (user, "repair", "new-turn")]
    keys = [first._counter_key(user), first._counter_key(other)]
    keys.extend(first._delivery_key(*scope) for scope in scopes)
    try:
        # Different instances race on one logical delivery, including after a
        # response was lost. Only one increment can take effect.
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda i: (first if i % 2 else second).record_session(*scopes[0]), range(32)))
        assert results == [1] * 32
        counter, marker = keys[0], first._delivery_key(*scopes[0])
        assert 0 < client.ttl(counter) <= 604800
        assert 0 < client.ttl(marker) <= 604800
        assert first.record_session(*scopes[1]) == 2
        assert first.record_session(*scopes[2]) == 3
        assert first.record_session(*scopes[3]) == 1
        # Consumed work must not be resurrected by a replay or new process.
        client.delete(counter)
        assert ReflectionScheduler().record_session(*scopes[0]) == 0
        assert not client.exists(counter)
        # Repair a legacy non-expiring counter in the same atomic operation.
        client.set(counter, 2)
        assert first.record_session(*scopes[4]) == 3
        assert 0 < client.ttl(counter) <= 604800
        # Preserve an existing retention deadline; retries must not extend it.
        client.expire(counter, 60)
        client.expire(marker, 45)
        assert second.record_session(*scopes[0]) == 3
        assert 0 < client.ttl(counter) <= 60
        assert 0 < client.ttl(marker) <= 45
        print(json.dumps({"real_redis": True, "concurrent_replay": "passed",
                          "tenant_session_turn_isolation": "passed", "consumed_replay": "passed",
                          "atomic_ttl_and_legacy_repair": "passed", "retention_preserved": "passed"}))
    finally:
        client.delete(*keys)
        assert not client.exists(*keys)
        remove_probe_users(user, other)


if __name__ == "__main__":
    check()
