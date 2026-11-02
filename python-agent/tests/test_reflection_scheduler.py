from types import SimpleNamespace
from contextlib import contextmanager
from hashlib import sha256
import pytest
import redis

import app.memory.reflection_scheduler as module


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.leases = {}
        self.states = {}
        self.stream = []
        self.acked = []
        self.deliveries = {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def ping(self):
        return True

    def expire(self, key, seconds):
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.deliveries.pop(key, None)
        return len(keys)

    def get(self, key):
        return self.leases.get(key, self.states.get(key, self.values.get(key)))

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.leases:
            return False
        self.leases[key] = value
        return True

    def eval(self, script, key_count, *args):
        if script == module._RECORD_SCRIPT:
            counter, delivery, _ttl = args
            if delivery not in self.deliveries:
                self.incr(counter)
            self.deliveries[delivery] = -1
            return int(self.values.get(counter, 0))
        if script == module._ENQUEUE_SCRIPT:
            job, lease, counter, queue, threshold, user, at, token = args
            count = int(self.values.get(counter, 0))
            if job in self.values or lease in self.leases or count < int(threshold):
                return 0
            entry = self.xadd(queue, dict(user_id=user, claimed_count=str(count),
                                         queued_at=at, job_token=token))
            self.values[job] = token
            return entry
        if script == module._CLAIM_SCRIPT:
            job, lease, state, job_token, token, _ttl = args
            if self.values.get(job) != job_token or lease in self.leases:
                return 0
            takeover = self.states.get(state) == "active"
            self.leases[lease] = token
            self.states[state] = "active"
            return 2 if takeover else 1
        if script == module._RENEW_SCRIPT:
            job, lease, job_token, owner, ttl = args
            return int(self.values.get(job) == job_token and self.leases.get(lease) == owner)
        assert script == module._COMPLETE_SCRIPT
        counter, lease, state, job, queue, job_token, token, claimed, group, message_id = args
        if self.values.get(job) != job_token or self.leases.get(lease) != token:
            return 0
        remaining = int(self.values.get(counter, 0)) - int(claimed)
        if remaining > 0:
            self.values[counter] = remaining
        else:
            self.values.pop(counter, None)
        self.leases.pop(lease, None)
        self.values.pop(job, None)
        self.states[state] = "completed"
        self.xack(queue, group, message_id)
        return 1

    def xgroup_create(self, *_args, **_kwargs):
        return True

    def xadd(self, _key, values):
        self.stream.append((b"1-0", values))
        return b"1-0"

    def xreadgroup(self, *_args, **_kwargs):
        return []

    def xautoclaim(self, *_args, **_kwargs):
        return (b"0-0", [], [])

    def xack(self, _key, _group, message_id):
        self.acked.append(message_id)
        return 1


def test_idle_queue_wait_fits_within_redis_socket_timeout(monkeypatch):
    options = {}

    def create_redis(**kwargs):
        options.update(kwargs)
        return FakeRedis()

    monkeypatch.setattr(module.redis, "Redis", create_redis)
    module.ReflectionScheduler()

    assert options["socket_timeout"] > module._QUEUE_BLOCK_MS / 1000


def test_delivery_retries_remain_deduplicated_after_consumption():
    fake = FakeRedis()
    first = module.ReflectionScheduler(redis_client=fake)
    second = module.ReflectionScheduler(redis_client=fake)
    assert first.record_session("u", "session", "turn") == 1
    assert second.record_session("u", "session", "turn") == 1
    fake.values.pop(first._counter_key("u"))
    assert second.record_session("u", "session", "turn") == 0
    assert first._counter_key("u") not in fake.values
    assert second.record_session("u", "session", "next-turn") == 1


def test_delivery_identity_is_user_session_and_turn_scoped():
    fake = FakeRedis()
    scheduler = module.ReflectionScheduler(redis_client=fake)
    assert scheduler.record_session("u", "session", "turn") == 1
    assert scheduler.record_session("u", "other-session", "turn") == 2
    assert scheduler.record_session("other-user", "session", "turn") == 1
    assert scheduler.record_session("u", "session", "other-turn") == 3
    assert scheduler._delivery_key("u", "a:b", "c") != scheduler._delivery_key("u", "a", "b:c")
    assert not fake.deliveries
    receipts = module.generation_store.snapshot("u")["reflection_deliveries"]
    assert len(receipts) == 2
    assert "session" not in str(receipts) and "turn" not in str(receipts)


@pytest.mark.parametrize("session,delivery", [("session", ""), ("", "turn")])
def test_partial_delivery_identity_rejected_before_counting(session, delivery):
    fake = FakeRedis()
    with pytest.raises(ValueError):
        module.ReflectionScheduler(redis_client=fake).record_session("u", session, delivery)
    assert not fake.values and not fake.deliveries


def test_retry_after_lost_record_response_does_not_count_again(monkeypatch):
    fake = FakeRedis()
    scheduler = module.ReflectionScheduler(redis_client=fake)
    evaluate = fake.eval

    def lose_response(*args):
        evaluate(*args)
        raise redis.ConnectionError("response lost after Redis applied script")

    monkeypatch.setattr(fake, "eval", lose_response)
    with pytest.raises(redis.ConnectionError):
        scheduler.record_session("u", "session", "turn")
    monkeypatch.setattr(fake, "eval", evaluate)
    assert scheduler.record_session("u", "session", "turn") == 1


def test_sql_commit_failure_keeps_nonexpiring_marker_after_consumption(monkeypatch):
    fake = FakeRedis()
    scheduler = module.ReflectionScheduler(redis_client=fake)
    locked = module.generation_store.locked

    @contextmanager
    def fail_commit(user):
        with locked(user) as state:
            yield state
            raise RuntimeError("SQL commit failed")

    monkeypatch.setattr(module.generation_store, "locked", fail_commit)
    with pytest.raises(RuntimeError, match="SQL commit failed"):
        scheduler.record_session("u", "session", "turn")
    marker = scheduler._delivery_key("u", "session", "turn")
    assert fake.deliveries[marker] == -1
    assert not module.generation_store.snapshot("u")
    # Even a consumed/expired counter cannot resurrect this pending delivery.
    fake.values.clear()
    monkeypatch.setattr(module.generation_store, "locked", locked)
    assert module.ReflectionScheduler(redis_client=fake).record_session("u", "session", "turn") == 0
    assert not fake.values and not fake.deliveries
    assert module.generation_store.snapshot("u")["reflection_deliveries"]


def test_sql_receipt_survives_missing_redis_marker_and_counter():
    fake = FakeRedis()
    scheduler = module.ReflectionScheduler(redis_client=fake)
    assert scheduler.record_session("u", "session", "turn") == 1
    fake.values.clear()
    fake.deliveries.clear()
    assert module.ReflectionScheduler(redis_client=fake).record_session("u", "session", "turn") == 0
    assert not fake.values and not fake.deliveries


def test_committed_receipt_survives_marker_cleanup_failure(monkeypatch, caplog):
    fake = FakeRedis()
    scheduler = module.ReflectionScheduler(redis_client=fake)
    delete = fake.delete

    def fail_delete(*_keys):
        raise redis.ConnectionError("private-message-marker")

    monkeypatch.setattr(fake, "delete", fail_delete)
    assert scheduler.record_session("u", "session", "turn") == 1
    assert not scheduler._redis_available
    assert "private-message-marker" not in caplog.text
    assert len(fake.deliveries) == 1
    monkeypatch.setattr(fake, "delete", delete)
    assert scheduler.record_session("u", "session", "turn") == 1
    assert not fake.deliveries


@pytest.mark.parametrize("receipts", [[], {"bad": {}}, {"a" * 64: []},
                                    {"a" * 64: {"b" * 64: 1}},
                                    {"a" * 64: {"bad": True}}])
def test_corrupt_receipts_fail_before_redis_mutation(receipts):
    fake = FakeRedis()
    with module.generation_store.locked("u") as state:
        state["reflection_deliveries"] = receipts
    with pytest.raises(ValueError, match="反思投递回执损坏"):
        module.ReflectionScheduler(redis_client=fake).record_session("u", "session", "turn")
    assert not fake.values and not fake.deliveries


def test_session_deletion_retires_receipts_without_reopening_delivery():
    from app.memory.session_scope import tombstone_session

    fake = FakeRedis()
    scheduler = module.ReflectionScheduler(redis_client=fake)
    scheduler.record_session("u", "session", "turn")
    scheduler.record_session("u", "other-session", "turn")
    tombstone_session("u", "session")
    receipts = module.generation_store.snapshot("u")["reflection_deliveries"]
    assert list(receipts) == [sha256(b"other-session").hexdigest()]
    with pytest.raises(module.StaleGeneration):
        scheduler.record_session("u", "session", "turn")
    assert scheduler.record_session("u", "other-session", "turn") == 2


def test_corrupt_receipts_do_not_rollback_session_tombstone():
    from app.memory.session_scope import tombstone_session, session_deleted

    with module.generation_store.locked("u") as state:
        state["reflection_deliveries"] = []
    with pytest.raises(ValueError, match="反思投递回执损坏"):
        tombstone_session("u", "session")
    assert session_deleted(module.generation_store.snapshot("u"), "session")


def test_reflection_is_persisted_to_stream_before_execution(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60),
    )
    scheduler = module.ReflectionScheduler(redis_client=fake)
    scheduler.record_session("u")
    assert scheduler.check_and_trigger("u") is True


def test_only_one_node_claims_shared_reflection(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(memory_reflection_every_sessions=2, memory_reflection_lease_seconds=60),
    )
    monkeypatch.setattr(module, "run_reflection", lambda user_id: None)
    first = module.ReflectionScheduler(redis_client=fake)
    second = module.ReflectionScheduler(redis_client=fake)

    first.record_session("u")
    second.record_session("u")
    assert first.check_and_trigger("u") is True
    assert second.check_and_trigger("u") is False
    assert len(fake.stream) == 1
    first._run_queued_reflection(*fake.stream[0])
    assert fake.acked == [b"1-0"]
    assert fake.values == {}


def test_failed_reflection_keeps_count_for_retry(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60),
    )
    calls = {"count": 0}

    def fail_once(_):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("temporary")

    monkeypatch.setattr(module, "run_reflection", fail_once)
    scheduler = module.ReflectionScheduler(redis_client=fake)
    scheduler.record_session("u")
    assert scheduler.check_and_trigger("u") is True
    scheduler._run_queued_reflection(*fake.stream[0])
    assert scheduler.check_and_trigger("u") is False
    fake.leases.clear()
    scheduler._run_queued_reflection(*fake.stream[0])
    assert fake.acked == [b"1-0"]
    assert fake.values == {}


def test_expired_shared_lease_is_counted_as_takeover(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(
        module,
        "settings",
        SimpleNamespace(memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60),
    )
    first = module.ReflectionScheduler(redis_client=fake)
    first.record_session("u")
    assert first.check_and_trigger("u") is True
    fake.leases.clear()

    second = module.ReflectionScheduler(redis_client=fake)
    assert second.check_and_trigger("u") is False
    job = fake.stream[0][1]["job_token"]
    assert first._claim_shared("u", job, "old")
    fake.leases.clear()
    assert second._claim_shared("u", job, "new")
    assert not first._complete_shared("u", 1, job, "old", b"1-0")
    assert second._complete_shared("u", 1, job, "new", b"1-0")


def test_unavailable_redis_never_acknowledges_in_memory_task(monkeypatch):
    fake = FakeRedis()
    scheduler = module.ReflectionScheduler(redis_client=fake)

    def unavailable(*_args, **_kwargs):
        raise redis.ConnectionError("offline")

    monkeypatch.setattr(fake, "incr", unavailable)
    monkeypatch.setattr(fake, "eval", unavailable)
    monkeypatch.setattr(fake, "ping", unavailable)
    with pytest.raises(redis.ConnectionError):
        scheduler.record_session("u")
    with pytest.raises(redis.ConnectionError):
        scheduler.check_and_trigger("u")
    assert not scheduler.queue_available()
    assert fake.stream == []
    assert not hasattr(scheduler, "_session_counts")
    monkeypatch.setattr(fake, "ping", lambda: True)
    assert scheduler.queue_available()


def test_failed_enqueue_releases_lease_without_reporting_success(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(module, "settings", SimpleNamespace(
        memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60))
    scheduler = module.ReflectionScheduler(redis_client=fake)
    scheduler.record_session("u")

    def unavailable(*_args, **_kwargs):
        raise redis.ConnectionError("offline")

    monkeypatch.setattr(fake, "xadd", unavailable)
    with pytest.raises(redis.ConnectionError):
        scheduler.check_and_trigger("u")
    assert fake.leases == {}
    assert fake.values[scheduler._counter_key("u")] == 1


def test_reclaimed_live_job_does_not_share_owner_or_execute_twice(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(module, "settings", SimpleNamespace(
        memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60))
    first = module.ReflectionScheduler(redis_client=fake)
    second = module.ReflectionScheduler(redis_client=fake)
    first.record_session("u")
    assert first.check_and_trigger("u")
    entry = fake.stream[0]
    calls = []

    def reflect(user):
        calls.append(user)
        second._run_queued_reflection(*entry)
        first.record_session(user)

    monkeypatch.setattr(module, "run_reflection", reflect)
    first._run_queued_reflection(*entry)
    assert calls == ["u"]
    assert fake.acked == [entry[0]]
    assert fake.values == {first._counter_key("u"): 1}
    first._run_queued_reflection(*entry)
    assert calls == ["u"]
    assert fake.values[first._counter_key("u")] == 1


def test_successful_model_does_not_ack_after_losing_lease(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(module, "settings", SimpleNamespace(
        memory_reflection_every_sessions=1, memory_reflection_lease_seconds=60))
    scheduler = module.ReflectionScheduler(redis_client=fake)
    scheduler.record_session("u")
    assert scheduler.check_and_trigger("u")
    monkeypatch.setattr(module, "run_reflection", lambda _: fake.leases.clear())
    scheduler._run_queued_reflection(*fake.stream[0])
    assert fake.acked == []
    assert fake.values[scheduler._counter_key("u")] == 1
    assert scheduler._job_key("u") in fake.values


def test_reclaim_advances_cursor_past_live_jobs(monkeypatch):
    scheduler = module.ReflectionScheduler(redis_client=FakeRedis())
    starts = []

    def reclaim(*_args, **kwargs):
        starts.append(kwargs["start_id"])
        return ["20-0" if len(starts) == 1 else "0-0", [], []]

    monkeypatch.setattr(scheduler._redis, "xautoclaim", reclaim)
    scheduler.reclaim_stale_reflections()
    scheduler.reclaim_stale_reflections()
    assert starts == ["0-0", "20-0"]
