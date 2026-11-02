from types import SimpleNamespace
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

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def ping(self):
        return True

    def expire(self, key, seconds):
        return True

    def get(self, key):
        return self.leases.get(key, self.states.get(key, self.values.get(key)))

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.leases:
            return False
        self.leases[key] = value
        return True

    def eval(self, script, key_count, *args):
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
